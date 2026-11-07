"""Shared-policy Multi-Agent RL for warehouse navigation (Phase 9).

All robots in the fleet share a single DQN policy network (parameter sharing).  During
training each robot contributes independent (obs, action, reward, next_obs, done) transitions
to one shared replay buffer.  During inference the same policy is queried per robot per tick.

The trainer integrates with the existing experiment infrastructure:
  - Accepts a WarehouseEnv factory as `train_data`
  - Reports throughput, collision rate and mean episode reward as evaluation metrics
  - Saves weights to models/navigation_marl/<version>/weights.pt

Comparison with A* dispatch (baseline E4d) is done in the experiment runner
(configs/experiments/E9d.yaml) by setting `strategies.planner: marl` and providing
the trained weights path.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ai.common.base import AIModule, TrainResult
from ai.reinforcement_learning.dqn_agent import DQNNavigator, _ReplayBuffer, _TORCH
from ai.reinforcement_learning.env import N_ACTIONS, OBS_DIM, WarehouseEnv

if _TORCH:
    import torch


@dataclass
class MARLConfig:
    episodes: int = 300
    episode_ticks: int = 600          # one simulated hour per episode
    lr: float = 5e-4
    gamma: float = 0.99
    eps_start: float = 1.0
    eps_end: float = 0.05
    eps_decay: float = 0.998          # slower decay: more robots sharing one network
    batch_size: int = 128
    target_update: int = 1000
    buffer_capacity: int = 100_000
    seed: int = 42
    eval_episodes: int = 10

    @classmethod
    def from_dict(cls, d: dict) -> "MARLConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class SharedPolicyMARL(AIModule):
    """Shared-policy DQN for the full robot fleet.

    train_data: a WarehouseEnv factory (callable) or a MARLConfig-augmented env.
    predict({robot_id: obs}): returns {robot_id: action} for all robots in one tick.
    evaluate: runs eval_episodes episodes with ε=0; reports throughput vs baseline.
    """

    name = "navigation_marl"

    def __init__(self, cfg: MARLConfig | None = None) -> None:
        self.cfg = cfg or MARLConfig()
        # Underlying DQN — shared by all robots
        self._agent = DQNNavigator(
            obs_dim=OBS_DIM,
            n_actions=N_ACTIONS,
            lr=self.cfg.lr,
            gamma=self.cfg.gamma,
            eps_start=self.cfg.eps_start,
            eps_end=self.cfg.eps_end,
            eps_decay=self.cfg.eps_decay,
            batch_size=self.cfg.batch_size,
            target_update=self.cfg.target_update,
            buffer_capacity=self.cfg.buffer_capacity,
            seed=self.cfg.seed,
        )
        self._training_history: list[dict] = []

    # ----- AIModule interface ----------------------------------------------------

    def train(self, train_data: Any, val_data: Any | None = None) -> TrainResult:
        if not _TORCH:
            raise RuntimeError("PyTorch is required for MARL training (pip install torch)")

        env_factory = train_data if callable(train_data) else lambda s: train_data
        cfg = self.cfg
        ep_rewards: list[float] = []
        ep_deliveries: list[int] = []

        for ep in range(cfg.episodes):
            env: WarehouseEnv = env_factory(cfg.seed + ep)
            obs_dict = env.reset_multi(seed=cfg.seed + ep)
            ep_reward = 0.0
            ep_del = 0
            done = False

            while not done:
                # Action selection — one shared policy for all robots
                action_dict: dict[str, int] = {}
                for rid, obs in obs_dict.items():
                    if random.random() < self._agent.eps:
                        action_dict[rid] = random.randrange(N_ACTIONS)
                    else:
                        action_dict[rid] = self._agent.predict(obs)

                results = env.step_multi(action_dict)

                # Collect transitions from all robots into the shared buffer
                for rid, (next_obs, reward, truncated) in results.items():
                    obs = obs_dict[rid]
                    self._agent._buf.push(obs, action_dict[rid], reward, next_obs, float(truncated))
                    ep_reward += reward
                    if reward >= 10.0:
                        ep_del += 1

                # Training step if buffer has enough data
                if len(self._agent._buf) >= cfg.batch_size:
                    self._agent._update()

                obs_dict = {rid: r[0] for rid, r in results.items()}
                done = any(r[2] for r in results.values())

            ep_rewards.append(ep_reward)
            ep_deliveries.append(ep_del)
            self._agent.eps = max(cfg.eps_end, self._agent.eps * cfg.eps_decay)

            if (ep + 1) % 50 == 0:
                mean_r = float(np.mean(ep_rewards[-20:]))
                mean_d = float(np.mean(ep_deliveries[-20:]))
                self._training_history.append({
                    "episode": ep + 1,
                    "mean_reward": round(mean_r, 2),
                    "mean_deliveries": round(mean_d, 2),
                    "eps": round(self._agent.eps, 4),
                })

        version = f"marl_ep{cfg.episodes}"
        artifact = self.artifact_dir(version)
        self._agent._save_weights(artifact / "weights.pt")
        (artifact / "training_history.json").write_text(
            json.dumps(self._training_history, indent=2)
        )
        metrics = {
            "mean_reward_last20": float(np.mean(ep_rewards[-20:])),
            "mean_deliveries_last20": float(np.mean(ep_deliveries[-20:])),
            "episodes": cfg.episodes,
        }
        return TrainResult(
            model_name=self.name,
            version=version,
            metrics=metrics,
            artifact_path=artifact,
        )

    def predict(self, inputs: Any) -> Any:
        """inputs: {robot_id: obs_array} → {robot_id: action}."""
        if isinstance(inputs, dict):
            return {rid: self._agent.predict(obs) for rid, obs in inputs.items()}
        return self._agent.predict(inputs)

    def evaluate(self, test_data: Any) -> dict[str, float]:
        """Run eval_episodes with ε=0; report mean reward and orders/hour."""
        env_factory = test_data if callable(test_data) else lambda s: test_data
        cfg = self.cfg
        eps_saved, self._agent.eps = self._agent.eps, 0.0
        all_rewards, all_deliveries = [], []

        for ep in range(cfg.eval_episodes):
            env: WarehouseEnv = env_factory(cfg.seed + 1000 + ep)
            obs_dict = env.reset_multi(seed=cfg.seed + 1000 + ep)
            ep_reward, ep_del = 0.0, 0
            done = False
            while not done:
                action_dict = {rid: self._agent.predict(obs) for rid, obs in obs_dict.items()}
                results = env.step_multi(action_dict)
                for rid, (next_obs, reward, truncated) in results.items():
                    ep_reward += reward
                    if reward >= 10.0:
                        ep_del += 1
                obs_dict = {rid: r[0] for rid, r in results.items()}
                done = any(r[2] for r in results.values())
            all_rewards.append(ep_reward)
            all_deliveries.append(ep_del)

        self._agent.eps = eps_saved
        return {
            "mean_reward": float(np.mean(all_rewards)),
            "orders_per_episode": float(np.mean(all_deliveries)),
        }

    # ----- persistence -----------------------------------------------------------

    def save(self, version: str) -> Path:
        return self._agent.save(version.replace(self._agent.name, self.name))

    def load(self, version: str) -> None:
        path = self.artifact_dir(version) / "weights.pt"
        self._agent.load(version)

"""Deep Q-Network navigator for a single robot (Phase 9).

Architecture: 2-layer MLP (58 → 128 → 64 → 5).
Training: experience replay, target network soft-update every `target_update` steps.
Exploration: ε-greedy with exponential decay.

The shared-policy MARL trainer (marl.py) reuses this class with one shared network
instance and collects transitions from every robot in the fleet.
"""

from __future__ import annotations

import json
import random
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ai.common.base import AIModule, TrainResult
from ai.reinforcement_learning.env import N_ACTIONS, OBS_DIM, WarehouseEnv

# Optional PyTorch import — the module degrades gracefully without it so the rest of the
# project still imports and the backend starts even when torch is not installed.
try:
    import torch
    import torch.nn as nn
    import torch.optim as optim

    _TORCH = True
except ImportError:
    _TORCH = False


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------

if _TORCH:
    class _QNet(nn.Module):
        def __init__(self, obs_dim: int = OBS_DIM, n_actions: int = N_ACTIONS) -> None:
            super().__init__()
            self.net = nn.Sequential(
                nn.Linear(obs_dim, 128),
                nn.ReLU(),
                nn.Linear(128, 64),
                nn.ReLU(),
                nn.Linear(64, n_actions),
            )

        def forward(self, x):
            return self.net(x)
else:
    _QNet = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Replay buffer
# ---------------------------------------------------------------------------

@dataclass
class _ReplayBuffer:
    capacity: int = 50_000
    _buf: deque = field(init=False)

    def __post_init__(self) -> None:
        self._buf = deque(maxlen=self.capacity)

    def push(self, obs, action, reward, next_obs, done) -> None:
        self._buf.append((obs, action, reward, next_obs, done))

    def sample(self, batch_size: int):
        batch = random.sample(self._buf, batch_size)
        obs, act, rew, nobs, done = zip(*batch, strict=True)
        return (
            np.array(obs, dtype=np.float32),
            np.array(act, dtype=np.int64),
            np.array(rew, dtype=np.float32),
            np.array(nobs, dtype=np.float32),
            np.array(done, dtype=np.float32),
        )

    def __len__(self) -> int:
        return len(self._buf)


# ---------------------------------------------------------------------------
# DQN agent
# ---------------------------------------------------------------------------

class DQNNavigator(AIModule):
    """Single-robot DQN navigator.

    train_data: a WarehouseEnv factory (callable → WarehouseEnv)
    predict(obs): returns the greedy action for a given 58-dim observation
    evaluate: runs `eval_episodes` full episodes and returns mean reward + throughput
    """

    name = "navigation_dqn"

    def __init__(
        self,
        obs_dim: int = OBS_DIM,
        n_actions: int = N_ACTIONS,
        lr: float = 1e-3,
        gamma: float = 0.99,
        eps_start: float = 1.0,
        eps_end: float = 0.05,
        eps_decay: float = 0.995,
        batch_size: int = 64,
        target_update: int = 500,
        buffer_capacity: int = 50_000,
        seed: int = 42,
    ) -> None:
        self.seed = seed
        self.gamma = gamma
        self.eps = eps_start
        self.eps_end = eps_end
        self.eps_decay = eps_decay
        self.batch_size = batch_size
        self.target_update = target_update
        self._step = 0

        if not _TORCH:
            self._net = self._target = self._opt = self._buf = None
            return

        torch.manual_seed(seed)
        self._net = _QNet(obs_dim, n_actions)
        self._target = _QNet(obs_dim, n_actions)
        self._target.load_state_dict(self._net.state_dict())
        self._opt = optim.Adam(self._net.parameters(), lr=lr)
        self._buf = _ReplayBuffer(buffer_capacity)
        self._loss_fn = nn.SmoothL1Loss()

    # ----- AIModule interface ----------------------------------------------------

    def train(self, train_data: Any, val_data: Any | None = None) -> TrainResult:
        """train_data should be a WarehouseEnv (or factory → env)."""
        if not _TORCH:
            raise RuntimeError("PyTorch is required for DQN training (pip install torch)")
        env: WarehouseEnv = train_data() if callable(train_data) else train_data
        episodes = getattr(train_data, "episodes", 200)
        rewards, losses = [], []

        for ep in range(episodes):
            obs, _ = env.reset(seed=self.seed + ep)
            ep_reward = 0.0
            done = False
            while not done:
                action = self._select_action(obs)
                next_obs, reward, terminated, truncated, _ = env.step(action)
                done = terminated or truncated
                # Truncation is not a terminal state; only terminated ends the value chain.
                self._buf.push(obs, action, reward, next_obs, float(terminated))
                obs = next_obs
                ep_reward += reward
                if len(self._buf) >= self.batch_size:
                    losses.append(self._update())
            rewards.append(ep_reward)
            self.eps = max(self.eps_end, self.eps * self.eps_decay)

        mean_reward = float(np.mean(rewards[-20:])) if rewards else 0.0
        mean_loss = float(np.mean(losses[-100:])) if losses else 0.0
        version = f"dqn_ep{episodes}"
        artifact = self.artifact_dir(version)
        self._save_weights(artifact / "weights.pt")
        return TrainResult(
            model_name=self.name,
            version=version,
            metrics={"mean_reward_last20": mean_reward, "mean_loss": mean_loss, "episodes": episodes},
            artifact_path=artifact,
        )

    def predict(self, inputs: Any) -> Any:
        """Greedy action for a 58-dim observation array."""
        if not _TORCH or self._net is None:
            return 4  # WAIT fallback
        obs = np.asarray(inputs, dtype=np.float32)
        with torch.no_grad():
            q = self._net(torch.tensor(obs).unsqueeze(0))
        return int(q.argmax(dim=1).item())

    def evaluate(self, test_data: Any) -> dict[str, float]:
        """Run eval_episodes episodes with ε=0 and return mean reward + order throughput."""
        if not _TORCH:
            return {"mean_reward": 0.0, "orders_per_episode": 0.0}
        env: WarehouseEnv = test_data() if callable(test_data) else test_data
        eps_saved, self.eps = self.eps, 0.0
        rewards, deliveries = [], []
        eval_eps = getattr(test_data, "eval_episodes", 10)
        for ep in range(eval_eps):
            obs, _ = env.reset(seed=1000 + ep)
            ep_reward, ep_del = 0.0, 0
            done = False
            while not done:
                action = self._select_action(obs)
                obs, reward, terminated, truncated, info = env.step(action)
                ep_reward += reward
                done = terminated or truncated
                if reward >= 10.0:
                    ep_del += 1
            rewards.append(ep_reward)
            deliveries.append(ep_del)
        self.eps = eps_saved
        return {
            "mean_reward": float(np.mean(rewards)),
            "orders_per_episode": float(np.mean(deliveries)),
        }

    # ----- persistence -----------------------------------------------------------

    def save(self, version: str) -> Path:
        if not _TORCH or self._net is None:
            raise RuntimeError("No model to save")
        path = self.artifact_dir(version) / "weights.pt"
        self._save_weights(path)
        return path

    def load(self, version: str) -> None:
        if not _TORCH:
            raise RuntimeError("PyTorch required")
        path = self.artifact_dir(version) / "weights.pt"
        state = torch.load(path, map_location="cpu", weights_only=True)
        self._net.load_state_dict(state)
        self._target.load_state_dict(state)

    # ----- internal helpers ------------------------------------------------------

    def _select_action(self, obs: np.ndarray) -> int:
        if random.random() < self.eps:
            return random.randrange(N_ACTIONS)
        return self.predict(obs)

    def _update(self) -> float:
        obs, act, rew, nobs, done = self._buf.sample(self.batch_size)
        obs_t = torch.tensor(obs)
        act_t = torch.tensor(act).unsqueeze(1)
        rew_t = torch.tensor(rew)
        nobs_t = torch.tensor(nobs)
        done_t = torch.tensor(done)

        q_vals = self._net(obs_t).gather(1, act_t).squeeze(1)
        with torch.no_grad():
            next_q = self._target(nobs_t).max(1).values
            target = rew_t + self.gamma * next_q * (1 - done_t)

        loss = self._loss_fn(q_vals, target)
        self._opt.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self._net.parameters(), 10.0)
        self._opt.step()

        self._step += 1
        if self._step % self.target_update == 0:
            self._target.load_state_dict(self._net.state_dict())

        return float(loss.item())

    def _save_weights(self, path: Path) -> None:
        torch.save(self._net.state_dict(), path)

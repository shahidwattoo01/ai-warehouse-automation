"""DQN navigation policy over the Gym environment.

Phase 9 · Algorithms: Deep Q-Network (PyTorch)
Metrics: Success rate, collision rate, path length vs A*
Trains only on simulator-generated data (data/processed/), split by run.
"""

from __future__ import annotations

from typing import Any

from ai.common.base import AIModule, TrainResult


class DQNNavigator(AIModule):
    name = "navigation_dqn"

    def train(self, train_data: Any, val_data: Any | None = None) -> TrainResult:
        raise NotImplementedError("Phase 9")

    def predict(self, inputs: Any) -> Any:
        raise NotImplementedError("Phase 9")

    def evaluate(self, test_data: Any) -> dict[str, float]:
        raise NotImplementedError("Phase 9")

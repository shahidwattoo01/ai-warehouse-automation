"""Predict a robot's order completion time (ticks).

Phase 3 · Algorithms: Linear Regression, Random Forest, Gradient Boosting, XGBoost
Metrics: MAE, RMSE
Trains only on simulator-generated data (data/processed/), split by run.
"""

from __future__ import annotations

from typing import Any

from ai.common.base import AIModule, TrainResult


class ETAModel(AIModule):
    name = "eta"

    def train(self, train_data: Any, val_data: Any | None = None) -> TrainResult:
        raise NotImplementedError("Phase 3")

    def predict(self, inputs: Any) -> Any:
        raise NotImplementedError("Phase 3")

    def evaluate(self, test_data: Any) -> dict[str, float]:
        raise NotImplementedError("Phase 3")

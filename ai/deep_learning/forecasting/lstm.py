"""LSTM over sliding windows of hourly orders.

Phase 5 · Algorithms: PyTorch LSTM
Metrics: MAE, RMSE
Trains only on simulator-generated data (data/processed/), split by run.
"""

from __future__ import annotations

from typing import Any

from ai.common.base import AIModule, TrainResult


class LSTMForecaster(AIModule):
    name = "demand_lstm"

    def train(self, train_data: Any, val_data: Any | None = None) -> TrainResult:
        raise NotImplementedError("Phase 5")

    def predict(self, inputs: Any) -> Any:
        raise NotImplementedError("Phase 5")

    def evaluate(self, test_data: Any) -> dict[str, float]:
        raise NotImplementedError("Phase 5")

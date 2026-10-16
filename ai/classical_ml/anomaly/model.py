"""Flag robots behaving abnormally from telemetry windows.

Phase 3 · Algorithms: Isolation Forest, DBSCAN, z-score
Metrics: Precision, recall, F1 vs injected faults
Trains only on simulator-generated data (data/processed/), split by run.
"""

from __future__ import annotations

from typing import Any

from ai.common.base import AIModule, TrainResult


class AnomalyModel(AIModule):
    name = "anomaly"

    def train(self, train_data: Any, val_data: Any | None = None) -> TrainResult:
        raise NotImplementedError("Phase 3")

    def predict(self, inputs: Any) -> Any:
        raise NotImplementedError("Phase 3")

    def evaluate(self, test_data: Any) -> dict[str, float]:
        raise NotImplementedError("Phase 3")

"""Baseline command parser: TF-IDF intent classifier + regex entities.

Phase 6 · Algorithms: TF-IDF + Logistic Regression
Metrics: Intent accuracy / F1, entity F1
Trains only on simulator-generated data (data/processed/), split by run.
"""

from __future__ import annotations

from typing import Any

from ai.common.base import AIModule, TrainResult


class IntentParser(AIModule):
    name = "intent_baseline"

    def train(self, train_data: Any, val_data: Any | None = None) -> TrainResult:
        raise NotImplementedError("Phase 6")

    def predict(self, inputs: Any) -> Any:
        raise NotImplementedError("Phase 6")

    def evaluate(self, test_data: Any) -> dict[str, float]:
        raise NotImplementedError("Phase 6")

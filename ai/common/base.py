"""Common interface for every AI module (TRD TR-ENG-04).

Each module trains only on simulator-generated data, splits by simulation run,
uses a fixed seed, and reports metrics that are stored with its model version.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MODELS_DIR = Path(__file__).resolve().parents[2] / "models"


@dataclass
class TrainResult:
    model_name: str
    version: str
    metrics: dict[str, float]
    training_run_ids: list[str] = field(default_factory=list)
    artifact_path: Path | None = None


class AIModule(ABC):
    """Base class: train(), predict(), evaluate(), save(), load()."""

    name: str = "base"
    seed: int = 42

    @abstractmethod
    def train(self, train_data: Any, val_data: Any | None = None) -> TrainResult: ...

    @abstractmethod
    def predict(self, inputs: Any) -> Any: ...

    @abstractmethod
    def evaluate(self, test_data: Any) -> dict[str, float]: ...

    def artifact_dir(self, version: str) -> Path:
        path = MODELS_DIR / self.name / version
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save(self, version: str) -> Path:
        raise NotImplementedError

    def load(self, version: str) -> None:
        raise NotImplementedError


def split_by_run(run_ids: list[str], val: float = 0.15, test: float = 0.15, seed: int = 42):
    """Train/val/test split by simulation run so no run leaks across splits (TRD 8)."""
    import random

    ids = sorted(set(run_ids))
    random.Random(seed).shuffle(ids)
    n = len(ids)
    n_test, n_val = int(n * test), int(n * val)
    return ids[n_test + n_val :], ids[n_test : n_test + n_val], ids[:n_test]

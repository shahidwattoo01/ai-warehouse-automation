"""Phase 5 networks running live against the simulator (used by ai/classical_ml/live_predictor.py).

    LiveFaultLSTM    scores each robot's last 10 telemetry readings (20 ticks) for a fault
    LiveDemandNet    forecasts the orders of the coming simulated hour from the last 168 hours

The inputs are built exactly as in notebooks 07 and 08 (see anomaly.CHANNELS and
demand.STEP_FEATURES / TARGET_FEATURES). PyTorch is imported only when a network is loaded.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

BUSY_STATUSES = {"MOVING", "DELIVERING", "FAULT"}


def fault_channels(samples: list[tuple], previous: tuple | None) -> np.ndarray:
    """One window of live telemetry samples -> array (readings, anomaly.CHANNELS).

    A sample is (moved, status, route_len, battery, temperature, blocked_ticks, task_elapsed,
    zone_congestion, fault_truth, load); `previous` is the reading before the window (for the
    first step, as in the training data), or None at the start of a run."""
    rows = []
    prev = previous
    for s in samples:
        moved, status, route, batt, temp, blocked, elapsed, congestion, _truth, load = s
        rows.append(
            [
                moved,
                float(status in BUSY_STATUSES and route > 0),
                batt,
                batt - prev[3] if prev else 0.0,
                temp,
                temp - prev[4] if prev else 0.0,
                route,
                route - prev[2] if prev else 0.0,
                blocked,
                elapsed,
                congestion,
                load,
            ]
        )
        prev = s
    return np.asarray(rows, dtype=np.float32)


class LiveFaultLSTM:
    algorithm = "LSTM (PyTorch)"

    def __init__(self, path: Path, report: Path) -> None:
        from ai.deep_learning.anomaly import load_bundle

        self.model, self.scale, bundle = load_bundle(path)
        self.threshold = bundle["threshold"]
        data = json.loads(report.read_text()) if report.exists() else {}
        self.test = {k: data.get("test", {}).get("LSTM (raw sequence)", {}).get(k)
                     for k in ("precision", "recall", "F1")}  # fmt: skip

    def scores(self, windows: np.ndarray) -> np.ndarray:
        from ai.deep_learning.anomaly import predict_proba

        return predict_proba(self.model, windows, self.scale)


class LiveDemandNet:
    def __init__(self, path: Path, report: Path) -> None:
        import torch

        from ai.deep_learning import demand

        self.torch = torch
        bundle = torch.load(path, map_location="cpu", weights_only=False)
        self.arch = bundle["arch"]
        self.history = bundle["history"]
        n_step, n_target = len(bundle["step_features"]), len(bundle["target_features"])
        self.model = {
            "MLP": lambda: demand.DemandMLP(len(bundle["features"])),
            "LSTM": lambda: demand.DemandLSTM(n_step, n_target, hidden=32),
            "Transformer": lambda: demand.DemandTransformer(n_step, n_target),
        }[self.arch]()
        self.model.load_state_dict(bundle["state_dict"])
        self.model.eval()
        self.y_mean, self.y_std = bundle["y_scale"]
        self.features = bundle["features"]
        self.f_mean = np.asarray(bundle["feature_mean"], dtype=np.float32)
        self.f_std = np.asarray(bundle["feature_std"], dtype=np.float32)
        data = json.loads(report.read_text()) if report.exists() else {}
        saved = [
            r
            for r in data.get("runs", [])
            if r["model"] == self.arch and r["seed"] == data.get("saved_seed")
        ]
        self.test_mae = saved[0]["test_MAE"] if saved else None
        self.algorithm = {
            "MLP": "MLP",
            "LSTM": "LSTM",
            "Transformer": "Transformer (PatchTST-style)",
        }[self.arch]
        self.algorithm += " (PyTorch)"

    def forecast(
        self, orders: list[float], calendars: list[dict], target: dict, features: dict
    ) -> float:
        """orders / calendars: the `history` hours before the forecast hour, oldest first; target:
        calendar of the forecast hour; features: the 11 Phase 3 features (used by the MLP)."""
        with self.torch.no_grad():
            if self.arch == "MLP":
                x = (
                    np.array([[features[f] for f in self.features]], dtype=np.float32) - self.f_mean
                ) / self.f_std
                out = self.model(self.torch.from_numpy(x))
            else:
                steps = np.array(
                    [
                        [(o - self.y_mean) / self.y_std, *_hour(c["hour"]),
                         c["is_weekend"], c["is_promo_day"]]
                        for o, c in zip(orders, calendars, strict=True)
                    ],
                    dtype=np.float32,
                )  # fmt: skip
                t = target
                cal = [*_hour(t["hour"]), *_dow(t["day_of_week"]), t["is_weekend"]]
                cal.append(t["is_promo_day"])
                tgt = np.array([cal], dtype=np.float32)
                out = self.model(self.torch.from_numpy(steps[None]), self.torch.from_numpy(tgt))
        return float(out.item() * self.y_std + self.y_mean)


def _hour(h: int) -> tuple[float, float]:
    return math.sin(2 * math.pi * (h % 24) / 24), math.cos(2 * math.pi * (h % 24) / 24)


def _dow(d: int) -> tuple[float, float]:
    return math.sin(2 * math.pi * d / 7), math.cos(2 * math.pi * d / 7)

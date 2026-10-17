"""Deep-learning fault detection on robot telemetry (Phase 5).

Phase 3 detected faults from 13 hand-made summary features per 20-tick window (XGBoost, F1 0.81).
Here neural networks get the same windows:

* MLP   reads the same 13 summary features (neural network vs trees, identical input);
* LSTM  reads the window as a sequence of 10 raw telemetry readings (one every 2 ticks), so it can
        learn the pattern over time itself instead of relying on hand-made summaries.

`build_sequences` cuts the raw telemetry (data/processed/deep_learning/robot_status.parquet) into
exactly the windows of data/processed/classical_ml/anomaly_windows.parquet: one window = one robot,
ticks tick_start..tick_end (20 ticks, 10 readings). Train, validation and test therefore use the
same days and the same windows as Phase 3, and the scores are directly comparable.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch import nn

STEPS = 10  # readings per window (20 ticks, telemetry every 2 ticks)
STATUS_EVERY = 2
# Per-reading channels. Robot status is not a channel (a FAULT status would give the label away);
# like Phase 3, it only marks whether the robot has somewhere to go ("busy").
CHANNELS = [
    "moved",  # share of the possible distance driven since the last reading (0, 0.5, 1)
    "busy",  # has a route and is moving, delivering or stopped by a fault
    "battery",  # %
    "battery_step",  # change since the last reading
    "temperature",  # motor, deg C
    "temperature_step",
    "route_len",  # cells left on the current route
    "route_step",  # change since the last reading (a detour makes it jump up)
    "blocked_ticks",
    "task_elapsed",
    "zone_congestion",
    "load",
]


DERIVED = ("busy", "battery_step", "temperature_step", "route_step")
RAW_COLUMNS = ["robot_id", "tick", "status", *[c for c in CHANNELS if c not in DERIVED]]


# ----- data ---------------------------------------------------------------------------------------
def _channels(run: pd.DataFrame) -> tuple[np.ndarray, dict[str, int]]:
    """One run's telemetry as an array (robots, readings, channels)."""
    run = run.sort_values(["robot_id", "tick"])
    robots = sorted(run["robot_id"].unique())
    n_read = run.groupby("robot_id").size().iloc[0]
    busy = run["status"].isin(["MOVING", "DELIVERING", "FAULT"]) & (run["route_len"] > 0)
    first = run["robot_id"].ne(run["robot_id"].shift())  # first reading of each robot: no step

    def step(col: str) -> np.ndarray:
        return run[col].diff().mask(first, 0.0).to_numpy()

    cols = {
        "moved": run["moved"].to_numpy(),
        "busy": busy.to_numpy(float),
        "battery": run["battery"].to_numpy(),
        "battery_step": step("battery"),
        "temperature": run["temperature"].to_numpy(),
        "temperature_step": step("temperature"),
        "route_len": run["route_len"].to_numpy(),
        "route_step": step("route_len"),
        "blocked_ticks": run["blocked_ticks"].to_numpy(),
        "task_elapsed": run["task_elapsed"].to_numpy(),
        "zone_congestion": run["zone_congestion"].to_numpy(),
        "load": run["load"].to_numpy(),
    }
    arr = np.stack([cols[c] for c in CHANNELS], axis=1).astype(np.float32)
    return arr.reshape(len(robots), n_read, len(CHANNELS)), {r: i for i, r in enumerate(robots)}


def build_sequences(status_path: Path, keys: pd.DataFrame, out_path: Path) -> np.ndarray:
    """Raw telemetry sequences for the windows in `keys` (run_id, robot_id, tick_end), in order.

    Saved as a .npy file (N, STEPS, channels) and returned memory-mapped, so large splits do not
    have to fit in RAM. Rebuilt only if the file is missing or has a different number of rows.
    """
    if out_path.exists():
        cached = np.load(out_path, mmap_mode="r")
        if cached.shape == (len(keys), STEPS, len(CHANNELS)):
            return cached
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out = np.lib.format.open_memmap(out_path, mode="w+", dtype=np.float32,
                                    shape=(len(keys), STEPS, len(CHANNELS)))  # fmt: skip
    keys = keys.reset_index(drop=True)
    offsets = np.arange(-(STEPS - 1), 1)
    for run_id, idx in keys.groupby("run_id").groups.items():
        run = pd.read_parquet(status_path, filters=[("run_id", "==", run_id)], columns=RAW_COLUMNS)
        arr, robot_index = _channels(run)
        k = keys.loc[idx]
        r = k["robot_id"].map(robot_index).to_numpy()
        end = (k["tick_end"].to_numpy() // STATUS_EVERY)[:, None] + offsets
        out[np.asarray(idx)] = arr[r[:, None], end]
    out.flush()
    return np.load(out_path, mmap_mode="r")


class Standardizer:
    """Per-channel (or per-feature) mean and standard deviation, fitted on training data."""

    def __init__(self, mean: np.ndarray, std: np.ndarray) -> None:
        self.mean = np.asarray(mean, dtype=np.float32)
        self.std = np.where(np.asarray(std) > 1e-6, std, 1.0).astype(np.float32)

    @classmethod
    def fit(cls, x: np.ndarray, chunk: int = 200_000) -> Standardizer:
        flat = lambda a: a.reshape(-1, a.shape[-1]).astype(np.float64)  # noqa: E731
        n, s, ss = 0, 0.0, 0.0
        for i in range(0, len(x), chunk):
            part = flat(np.asarray(x[i : i + chunk]))
            n, s, ss = n + len(part), s + part.sum(0), ss + (part**2).sum(0)
        mean = s / n
        return cls(mean, np.sqrt(np.maximum(ss / n - mean**2, 0)))

    def __call__(self, x: np.ndarray) -> np.ndarray:
        return (np.asarray(x, dtype=np.float32) - self.mean) / self.std

    def to_dict(self) -> dict:
        return {"mean": self.mean.tolist(), "std": self.std.tolist()}


# ----- networks -----------------------------------------------------------------------------------
class MLP(nn.Module):
    """Feed-forward network on the 13 window features."""

    def __init__(self, n_in: int, hidden: int = 128, dropout: float = 0.1) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(n_in, hidden), nn.ReLU(), nn.Dropout(dropout),
            nn.Linear(hidden, hidden // 2), nn.ReLU(), nn.Dropout(dropout),
            nn.Linear(hidden // 2, 1),
        )  # fmt: skip

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x).squeeze(-1)


class LSTMClassifier(nn.Module):
    """LSTM over the 10 readings; the last hidden state (plus its mean over time) -> fault logit."""

    def __init__(
        self, n_channels: int, hidden: int = 64, layers: int = 1, dropout: float = 0.1
    ) -> None:
        super().__init__()
        self.lstm = nn.LSTM(n_channels, hidden, num_layers=layers, batch_first=True,
                            dropout=dropout if layers > 1 else 0.0)  # fmt: skip
        self.head = nn.Sequential(nn.Linear(2 * hidden, hidden), nn.ReLU(), nn.Dropout(dropout),
                                  nn.Linear(hidden, 1))  # fmt: skip

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.lstm(x)
        return self.head(torch.cat([out[:, -1], out.mean(dim=1)], dim=1)).squeeze(-1)


ARCHITECTURES = {"MLP": MLP, "LSTM": LSTMClassifier}


def n_parameters(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())


# ----- training -----------------------------------------------------------------------------------
@torch.no_grad()
def predict_proba(
    model: nn.Module, x: np.ndarray, scale: Standardizer, batch: int = 8192
) -> np.ndarray:
    """Fault probability for every row of `x` (array or memory map), in chunks."""
    model.eval()
    out = np.empty(len(x), dtype=np.float32)
    for i in range(0, len(x), batch):
        xb = torch.from_numpy(scale(x[i : i + batch]))
        out[i : i + batch] = torch.sigmoid(model(xb)).numpy()
    return out


def train_classifier(
    model: nn.Module,
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_val: np.ndarray,
    y_val: np.ndarray,
    scale: Standardizer,
    epochs: int = 15,
    batch: int = 1024,
    lr: float = 2e-3,
    patience: int = 3,
    seed: int = 42,
) -> pd.DataFrame:
    """Adam + binary cross-entropy (faults up-weighted by their rarity), early stopping on the
    validation average precision; the best epoch's weights are restored. Returns the history."""
    from sklearn.metrics import average_precision_score

    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    x_train = scale(x_train)  # standardised copy in RAM (float32)
    y = torch.from_numpy(np.asarray(y_train, dtype=np.float32))
    pos_weight = torch.tensor((y == 0).sum().item() / max((y == 1).sum().item(), 1))
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    optim = torch.optim.Adam(model.parameters(), lr=lr)
    sched = torch.optim.lr_scheduler.ReduceLROnPlateau(optim, mode="max", factor=0.5, patience=1)
    history, best, best_state, wait = [], -1.0, None, 0
    for epoch in range(1, epochs + 1):
        start = time.time()
        model.train()
        order = rng.permutation(len(x_train))
        total = 0.0
        for i in range(0, len(order), batch):
            b = order[i : i + batch]
            optim.zero_grad()
            loss = loss_fn(model(torch.from_numpy(x_train[b])), y[b])
            loss.backward()
            optim.step()
            total += loss.item() * len(b)
        val_ap = average_precision_score(y_val, predict_proba(model, x_val, scale))
        sched.step(val_ap)
        history.append(
            {
                "epoch": epoch,
                "train_loss": total / len(order),
                "val_avg_precision": val_ap,
                "lr": optim.param_groups[0]["lr"],
                "seconds": time.time() - start,
            }
        )
        print(f"epoch {epoch:2d}  train loss {history[-1]['train_loss']:.4f}  "
              f"val avg precision {val_ap:.4f}  ({history[-1]['seconds']:.0f} s)")  # fmt: skip
        if val_ap > best:
            best, best_state, wait = (
                val_ap,
                {k: v.clone() for k, v in model.state_dict().items()},
                0,
            )
        else:
            wait += 1
            if wait >= patience:
                print(f"early stop: no improvement for {patience} epochs")
                break
    model.load_state_dict(best_state)
    return pd.DataFrame(history)


# ----- saving -------------------------------------------------------------------------------------
def save_bundle(path: Path, model: nn.Module, arch: str, config: dict, scale: Standardizer,
                threshold: float, inputs: list[str]) -> None:  # fmt: skip
    bundle = {
        "arch": arch,
        "config": config,
        "state_dict": model.state_dict(),
        "scale": scale.to_dict(),
        "threshold": float(threshold),
        "inputs": inputs,
    }
    torch.save(bundle, path)


def load_bundle(path: Path) -> tuple[nn.Module, Standardizer, dict]:
    bundle = torch.load(path, map_location="cpu", weights_only=True)
    model = ARCHITECTURES[bundle["arch"]](**bundle["config"])
    model.load_state_dict(bundle["state_dict"])
    model.eval()
    return model, Standardizer(**bundle["scale"]), bundle

"""Deep-learning demand forecast: orders in the next hour (Phase 5).

Phase 3 forecast the next hour from 11 hand-made features (calendar + lags 1 h, 2 h, 24 h, 168 h and
a 24-hour mean) with Gradient Boosting: test MAE 8.51 orders/hour. Here the networks read history
directly:

* MLP          the same 11 features (neural network vs trees, identical input);
* LSTM         the last HISTORY hours one by one (orders + calendar of each hour), then the calendar
               of the hour to forecast;
* Transformer  the same history with self-attention, read in 12-hour patches (PatchTST style):
               every part of the week can look directly at every other part (for example the same
               half-day one week earlier) instead of reading the hours in order.

The 91 days form one continuous hourly timeline, so a forecast for any hour may use all hours before
it (also those of the previous split), exactly like the lag features of Phase 3.
"""

from __future__ import annotations

import math
import time

import numpy as np
import pandas as pd
import torch
from torch import nn

HISTORY = 168  # hours of history the sequence models read (one week)
STEP_FEATURES = ["orders", "hour_sin", "hour_cos", "is_weekend", "is_promo_day"]
TARGET_FEATURES = ["hour_sin", "hour_cos", "dow_sin", "dow_cos", "is_weekend", "is_promo_day"]


def calendar(df: pd.DataFrame) -> pd.DataFrame:
    """Cyclical hour / weekday encodings (23:00 is next to 00:00, Sunday next to Monday)."""
    out = df.copy()
    out["hour_sin"] = np.sin(2 * np.pi * out["hour_of_day"] / 24)
    out["hour_cos"] = np.cos(2 * np.pi * out["hour_of_day"] / 24)
    out["dow_sin"] = np.sin(2 * np.pi * out["day_of_week"] / 7)
    out["dow_cos"] = np.cos(2 * np.pi * out["day_of_week"] / 7)
    for col in ("is_weekend", "is_promo_day"):
        out[col] = out[col].astype(float)
    return out


def history_windows(df: pd.DataFrame, rows: np.ndarray, orders_scale: tuple[float, float]):
    """For each target row index: the HISTORY hours before it (STEP_FEATURES, orders standardised)
    and the calendar of the target hour. `df` must be the full hourly timeline sorted by time."""
    mean, std = orders_scale
    steps = df[STEP_FEATURES].to_numpy(np.float32).copy()
    steps[:, 0] = (steps[:, 0] - mean) / std
    idx = np.asarray(rows)[:, None] + np.arange(-HISTORY, 0)
    assert idx.min() >= 0, "a target hour has less than HISTORY hours before it"
    return steps[idx], df[TARGET_FEATURES].to_numpy(np.float32)[rows]


# ----- networks -----------------------------------------------------------------------------------
class DemandMLP(nn.Module):
    def __init__(self, n_in: int, hidden: int = 64, dropout: float = 0.1) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(n_in, hidden), nn.ReLU(), nn.Dropout(dropout),
            nn.Linear(hidden, hidden), nn.ReLU(), nn.Linear(hidden, 1),
        )  # fmt: skip

    def forward(self, x: torch.Tensor, _target: torch.Tensor | None = None) -> torch.Tensor:
        return self.net(x).squeeze(-1)


class DemandLSTM(nn.Module):
    def __init__(self, n_step: int, n_target: int, hidden: int = 32, dropout: float = 0.1) -> None:
        super().__init__()
        self.lstm = nn.LSTM(n_step, hidden, batch_first=True)
        self.head = nn.Sequential(
            nn.Linear(hidden + n_target, hidden), nn.ReLU(), nn.Dropout(dropout),
            nn.Linear(hidden, 1),
        )  # fmt: skip

    def forward(self, history: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        out, _ = self.lstm(history)
        return self.head(torch.cat([out[:, -1], target], dim=1)).squeeze(-1)


class DemandTransformer(nn.Module):
    """Transformer encoder over the history, read in patches (as in PatchTST, Nie et al. 2023).

    The 168 hours are cut into 14 patches of 12 consecutive hours; each patch becomes one token, so
    attention compares 14 half-days instead of 168 single hours (about 100x less work), and each
    token already carries the shape of its 12 hours. A learned position embedding marks where in
    the week each patch lies."""

    def __init__(self, n_step: int, n_target: int, patch: int = 12, d_model: int = 32,
                 heads: int = 4, layers: int = 2, dropout: float = 0.1) -> None:  # fmt: skip
        super().__init__()
        assert HISTORY % patch == 0, "HISTORY must be a multiple of the patch length"
        self.patch = patch
        tokens = HISTORY // patch
        self.embed = nn.Linear(patch * n_step, d_model)
        self.position = nn.Parameter(torch.randn(tokens, d_model) / math.sqrt(d_model))
        layer = nn.TransformerEncoderLayer(d_model, heads, dim_feedforward=2 * d_model,
                                           dropout=dropout, batch_first=True)  # fmt: skip
        self.encoder = nn.TransformerEncoder(layer, layers)
        self.head = nn.Sequential(
            nn.Linear(2 * d_model + n_target, d_model), nn.ReLU(), nn.Linear(d_model, 1)
        )  # fmt: skip

    def forward(self, history: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        b, t, f = history.shape
        tokens = history.reshape(b, t // self.patch, self.patch * f)
        h = self.encoder(self.embed(tokens) + self.position)
        return self.head(torch.cat([h[:, -1], h.mean(dim=1), target], dim=1)).squeeze(-1)


def n_parameters(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())


# ----- training -----------------------------------------------------------------------------------
@torch.no_grad()
def predict(
    model: nn.Module, inputs: tuple[np.ndarray, ...], y_scale: tuple[float, float]
) -> np.ndarray:
    model.eval()
    out = model(*(torch.from_numpy(a) for a in inputs)).numpy()
    return out * y_scale[1] + y_scale[0]


def train_regressor(
    model: nn.Module,
    train_inputs: tuple[np.ndarray, ...],
    y_train: np.ndarray,
    val_inputs: tuple[np.ndarray, ...],
    y_val: np.ndarray,
    y_scale: tuple[float, float],
    epochs: int = 300,
    batch: int = 64,
    lr: float = 1e-3,
    patience: int = 30,
    seed: int = 42,
) -> pd.DataFrame:
    """Adam on mean absolute error (the metric we report), early stopping on validation MAE;
    the best epoch's weights are restored. Returns the history."""
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    x = [torch.from_numpy(a) for a in train_inputs]
    y = torch.from_numpy(((np.asarray(y_train) - y_scale[0]) / y_scale[1]).astype(np.float32))
    optim = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    loss_fn = nn.L1Loss()
    history, best, best_state, wait = [], math.inf, None, 0
    for epoch in range(1, epochs + 1):
        start = time.time()
        model.train()
        order = rng.permutation(len(y))
        total = 0.0
        for i in range(0, len(order), batch):
            b = torch.from_numpy(order[i : i + batch])
            optim.zero_grad()
            loss = loss_fn(model(*(a[b] for a in x)), y[b])
            loss.backward()
            optim.step()
            total += loss.item() * len(b)
        val_mae = float(np.mean(np.abs(predict(model, val_inputs, y_scale) - y_val)))
        history.append({"epoch": epoch, "train_mae_scaled": total / len(order), "val_mae": val_mae,
                        "seconds": time.time() - start})  # fmt: skip
        if val_mae < best - 1e-4:
            best, best_state, wait = (
                val_mae,
                {k: v.clone() for k, v in model.state_dict().items()},
                0,
            )
        else:
            wait += 1
            if wait >= patience:
                break
    model.load_state_dict(best_state)
    return pd.DataFrame(history)

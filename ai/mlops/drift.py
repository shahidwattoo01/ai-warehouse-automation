"""Drift of the live order models (backlog PR-19).

Two kinds of drift are watched, because either can make a model wrong:

* Data drift: the inputs no longer look like the training data. Each feature's live distribution
  is compared with the training distribution by the Population Stability Index (PSI), over the
  same bins (deciles of the training values; categories for text features). On its own this is
  a warning (WARN): a model can stay accurate on shifted inputs.
* Performance drift: the predictions no longer match what happened. The simulator reports every
  order's real delivery time, so the live error is known within minutes: ETA mean absolute error
  against the error on the test set; late-risk recall against its test recall. This is DRIFT,
  and confirmed DRIFT starts retraining.

`reference_profile` builds the training side once per model version (saved next to the model);
`DriftMonitor` keeps a window of finished live predictions and judges them.
"""

from __future__ import annotations

import math
from collections import deque

import numpy as np
import pandas as pd

EPS = 1e-4  # empty bins: PSI would divide by zero
STATUS_ORDER = ["NOT_ENOUGH_DATA", "OK", "WARN", "DRIFT"]


def reference_profile(frame: pd.DataFrame, features: list[str]) -> dict:
    """Bins and shares of every feature in the training data."""
    profile = {}
    for f in features:
        col = frame[f]
        if pd.api.types.is_numeric_dtype(col) and col.nunique() > 10:
            edges = np.unique(np.quantile(col.dropna(), np.linspace(0, 1, 11))[1:-1])
            shares = _numeric_shares(col.to_numpy(dtype=float), edges)
            profile[f] = {"kind": "numeric", "edges": edges.tolist(), "shares": shares}
        else:
            counts = col.astype(str).value_counts(normalize=True)
            profile[f] = {"kind": "category", "shares": counts.round(6).to_dict()}
    return profile


def _numeric_shares(values: np.ndarray, edges: np.ndarray) -> list[float]:
    idx = np.searchsorted(edges, values, side="right")
    counts = np.bincount(idx, minlength=len(edges) + 1)
    return (counts / max(1, len(values))).round(6).tolist()


def psi(expected: list[float], actual: list[float]) -> float:
    return float(
        sum(
            (a - e) * math.log(max(a, EPS) / max(e, EPS))
            for e, a in zip(expected, actual, strict=True)
        )
    )


def feature_psi(profile: dict, rows: list[dict]) -> dict[str, float]:
    """PSI per feature of the live rows against the reference profile."""
    out = {}
    for f, ref in profile.items():
        values = [r.get(f) for r in rows if r.get(f) is not None]
        if not values:
            continue
        if ref["kind"] == "numeric":
            live = _numeric_shares(np.asarray(values, dtype=float), np.asarray(ref["edges"]))
            out[f] = round(psi(ref["shares"], live), 4)
        else:
            cats = list(ref["shares"])
            n = len(values)
            live_counts = pd.Series([str(v) for v in values]).value_counts()
            unseen = n - sum(int(live_counts.get(c, 0)) for c in cats)
            expected = [ref["shares"][c] for c in cats] + [0.0]
            actual = [live_counts.get(c, 0) / n for c in cats] + [unseen / n]
            out[f] = round(psi(expected, actual), 4)
    return out


def _worse(a: str, b: str) -> str:
    return a if STATUS_ORDER.index(a) >= STATUS_ORDER.index(b) else b


class DriftMonitor:
    """Recent finished predictions of one model, and the checks on them."""

    def __init__(self, model: str, profile: dict, baseline: dict, cfg: dict) -> None:
        self.model = model
        self.profile = profile
        self.baseline = baseline  # the production version's test metrics
        self.cfg = cfg
        self.window: deque[dict] = deque(maxlen=cfg["monitor"]["window"])
        self.history: deque[dict] = deque(maxlen=200)  # one row per check, for the chart
        self.confirmed = 0  # checks in a row with DRIFT
        self.last: dict | None = None
        # The version's own live error in its first hours in production. Live conditions differ
        # from the test set (here: easier), so a model can get much worse and still beat its
        # test error; comparing with its own start catches that.
        self.live_baseline: dict | None = None

    def observe(self, record: dict) -> None:
        if record.get("actual") is not None:
            self.window.append(record)

    def reset(self, profile: dict, baseline: dict) -> None:
        """A new production version: judge it from scratch against its own training data."""
        self.profile, self.baseline = profile, baseline
        self.window.clear()
        self.confirmed = 0
        self.live_baseline = None

    # ----- the checks ------------------------------------------------------------------------
    def performance(self) -> dict:
        rows = list(self.window)
        if self.model == "eta":
            errors = [abs(r["actual"]["duration_ticks"] - r["output"]["eta_ticks"]) for r in rows]
            mae = sum(errors) / len(errors) if errors else None
            base = self.baseline.get("MAE")
            ratio = mae / base if mae is not None and base else None
            return {"live_mae": _r(mae), "test_mae": base, "mae_ratio": _r(ratio, 3)}
        flags = [(bool(r["output"]["flag"]), bool(r["actual"]["late"])) for r in rows]
        tp = sum(f and a for f, a in flags)
        fp = sum(f and not a for f, a in flags)
        fn = sum(a and not f for f, a in flags)
        recall = tp / (tp + fn) if tp + fn else None
        precision = tp / (tp + fp) if tp + fp else None
        base = self.baseline.get("recall")
        drop = base - recall if recall is not None and base is not None else None
        return {"live_recall": _r(recall, 3), "live_precision": _r(precision, 3),
                "test_recall": base, "recall_drop": _r(drop, 3),
                "late_orders": tp + fn}  # fmt: skip

    def check(self, tick: int) -> dict:
        d = self.cfg["drift"]
        n = len(self.window)
        result = {"model": self.model, "tick": tick, "samples": n, "reasons": []}
        if n < self.cfg["monitor"]["min_samples"]:
            result.update(status="NOT_ENOUGH_DATA", psi={}, performance={})
            self.last = result
            return result
        status = "OK"
        ignore = set(d.get("psi_ignore", []))
        profile = {f: p for f, p in self.profile.items() if f not in ignore}
        scores = feature_psi(profile, [r["input"] for r in self.window])
        top = dict(sorted(scores.items(), key=lambda kv: -kv[1])[:5])
        worst = max(scores.values(), default=0.0)
        if worst >= d["psi_warn"]:
            # An input shift alone is a warning: the model may still be right (it is judged by
            # its live error below). Retraining needs the error to grow as well.
            status = _worse(status, "WARN")
            feature = max(scores, key=scores.get)
            size = "major" if worst >= d["psi_drift"] else "moderate"
            result["reasons"].append(f"{size} shift of input {feature} (PSI {worst:.2f})")
        perf = self.performance()
        if self.live_baseline is None and n >= self.cfg["monitor"]["baseline_samples"]:
            self.live_baseline = perf
        if self.model == "eta" and perf["mae_ratio"] is not None:
            start = (self.live_baseline or {}).get("live_mae")
            perf["start_mae"] = start
            perf["start_ratio"] = _r(perf["live_mae"] / start, 3) if start else None
            pairs = [
                (perf["mae_ratio"], "the test error"),
                (perf["start_ratio"], "its error when it went live"),
            ]
            for ratio, against in pairs:
                if ratio is not None and ratio >= d["eta_mae_ratio_warn"]:
                    level = "DRIFT" if ratio >= d["eta_mae_ratio_drift"] else "WARN"
                    status = _worse(status, level)
                    result["reasons"].append(
                        f"live error {perf['live_mae']:.0f} ticks is {ratio:.2f}x {against}"
                    )
        enough = perf.get("late_orders", 0) >= d.get("late_min_positives", 30)
        start = (self.live_baseline or {}).get("live_recall")
        if self.model == "late" and start is not None and perf.get("live_recall") is not None:
            perf["start_recall"] = start
            own_drop = round(start - perf["live_recall"], 3)
            perf["recall_drop"] = max(perf.get("recall_drop") or 0, own_drop)
        if self.model == "late" and perf.get("recall_drop") is not None and enough:
            drop = perf["recall_drop"]
            if drop >= d["late_recall_drop_warn"]:
                level = "DRIFT" if drop >= d["late_recall_drop_drift"] else "WARN"
                status = _worse(status, level)
                caught, test = perf["live_recall"], perf["test_recall"]
                result["reasons"].append(f"catches {caught:.0%} of late orders (test {test:.0%})")
        self.confirmed = self.confirmed + 1 if status == "DRIFT" else 0
        result.update(status=status, psi=top, max_psi=round(worst, 4), performance=perf,
                      confirmed=self.confirmed)  # fmt: skip
        numbers = {k: v for k, v in perf.items() if isinstance(v, float)}
        self.history.append({"tick": tick, "status": status, "max_psi": round(worst, 4), **numbers})
        self.last = result
        return result


def _r(x: float | None, digits: int = 1) -> float | None:
    return None if x is None else round(x, digits)

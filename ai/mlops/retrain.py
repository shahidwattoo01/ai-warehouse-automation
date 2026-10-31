"""Retraining a live order model and the promotion gate (backlog PR-19).

    training data   the original training split (a sample of it) + recent live outcomes,
                    live rows weighted up (they show the warehouse as it is now)
    candidate       a clone of the production pipeline (same preprocessing and algorithm,
                    same settings) fitted on that data
    judged on       the newest live outcomes, kept out of training (how the warehouse is now),
                    and the original test split (how it was: the candidate must not forget it)

The gate's tests, all of which must pass before the candidate may replace production:

    schema        same input features as production
    sane output   finite predictions; ETA > 0, probabilities in [0, 1]
    better now    on the recent holdout: ETA MAE at least `min_improvement` lower, or late-risk
                  F1 at least that much higher
    not worse     on the original test split: at most `max_regression` worse
    fast enough   median time of one prediction below `max_latency_ms`
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.metrics import f1_score, mean_absolute_error, recall_score

from ai.mlops.drift import reference_profile
from ai.mlops.registry import ROOT, Registry

TASKS = ROOT / "data" / "processed" / "classical_ml" / "tasks.parquet"
TARGET = {"eta": "duration_ticks", "late": "late"}
MAX_OLD_ROWS = 40_000  # a sample of the original training split: retraining takes ~a minute


def load_tasks(path: Path = TASKS) -> pd.DataFrame:
    """Dataset v3 with the features derived exactly as notebooks/01 and 02 do."""
    df = pd.read_parquet(path)
    df["hour_sin"] = np.sin(2 * np.pi * df["sim_hour"] / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df["sim_hour"] / 24)
    for col in ["is_weekend", "is_promo_day"]:
        df[col] = df[col].astype(int)
    for col in ["priority", "main_category"]:
        df[col] = df[col].astype(str)
    return df


def load_model(registry: Registry, model: str, version: str | None = None):
    entry = registry.get(model, version) if version else registry.production(model)
    obj = joblib.load(registry.path_of(entry))
    return entry, obj


def pipeline_of(model: str, obj):
    return obj if model == "eta" else obj["pipeline"]


def _live_frame(model: str, records: list[dict]) -> tuple[pd.DataFrame, np.ndarray]:
    rows = sorted(records, key=lambda r: r["tick"])
    X = pd.DataFrame([r["input"] for r in rows])
    if model == "eta":
        y = np.array([r["actual"]["duration_ticks"] for r in rows], dtype=float)
    else:
        y = np.array([bool(r["actual"]["late"]) for r in rows])
    return X, y


def _score(model: str, obj, X: pd.DataFrame, y: np.ndarray) -> dict:
    pipe = pipeline_of(model, obj)
    X = X[list(pipe.feature_names_in_)]
    if model == "eta":
        pred = pipe.predict(X)
        return {"MAE": round(float(mean_absolute_error(y, pred)), 3), "n": len(y)}
    flags = pipe.predict_proba(X)[:, 1] >= obj["threshold"]
    return {
        "F1": round(float(f1_score(y, flags, zero_division=0)), 4),
        "recall": round(float(recall_score(y, flags, zero_division=0)), 4),
        "n": len(y),
    }


def _latency_ms(model: str, obj, row: pd.DataFrame) -> float:
    pipe = pipeline_of(model, obj)
    row = row[list(pipe.feature_names_in_)]
    times = []
    for _ in range(200):
        t = time.perf_counter()
        pipe.predict(row) if model == "eta" else pipe.predict_proba(row)
        times.append((time.perf_counter() - t) * 1000)
    return round(float(np.median(times)), 3)


def retrain(
    model: str, records: list[dict], registry: Registry, cfg: dict, reason: str,
    tasks_path: Path = TASKS, seed: int = 0,
) -> dict:  # fmt: skip
    """Train a candidate, run the gate, register it. Returns the candidate's registry entry."""
    r, g = cfg["retrain"], cfg["gate"]
    began = time.perf_counter()
    prod_entry, prod = load_model(registry, model)
    pipe = pipeline_of(model, prod)
    features = list(pipe.feature_names_in_)
    target = TARGET[model]

    tasks = load_tasks(tasks_path)
    old_train = tasks[tasks["split"] == "train"]
    old_train = old_train.sample(min(MAX_OLD_ROWS, len(old_train)), random_state=seed)
    old_test = tasks[tasks["split"] == "test"]

    X_live, y_live = _live_frame(model, records)
    cut = int(len(X_live) * (1 - r["holdout_share"]))
    X_fit = pd.concat([old_train[features], X_live.iloc[:cut][features]], ignore_index=True)
    y_fit = np.concatenate([old_train[target].to_numpy(), y_live[:cut]])
    w = np.concatenate([np.ones(len(old_train)), np.full(cut, r["live_weight"])])
    X_hold, y_hold = X_live.iloc[cut:], y_live[cut:]

    cand_pipe = clone(pipe)
    cand_pipe.fit(X_fit, y_fit, model__sample_weight=w)
    cand = cand_pipe if model == "eta" else {**prod, "pipeline": cand_pipe}

    # ----- the gate --------------------------------------------------------------------------
    tests = []
    now_prod, now_cand = _score(model, prod, X_hold, y_hold), _score(model, cand, X_hold, y_hold)
    was_prod = _score(model, prod, old_test, old_test[target].to_numpy())
    was_cand = _score(model, cand, old_test, old_test[target].to_numpy())
    tests.append(("schema", list(cand_pipe.feature_names_in_) == features,
                  f"{len(features)} input features, as production"))  # fmt: skip
    if model == "eta":
        p = cand_pipe.predict(X_hold[features])
        tests.append(("sane output", bool(np.isfinite(p).all() and (p > 0).all()),
                      f"ETA {p.min():.0f}-{p.max():.0f} ticks"))  # fmt: skip
        gain = 1 - now_cand["MAE"] / max(now_prod["MAE"], 1e-9)  # production may be exact
        detail = f"recent MAE {now_cand['MAE']:.1f} vs {now_prod['MAE']:.1f} ({gain:+.1%})"
        tests.append(("better now", gain >= g["min_improvement"], detail))
        loss = was_cand["MAE"] / max(was_prod["MAE"], 1e-9) - 1
        detail = f"test MAE {was_cand['MAE']:.1f} vs {was_prod['MAE']:.1f} ({loss:+.1%})"
        tests.append(("not worse before", loss <= g["max_regression"], detail))
    else:
        p = cand_pipe.predict_proba(X_hold[features])[:, 1]
        tests.append(("sane output", bool(np.isfinite(p).all() and ((p >= 0) & (p <= 1)).all()),
                      "probabilities in [0, 1]"))  # fmt: skip
        gain = now_cand["F1"] - now_prod["F1"]
        detail = f"recent F1 {now_cand['F1']:.3f} vs {now_prod['F1']:.3f} ({gain:+.3f})"
        tests.append(("better now", gain >= g["min_improvement"], detail))
        loss = (was_prod["F1"] - was_cand["F1"]) / max(was_prod["F1"], 1e-9)
        tests.append(("not worse before", loss <= g["max_regression"],
                      f"test F1 {was_cand['F1']:.3f} vs {was_prod['F1']:.3f}"))  # fmt: skip
    latency = _latency_ms(model, cand, X_hold.iloc[:1])
    tests.append(("fast enough", latency <= g["max_latency_ms"], f"{latency} ms per prediction"))
    passed = all(ok for _, ok, _ in tests)

    # ----- store it --------------------------------------------------------------------------
    version = registry.next_version(model)
    out = registry.dir / "models"
    out.mkdir(parents=True, exist_ok=True)
    stem = f"{model}_{version}"
    joblib.dump(cand, out / f"{stem}.joblib")
    profile = reference_profile(pd.concat([old_train[features], X_live.iloc[:cut][features]]),
                                features)  # fmt: skip
    (out / f"{stem}_reference.json").write_text(json.dumps(profile), encoding="utf-8")
    report = {
        "model": stem, "based_on": prod_entry["version"], "reason": reason,
        "algorithm": type(cand_pipe.named_steps["model"]).__name__,
        "rows": {"old": len(old_train), "live": cut, "holdout": len(y_hold)},
        "recent": {"production": now_prod, "candidate": now_cand},
        "original_test": {"production": was_prod, "candidate": was_cand},
        "tests": [{"test": t, "passed": ok, "detail": d} for t, ok, d in tests],
        "passed": passed, "seconds": round(time.perf_counter() - began, 1),
    }  # fmt: skip
    (out / f"{stem}_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    rel = out.relative_to(ROOT).as_posix() if out.is_relative_to(ROOT) else out.as_posix()
    entry = registry.add_candidate(model, {
        "version": version, "file": f"{rel}/{stem}.joblib", "report": f"{rel}/{stem}_report.json",
        "reference": f"{rel}/{stem}_reference.json",
        "trained_on": f"{len(old_train)} old + {cut} live rows",
        "test": was_cand if model == "late" else {"MAE": now_cand["MAE"]},
        "baseline": _baseline(model, now_cand), "gate": report["tests"], "passed": passed,
        "reason": reason,
    })  # fmt: skip
    if not passed:
        failed = ", ".join(t for t, ok, _ in tests if not ok)
        registry.reject(model, version, f"failed {failed}")
    return entry


def _baseline(model: str, recent: dict) -> dict:
    """What drift is judged against once this version is in production: its error on the
    recent holdout (the conditions it was trained for)."""
    if model == "eta":
        return {"MAE": recent["MAE"]}
    return {"recall": recent["recall"]}

"""MLOps building blocks: PSI, the drift monitor's rules, the version registry's lifecycle."""

import random

import pandas as pd
import pytest
import yaml

from ai.mlops.drift import DriftMonitor, feature_psi, psi, reference_profile
from ai.mlops.registry import (
    ROOT,  # noqa: E402
    Registry,
)

CFG = yaml.safe_load((ROOT / "configs" / "mlops.yaml").read_text(encoding="utf-8"))


def frame(n=2000, shift=0.0, seed=0):
    rng = random.Random(seed)
    return pd.DataFrame({
        "path_distance": [rng.gauss(40 + shift, 10) for _ in range(n)],
        "priority": [rng.choice(["HIGH", "MEDIUM", "LOW"]) for _ in range(n)],
        "day_of_week": [rng.randrange(7) for _ in range(n)],
    })  # fmt: skip


def test_psi_is_small_for_the_same_data_and_large_for_a_shift():
    profile = reference_profile(frame(), ["path_distance", "priority"])
    same = feature_psi(profile, frame(seed=1).to_dict("records"))
    moved = feature_psi(profile, frame(shift=25, seed=1).to_dict("records"))
    assert same["path_distance"] < 0.05 and same["priority"] < 0.05
    assert moved["path_distance"] > 0.25
    assert psi([0.5, 0.5], [0.5, 0.5]) == 0


def test_unseen_category_counts_as_shift():
    profile = reference_profile(frame(), ["priority"])
    rows = [{"priority": "URGENT"}] * 200
    assert feature_psi(profile, rows)["priority"] > 1


def eta_records(n, error, tick0=0, shift=0.0, seed=0):
    rng = random.Random(seed)
    rows = frame(n, shift, seed).to_dict("records")
    return [{"model": "eta", "tick": tick0 + i, "input": r, "output": {"eta_ticks": 100},
             "actual": {"duration_ticks": 100 + rng.choice([-1, 1]) * error}}
            for i, r in enumerate(rows)]  # fmt: skip


def monitor(model="eta"):
    profile = reference_profile(frame(), ["path_distance", "priority", "day_of_week"])
    return DriftMonitor(model, profile, {"MAE": 20.0, "recall": 0.9}, CFG)


def test_growing_error_is_drift_and_must_be_confirmed():
    mon = monitor()
    assert mon.check(0)["status"] == "NOT_ENOUGH_DATA"
    for r in eta_records(400, error=18):
        mon.observe(r)
    first = mon.check(1)
    assert first["status"] == "OK" and mon.live_baseline["live_mae"] == 18
    for r in eta_records(400, error=30, tick0=1000):  # 1.67x its own start, 1.5x the test error
        mon.observe(r)
    assert mon.check(2)["status"] == "DRIFT" and mon.confirmed == 1
    assert mon.check(3)["confirmed"] == 2  # confirm_checks: now retraining may start
    assert any("went live" in reason for reason in mon.last["reasons"])


def test_input_shift_alone_is_only_a_warning_and_calendar_is_ignored():
    mon = monitor()
    rows = eta_records(400, error=15, shift=40)
    for r in rows:
        r["input"]["day_of_week"] = 3  # one weekday in a short window: not drift
        mon.observe(r)
    result = mon.check(1)
    assert result["status"] == "WARN"
    assert "path_distance" in result["reasons"][0] and "day_of_week" not in result["psi"]


def test_late_recall_needs_enough_late_orders():
    mon = monitor("late")
    rows = [{"model": "late", "tick": i, "input": {}, "output": {"flag": False},
             "actual": {"late": i < 10}} for i in range(400)]  # fmt: skip
    for r in rows:
        mon.observe(r)
    result = mon.check(1)  # 10 late orders, none caught: too few to judge
    assert result["status"] == "OK" and result["performance"]["late_orders"] == 10


def test_registry_lifecycle(tmp_path):
    reg = Registry(state_dir=tmp_path)
    assert reg.production("eta")["version"] == "v1"
    good = reg.add_candidate("eta", {"version": "v2", "file": "x", "reference": "x", "test": {}})
    assert good["status"] == "candidate" and reg.next_version("eta") == "v3"
    reg.promote("eta", "v2", by="gate")
    assert reg.production("eta")["version"] == "v2" and reg.get("eta", "v1")["status"] == "archived"
    reg.add_candidate("eta", {"version": "v3", "file": "x", "reference": "x", "test": {}})
    reg.reject("eta", "v3", "failed better now")
    with pytest.raises(ValueError):
        reg.promote("eta", "v3")  # a rejected candidate never goes live
    assert reg.rollback("eta", by="sara")["version"] == "v1"
    again = Registry(state_dir=tmp_path)  # survives a restart
    assert again.production("eta")["version"] == "v1"
    assert [h["event"] for h in again.get("eta", "v2")["history"]][-1] == "replaced by v1"

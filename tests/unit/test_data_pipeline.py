"""Unit tests for fault injection, the recorder and the training-data tables."""

import sys
from pathlib import Path

import pandas as pd

from simulation.environment.engine import SimulationEngine
from simulation.environment.recorder import Recorder
from simulation.warehouse.entities import RobotStatus

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

FAST = {"layout": "default", "ticks_per_hour": 200, "orders": {"arrival_prob_per_tick": 0.2}}


def _run(ticks: int, overrides: dict, seed: int = 3) -> tuple[SimulationEngine, Recorder]:
    engine = SimulationEngine(seed=seed, overrides=overrides)
    recorder = Recorder(engine, "test", status_every=2)
    engine.start()
    for _ in range(ticks):
        engine.tick()
        recorder.after_tick()
    return engine, recorder


def test_fleet_delivers_orders_without_overlap():
    engine, recorder = _run(1500, FAST)
    positions = [r.position for r in engine.robots.values()]
    assert len(positions) == len(set(positions))
    tasks = recorder.tables()["tasks"]
    assert len(tasks) > 50
    assert (tasks["duration_ticks"] > 0).all()
    assert (tasks["est_distance"] > 0).all()


def test_stop_fault_is_labelled_and_clears():
    engine = SimulationEngine(seed=1, overrides=FAST)
    engine.start()
    engine.faults.inject("R1", "stop_event")
    assert engine.robots["R1"].status == RobotStatus.FAULT
    assert engine.faults.label("R1") == "stop_event"
    events = []
    for _ in range(80):
        events += engine.tick()
    assert engine.faults.label("R1") is None
    assert engine.robots["R1"].status != RobotStatus.FAULT
    assert any(e.type.value == "FAULT_CLEARED" and e.is_injected_fault for e in events)


def test_anomaly_windows_carry_fault_labels():
    _, recorder = _run(1200, {**FAST, "faults": {"enabled": True, "probability_per_hour": 6.0}})
    windows = recorder.tables()["anomaly_windows"]
    assert {"move_rate_when_busy", "battery_min_step", "is_anomaly", "fault_type"} <= set(
        windows.columns
    )
    assert windows["is_anomaly"].sum() > 0
    assert set(windows["fault_type"]) - {"none"}
    # Labels and flags agree.
    assert ((windows["fault_type"] != "none") == (windows["is_anomaly"] == 1)).all()


def test_demand_follows_hourly_profile():
    engine, recorder = _run(24 * 200, {**FAST, "orders": {"arrival_prob_per_tick": 0.1}})
    demand = recorder.tables()["demand_hourly"]
    assert len(demand) == 24
    night = demand[demand["hour_of_day"].between(0, 3)]["orders_total"].mean()
    day = demand[demand["hour_of_day"].between(8, 15)]["orders_total"].mean()
    assert day > night * 2


def test_orders_and_tasks_carry_product_details():
    _, recorder = _run(800, FAST)
    tables = recorder.tables()
    for name in ("orders", "tasks"):
        df = tables[name]
        assert {"total_weight_kg", "main_category", "categories"} <= set(df.columns), name
        assert (df["total_weight_kg"] > 0).all(), name
        # The main category is always one of the order's categories.
        assert all(
            m in c.split("|") for m, c in zip(df["main_category"], df["categories"], strict=True)
        )


def test_demand_by_category_adds_up():
    _, recorder = _run(6 * 200, FAST)
    demand = recorder.tables()["demand_hourly"]
    cat_cols = [c for c in demand.columns if c.startswith("lines_cat_")]
    assert len(cat_cols) == 10
    orders = recorder.tables()["orders"]
    # Each order line counts once in its category; totals still count orders.
    complete_hours = orders[orders["order_time"] < 6 * 200]
    assert demand[cat_cols].to_numpy().sum() == complete_hours["n_items"].sum()
    assert demand["orders_total"].sum() == len(complete_hours)


def test_demand_is_not_capped_by_the_waiting_queue():
    """With orders far above capacity, every customer order is still recorded (v1 bug)."""
    overrides = {**FAST, "orders": {"arrival_prob_per_tick": 1.0}}  # an order every tick
    engine, recorder = _run(600, overrides)
    assert engine.generator.max_pending >= 150
    pending = sum(o.status.value == "PENDING" for o in engine.orders.values())
    assert pending > 50  # the old cap (30) would have stopped recording demand long before


def test_generate_data_run_one(tmp_path):
    from generate_data import DATASET_VERSION, combine, run_one

    spec = {
        "run_id": "day_t",
        "seed": 5,
        "day_index": 0,
        "layout": "default",
        "hours": 2,
        "ticks_per_hour": 200,
        "status_every": 2,
        "target_load": 0.6,
        "arrival_prob": 0.15,
        "hourly_profile": [1.0] * 24,
        "fault_rate": 2.0,
        "closure_rate": 0.0,
        "floor_hazard_rate": 2.0,
        "calendar": {"date": "2026-09-07", "day_of_week": 0, "split": "train"},
        "dataset_version": DATASET_VERSION,
        "out_dir": str(tmp_path / "runs"),
    }
    result = run_one(spec)
    assert result["rows"]["tasks"] > 0
    stale = tmp_path / "runs" / "stale_run"  # left over from an older generation
    stale.mkdir()
    pd.DataFrame({"dataset_version": ["v0"], "x": [1]}).to_parquet(stale / "tasks.parquet")
    totals = combine(tmp_path / "runs", tmp_path / "processed", ["day_t"])
    tasks = pd.read_parquet(tmp_path / "processed" / "classical_ml" / "tasks.parquet")
    assert set(tasks["dataset_version"]) == {DATASET_VERSION}  # the stale run was not mixed in
    assert set(tasks["split"]) == {"train"} and set(tasks["date"]) == {"2026-09-07"}
    assert totals["robot_status"] == 2 * 200 // 2 * 12
    demand = pd.read_parquet(tmp_path / "processed" / "classical_ml" / "demand_hourly.parquet")
    assert {"timestamp", "lag_1h_orders", "lag_24h_orders"} <= set(demand.columns)

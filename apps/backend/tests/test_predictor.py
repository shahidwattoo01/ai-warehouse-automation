"""Live Phase 3 predictions on a running simulation (skipped until the models are trained)."""

import pytest

from app.services.predictor import MODELS_DIR, Predictor
from simulation.environment.engine import SimulationEngine

pytestmark = pytest.mark.skipif(
    not (MODELS_DIR / "eta_v1.joblib").exists(), reason="train notebooks/01-04 first"
)


def test_predictor_scores_orders_robots_and_demand():
    engine = SimulationEngine(seed=11, overrides={"layout": "large"})
    predictor = Predictor()
    predictor.attach(engine)
    engine.start()
    for _ in range(1500):
        engine.tick()
        predictor.after_tick()
    snap = predictor.snapshot()
    assert {"eta", "late", "demand", "anomaly"} <= set(snap["models"])
    assert snap["live_accuracy"]["eta_n"] > 20  # deliveries compared with their prediction
    assert all(p["eta_ticks"] > 0 and 0 <= p["late_risk"] <= 1 for p in snap["orders"].values())
    assert len(snap["robots"]) == len(engine.robots)  # every robot has a health score
    assert snap["demand"]["history"] and snap["demand"]["forecast"] is not None
    if "demand_breakdown" in snap["models"]:
        assert set(snap["demand"]["zones"]) == {"ZONE_A", "ZONE_B", "ZONE_C", "ZONE_D"}
        assert set(snap["demand"]["priorities"]) == {"HIGH", "MEDIUM", "LOW"}
    records, _ = predictor.drain()
    assert {"eta", "late", "demand"} <= {r["model"] for r in records}
    assert all(r["actual"] is not None for r in records)  # every record carries its outcome


@pytest.mark.skipif(
    not (MODELS_DIR / "anomaly_lstm_v1.pt").exists(), reason="run notebooks/07 first"
)
def test_phase5_lstm_replaces_xgboost_unless_switched_off(monkeypatch):
    monkeypatch.delenv("WAREHOUSE_ANOMALY_MODEL", raising=False)
    monkeypatch.delenv("WAREHOUSE_DEMAND_MODEL", raising=False)
    deep = Predictor()
    versions = {v["model_name"]: v for v in deep.versions}
    assert versions["anomaly"]["version"] == "v2" and "lstm" in versions["anomaly"]["artifact_path"]
    assert (
        versions["demand"]["version"] == "v1"
    )  # the demand network is opt-in (short live history)

    monkeypatch.setenv("WAREHOUSE_ANOMALY_MODEL", "xgboost")
    classic = Predictor()
    assert {v["model_name"]: v["version"] for v in classic.versions}["anomaly"] == "v1"

    engine = SimulationEngine(seed=11, overrides={"layout": "large"})
    deep.attach(engine)
    engine.start()
    for _ in range(60):  # enough readings for a few LSTM scores
        engine.tick()
        deep.after_tick()
    assert deep.snapshot()["algorithms"]["anomaly"].startswith("LSTM")
    assert len(deep.robot_health) == len(engine.robots)

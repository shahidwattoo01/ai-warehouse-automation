"""MLOps with the real ETA model: a slower warehouse is learned by retraining, the gate promotes
the candidate and the live predictor switches to it; a candidate that is not better is rejected;
rollback; the API and its permission. Skipped without the trained models and dataset v3."""

import pytest
from fastapi.testclient import TestClient

from ai.classical_ml.live_predictor import Predictor
from ai.mlops import retrain as retrain_mod
from ai.mlops.registry import MODELS_DIR, Registry
from ai.mlops.retrain import TASKS, load_tasks, pipeline_of
from app.main import app
from app.services.mlops import MlopsService

pytestmark = pytest.mark.skipif(
    not (TASKS.exists() and (MODELS_DIR / "eta_v1.joblib").exists()
         and (MODELS_DIR / "eta_v1_reference.json").exists()),
    reason="needs dataset v3, the trained ETA model and its profile (scripts/mlops.py)",
)  # fmt: skip


@pytest.fixture()
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(retrain_mod, "MAX_OLD_ROWS", 12000)  # a quicker fit than 40,000
    svc = MlopsService(registry=Registry(state_dir=tmp_path))
    svc.attach(Predictor())
    return svc


def live_records(svc, n, slower):
    """Finished ETA predictions of n test orders in a warehouse `slower` times slower."""
    tasks = load_tasks()
    rows = tasks[tasks["split"] == "test"].sample(n, random_state=1)
    pipe = pipeline_of("eta", svc.predictor.models["eta"])
    X = rows[list(pipe.feature_names_in_)]
    pred = pipe.predict(X)
    out = []
    for i, (row, p, real) in enumerate(zip(X.to_dict("records"), pred, rows["duration_ticks"],
                                           strict=True)):  # fmt: skip
        actual = p if slower is None else real * slower
        out.append({"model": "eta", "tick": i, "input": row, "output": {"eta_ticks": round(p)},
                    "actual": {"duration_ticks": float(actual)}})  # fmt: skip
    return out


def test_retrain_promote_swap_and_rollback(service):
    service.observe(live_records(service, 800, slower=1.25))
    service.start_retrain("eta", "test", "pytest")
    service._thread.join(120)
    job = service.job
    assert job["status"] == "DONE" and job["passed"], job.get("gate")
    gate = {t["test"]: t for t in job["gate"]}
    assert set(gate) == {"schema", "sane output", "better now", "not worse before", "fast enough"}
    service.after_tick(1)  # promotions are applied on the loop, between ticks
    assert service.registry.production("eta")["version"] == "v2"
    live = [v for v in service.predictor.versions if v["model_name"] == "eta"][0]
    assert live["version"] == "v2"
    assert service.monitors["eta"].live_baseline is None  # judged afresh
    assert [e["event"] for e in service.events][:2] == ["promoted", "retrain_started"]

    service.rollback("eta", "pytest")
    assert service.registry.production("eta")["version"] == "v1"
    assert [v for v in service.predictor.versions if v["model_name"] == "eta"][0]["version"] == "v1"


def test_candidate_that_is_not_better_is_rejected(service):
    service.observe(live_records(service, 400, slower=None))  # production is exactly right
    service.start_retrain("eta", "test", "pytest")
    service._thread.join(120)
    assert service.job["passed"] is False
    failed = [t["test"] for t in service.job["gate"] if not t["passed"]]
    assert "better now" in failed
    assert service.registry.production("eta")["version"] == "v1"  # nothing changed
    assert service.registry.get("eta", "v2")["status"] == "rejected"
    with pytest.raises(ValueError):
        service.promote("eta", "v2", "pytest")


def test_candidate_that_forgets_the_old_warehouse_is_rejected(service, monkeypatch):
    """Few old rows, a much slower world: the candidate fits the new data and loses the old."""
    monkeypatch.setattr(retrain_mod, "MAX_OLD_ROWS", 3000)
    service.observe(live_records(service, 600, slower=1.6))
    service.start_retrain("eta", "test", "pytest")
    service._thread.join(120)
    gate = {t["test"]: t["passed"] for t in service.job["gate"]}
    assert gate["better now"] and not gate["not worse before"]
    assert service.registry.production("eta")["version"] == "v1"


def test_not_enough_live_data(service):
    service.observe(live_records(service, 20, slower=1.0))
    with pytest.raises(ValueError):
        service.start_retrain("eta", "test", "pytest")


def test_api_status_and_errors():
    client = TestClient(app)
    status = client.get("/api/v1/mlops/status").json()
    assert {"models", "job", "events", "settings"} <= set(status)
    assert "eta" in status["models"] and status["models"]["eta"]["production"]
    r = client.post("/api/v1/mlops/nothing/retrain")
    assert r.status_code == 404
    r = client.post("/api/v1/mlops/eta/promote/v999")
    assert r.status_code == 404
    text = client.get("/metrics").text
    assert 'warehouse_model_status{model="eta",status=' in text


def test_two_models_drifting_at_once_never_stop_the_loop(service, monkeypatch):
    """Live run: ETA was retraining when late risk confirmed drift too; its automatic start
    raised and the exception stopped the simulator loop. Now the second one waits."""
    import threading

    gate = threading.Event()
    monkeypatch.setattr(
        "app.services.mlops.retrain",
        lambda *a, **k: gate.wait(10) and {"version": "v2", "passed": False, "gate": []},
    )
    service.observe(live_records(service, 300, slower=1.0))
    service.start_retrain("eta", "test", "pytest")
    for mon in service.monitors.values():  # both report confirmed drift
        monkeypatch.setattr(mon, "check", lambda tick, m=mon: (
            setattr(m, "confirmed", 5) or {"status": "DRIFT", "reasons": ["test"], "model": m.model}
        ))  # fmt: skip
    service.after_tick(service.cfg["monitor"]["check_every_ticks"] * 100)  # must not raise
    assert service.job["model"] == "eta"  # late risk waits for its next check
    gate.set()
    service._thread.join(10)

    def boom(tick):
        raise RuntimeError("anything")

    monkeypatch.setattr(service, "_after_tick", boom)
    service.after_tick(1)  # logged, never raised into the loop

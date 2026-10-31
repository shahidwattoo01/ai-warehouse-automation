"""Recovery: signed state snapshots restore the whole warehouse (engine, alert incidents, ERP
books, event sequence) paused and identical; tampered files are refused; a standby instance
answers 503; the PostgreSQL leader lock lets exactly one instance be active; the backup
manifest check catches a damaged file."""

import json
import pickle

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.main import app
from app.services.alerts import centre
from app.services.erp import erp
from app.services.events import events_service
from app.services.leader import LeaderLock
from app.services.recovery import MAGIC, Recovery, snapshot_key
from app.services.simulator import simulator
from simulation.environment.engine import SimulationEngine
from simulation.warehouse.entities import RobotStatus

KEY = snapshot_key("tests-only-recovery-secret")


@pytest.fixture()
def world(tmp_path):
    """The live simulator on a small WMS run, saving to a temporary directory."""
    original = (simulator.engine, simulator.recovery, simulator.strategies, simulator.preset)
    simulator.engine = SimulationEngine(
        seed=7, overrides={"layout": "default", "inventory_model": "wms"}
    )
    simulator._attach_services()
    simulator.recovery = Recovery(tmp_path, KEY)
    centre.reset()
    yield simulator
    simulator.engine, simulator.recovery, simulator.strategies, simulator.preset = original
    centre.reset()
    simulator._attach_services()


def run(sim, ticks: int) -> None:
    eng = sim.engine
    eng.start()
    for _ in range(ticks):
        events = eng.tick()
        if eng.time == 150:
            eng.robots["R1"].status = RobotStatus.FAULT
        erp.after_tick()
        if eng.time % 30 == 0:
            centre.evaluate(eng, {})
        events_service.after_tick(events, centre.take_changed())


def test_snapshot_restores_the_whole_warehouse(world):
    sim = world
    run(sim, 400)
    eng = sim.engine
    before = {
        "time": eng.time,
        "kpis": eng.kpis.snapshot(),
        "state": {**eng.state(include_inventory=True), "running": False},
        "incidents": sorted(centre.incidents),
        "seq": events_service.publisher.seq,
        "imported": dict(erp.connector.imported),
    }
    assert before["incidents"], "the fault should have opened an incident"
    twin = pickle.loads(pickle.dumps(eng))  # what the warehouse would have done without a restart
    sim.recovery.write(sim.recovery.capture(sim), eng.time)
    assert sim.recovery.path.exists() and sim.recovery.status()["saved_tick"] == before["time"]

    # "restart": everything in memory is new
    sim.engine = SimulationEngine(seed=1, overrides={"layout": "default", "inventory_model": "wms"})
    centre.reset()
    sim._attach_services()
    data = sim.recovery.load()
    sim.recovery.adopt(sim, data)

    eng = sim.engine
    assert eng.running is False  # restored paused: an operator checks the floor first
    assert eng.time == before["time"] and eng.kpis.snapshot() == before["kpis"]
    assert eng.state(include_inventory=True) == before["state"]
    assert sorted(centre.incidents) == before["incidents"]
    assert events_service.publisher.seq == before["seq"]  # subscribers' `after=` stays valid
    assert dict(erp.connector.imported) == before["imported"]
    assert sim.recovery.status()["restored"]["tick"] == before["time"]
    # services follow the restored engine, and it carries on exactly as it would have
    assert erp.connector.engine is eng and events_service.engine is eng
    eng.start()
    twin.start()
    for _ in range(150):
        eng.tick()
        twin.tick()
    assert eng.kpis.snapshot() == twin.kpis.snapshot()
    nxt = events_service.publisher.publish("robots/paused", "R2", {}, eng.time)
    assert nxt["sequence"] == before["seq"] + 1


def test_tampered_snapshot_is_refused_and_previous_used(world, tmp_path):
    sim = world
    run(sim, 50)
    rec = sim.recovery
    rec.write(rec.capture(sim), 50)  # becomes .prev after the next write
    run(sim, 50)
    rec.write(rec.capture(sim), 100)
    raw = bytearray(rec.path.read_bytes())
    raw[-10] ^= 0xFF  # one changed byte
    rec.path.write_bytes(bytes(raw))
    data = rec.load()
    assert data["tick"] == 50  # the good previous file
    assert (tmp_path / "warehouse_state.rejected").exists()
    assert "signature" in rec.status()["last_error"]


def test_foreign_key_and_no_secret(world, tmp_path):
    sim = world
    run(sim, 20)
    sim.recovery.write(sim.recovery.capture(sim), 20)
    other = Recovery(tmp_path, snapshot_key("another-secret"))
    assert other.load() is None  # never unpickled
    assert not Recovery(tmp_path, snapshot_key("")).enabled
    evil = tmp_path / "x" / "warehouse_state.bin"
    evil.parent.mkdir()
    evil.write_bytes(MAGIC + b"\0" * 32 + b"not zlib")
    assert Recovery(evil.parent, KEY).load() is None


def test_snapshot_api_and_status(world):
    client = TestClient(app)
    run(world, 30)
    r = client.post("/api/v1/simulation/snapshot")
    assert r.status_code == 200 and r.json()["saved_tick"] == 30 and r.json()["size_bytes"] > 0
    st = client.get("/api/v1/simulation/recovery").json()
    assert st["enabled"] and st["role"] == "active" and st["writes"] == 1
    text_ = client.get("/metrics").text
    assert "warehouse_instance_active 1" in text_
    assert "warehouse_state_snapshot_bytes" in text_


def test_standby_answers_503():
    client = TestClient(app)
    simulator.role = "standby"
    try:
        r = client.get("/api/v1/simulation/state")
        assert r.status_code == 503 and r.json()["detail"]["code"] == "standby"
        assert r.headers["retry-after"] == "2"
        assert client.get("/health").status_code == 200  # the process is alive
        ready = client.get("/ready")
        assert ready.status_code == 503 and ready.json()["checks"]["role"]["ok"] is False
    finally:
        simulator.role = "active"


@pytest.fixture()
def db_url() -> str:
    url = get_settings().database_url
    try:
        with create_engine(url).connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"PostgreSQL not available: {str(exc).splitlines()[0]}")
    return url


def test_leader_lock_one_active(db_url):
    key = 0x7E57  # not the platform's key: a running dev backend is not disturbed
    a, b = LeaderLock(db_url, key), LeaderLock(db_url, key)
    try:
        assert a.try_acquire() and a.still_held()
        assert not b.try_acquire()  # one active instance only
        a.conn.invalidate()  # the active instance's database session dies (crash, network)
        assert not a.still_held() and not a.held  # it steps down...
        assert b.try_acquire()  # ...and the standby takes over
    finally:
        a.release()
        b.release()


def test_backup_manifest_detects_damage(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[3] / "scripts" / "backup_db.py"
    spec = importlib.util.spec_from_file_location("backup_db", path)
    backup_db = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(backup_db)
    dump = tmp_path / "warehouse_ai_20260101_000000.dump"
    dump.write_bytes(b"PGDMP fake")
    manifest = {"database": "warehouse_ai", "sha256": "0" * 64, "tables": {}, "total_rows": 0,
                "alembic_version": "007"}  # fmt: skip
    dump.with_suffix(".json").write_text(json.dumps(manifest))
    assert backup_db.verify(dump) is False  # refused before any restore
    for i in range(5):
        (tmp_path / f"warehouse_ai_2026010{i}_000000.dump").write_bytes(b"x")
    backup_db.prune(tmp_path, "warehouse_ai", keep=2)
    assert len(list(tmp_path.glob("*.dump"))) == 2

"""Guards for what the load tests found (tests/load, docs/load_testing.md): one product's stock
must not cost the whole catalogue, the KPI answer is shared per tick, the login check does not
ask the database per request, and the load-test mix only names routes that exist."""

import sys
import time

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import wms as wms_api
from app.core import auth
from app.main import app
from app.services import users
from app.services.simulator import simulator
from simulation.environment.engine import SimulationEngine


def _loadtest():
    """tests/load/loadtest.py at the repository root (not this tests package)."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[3] / "tests" / "load" / "loadtest.py"
    spec = importlib.util.spec_from_file_location("loadtest", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["loadtest"] = module  # its dataclasses look themselves up there
    spec.loader.exec_module(module)
    return module


lt = _loadtest()
MIX, parse_metrics, pct = lt.MIX, lt.parse_metrics, lt.pct


@pytest.fixture()
def wms_engine():
    original = simulator.engine
    e = SimulationEngine(seed=7, overrides={"layout": "default", "inventory_model": "wms"})
    e.start()
    for _ in range(100):
        e.tick()
    simulator.engine = e
    yield e
    simulator.engine = original


@pytest.mark.parametrize("model", ["wms", "simple"])
def test_stock_of_matches_stock(model):
    e = SimulationEngine(seed=7, overrides={"layout": "default", "inventory_model": model})
    e.start()
    for _ in range(50):
        e.tick()
    full = e.inventory.stock
    assert all(e.inventory.stock_of(p) == n for p, n in full.items())


def test_inventory_listing_is_not_quadratic(wms_engine):
    client = TestClient(app)
    began = time.perf_counter()
    rows = client.get("/api/v1/inventory").json()
    assert len(rows) == len(wms_engine.inventory.face)
    assert time.perf_counter() - began < 2.0  # was 13 s on the large layout (stock per row)
    stock = wms_engine.inventory.stock
    assert all(r["stock"] == stock[r["product_id"]] for r in rows)


def test_kpis_shared_within_a_tick(wms_engine, monkeypatch):
    calls = []
    real = wms_engine.inventory.wms.kpis
    monkeypatch.setattr(wms_engine.inventory.wms, "kpis", lambda: calls.append(1) or real())
    wms_api._kpi_cache["key"] = None
    client = TestClient(app)
    first = client.get("/api/v1/wms/kpis").json()
    for _ in range(5):
        assert client.get("/api/v1/wms/kpis").json() == first
    assert len(calls) == 1  # five more screens, no more work
    wms_engine.tick()
    assert client.get("/api/v1/wms/kpis").json()["tick"] == wms_engine.inventory.wms.inv.tick
    assert len(calls) == 2  # a new tick: computed again


def test_user_lookup_is_cached_until_an_account_changes(monkeypatch):
    store = auth.get_store()
    user = store.create("perf-user", "Perf User", "viewer", "x")
    asked = []
    real_get = store.get
    monkeypatch.setattr(store, "get", lambda uid: asked.append(uid) or real_get(uid))
    auth._user_cache.clear()
    for _ in range(20):
        assert auth._cached_user(user.user_id).username == "perf-user"
    assert len(asked) == 1
    store.update(user.user_id, active=False)  # any change: the next check asks again
    assert auth._cached_user(user.user_id).active is False
    assert len(asked) == 2
    assert users.VERSION[0] > 0


def test_load_mix_names_real_routes():
    client = TestClient(app)
    for path, _, _ in MIX:
        assert client.get(path).status_code < 400, path  # the test admin may read everything


def test_report_helpers():
    assert pct([5, 1, 3, 2, 4], 50) == 3 and pct([], 95) is None
    m = parse_metrics('# HELP x\nwarehouse_sim_tick 42\nwarehouse_robots{status="IDLE"} 3\n')
    assert m == {"warehouse_sim_tick": 42.0}


def test_distance_cache_is_bounded_and_keeps_recent_goals(monkeypatch):
    """The soak test saw memory climb as orders reached new racks: one field per goal."""
    import simulation.navigation.distance as d

    monkeypatch.setattr(d, "MAX_CACHED", 3)
    e = SimulationEngine(seed=7, overrides={"layout": "default", "inventory_model": "simple"})
    goals = [tuple(f) for f in list(e.inventory.face.values())[:5]]
    fields = e.distances
    first = fields.field(goals[0])
    for g in goals[1:3]:
        fields.field(g)
    assert fields.field(goals[0]) is first  # recently used: kept
    for g in goals[3:]:
        fields.field(g)
    assert len(fields._fields) == 3
    assert goals[0] in fields._fields and goals[1] not in fields._fields  # oldest went first
    start = next(iter(first))
    assert fields.distance(start, goals[1]) >= 0  # evicted fields are simply recomputed

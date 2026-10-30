"""Safety API: anyone logged in can stop the fleet; only safety:reset can release and restart;
everything is logged under the user."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.simulator import simulator
from simulation.environment.engine import SimulationEngine

API = "/api/v1/safety"


@pytest.fixture()
def client():
    original = simulator.engine
    simulator.engine = SimulationEngine(seed=3, overrides={"layout": "default"})
    simulator.engine.start()
    for _ in range(100):
        simulator.engine.tick()
    yield TestClient(app)
    simulator.engine = original


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_stop_release_reset_and_the_log(client):
    status = client.get(f"{API}/status").json()
    assert status["state"] == "NORMAL" and status["zones"]
    stopped = client.post(f"{API}/estop", json={"reason": "person on the highway"}).json()
    assert stopped["state"] == "ESTOP" and len(stopped["robots_held"]) == len(
        simulator.engine.robots
    )
    assert client.post(f"{API}/reset").status_code == 409  # release first
    assert client.post(f"{API}/release", json={"note": "area checked"}).json()["state"] == (
        "RELEASED"
    )
    for _ in range(300):  # a person may be next to a robot: wait until they walk on
        r = client.post(f"{API}/reset")
        if r.status_code == 200:
            break
        assert "person" in r.json()["detail"]["message"]
        simulator.engine.tick()
    assert r.json()["state"] == "NORMAL"
    log = client.get(f"{API}/events").json()
    stop = next(e for e in log if e["kind"] == "ESTOP")
    assert stop["user"] == "test-admin" and stop["text"].endswith("person on the highway")
    assert client.get(f"{API}/events", params={"kind": "ESTOP_RESET"}).json()


def test_zone_stop_and_slow_zone_settings(client):
    zone = client.get(f"{API}/status").json()["zones"][0]
    z = client.post(f"{API}/estop", json={"reason": "racking repair", "zone": zone}).json()
    assert z["stop"]["scope"] == "zone" and z["stop"]["zone"] == zone
    assert client.post(f"{API}/estop", json={"zone": "ZONE_NOPE"}).status_code == 409
    s = client.put(f"{API}/settings", json={"slow_zones": True, "slow_radius": 2}).json()
    assert s["slow_zones"] and s["slow_radius"] == 2
    assert client.put(f"{API}/settings", json={"slow_radius": 50}).status_code == 422


@pytest.mark.real_auth
def test_a_viewer_can_stop_but_not_restart(client, make_user):
    viewer = make_user("safety-viewer", "viewer")
    assert client.post(f"{API}/estop", headers=bearer(viewer), json={}).status_code == 200
    assert client.post(f"{API}/release", headers=bearer(viewer), json={}).status_code == 403
    operator = make_user("safety-operator", "operator")
    assert client.post(f"{API}/release", headers=bearer(operator), json={}).status_code == 200

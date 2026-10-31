"""VDA 5050 API: status, the message log and instant actions."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.simulator import simulator
from app.services.vda5050 import vda
from simulation.environment.engine import SimulationEngine
from simulation.warehouse.entities import RobotStatus

API = "/api/v1/vda5050"


@pytest.fixture()
def client():
    original = simulator.engine
    simulator.engine = SimulationEngine(seed=3, overrides={"layout": "default"})
    simulator.engine.start()
    vda.attach(simulator.engine)
    for _ in range(120):
        vda.after_tick(simulator.engine.tick())
    yield TestClient(app)
    simulator.engine = original
    vda.attach(original)


def test_status_messages_and_instant_actions(client):
    s = client.get(f"{API}/status").json()
    assert s["transport"] == "memory" and s["counts"]["published"] > 0
    assert len(s["vehicles"]) == len(simulator.engine.robots)
    assert s["topic_example"] == "uagv/v2/WarehouseAI/R1/state"
    log = client.get(
        f"{API}/messages", params={"serial": "R1", "topic": "state", "limit": 5}
    ).json()
    assert log and all(e["topic"] == "uagv/v2/WarehouseAI/R1/state" for e in log)
    r = client.post(f"{API}/instant-actions", json={"serials": ["R2"], "action": "startPause"})
    assert r.status_code == 200 and r.json()["action_ids"]
    vda.after_tick(simulator.engine.tick())
    assert simulator.engine.robots["R2"].status == RobotStatus.PAUSED
    missing = client.post(
        f"{API}/instant-actions", json={"serials": ["R99"], "action": "stopPause"}
    )
    assert missing.status_code == 404
    bad = client.post(f"{API}/instant-actions", json={"serials": ["R1"], "action": "explode"})
    assert bad.status_code == 422

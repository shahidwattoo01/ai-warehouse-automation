"""Agents API: the tool registry, a run on the live warehouse, pending actions approved and
rejected (approval also needs the action's own permission)."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.agents import agents
from app.services.simulator import simulator
from simulation.environment.engine import SimulationEngine


@pytest.fixture()
def client():
    original = simulator.engine
    simulator.engine = SimulationEngine(seed=3, overrides={"layout": "large"})
    agents.attach(simulator.engine)
    simulator.engine.start()
    for _ in range(50):
        simulator.engine.tick()
    yield TestClient(app)
    simulator.engine = original
    agents.attach(original)


def test_tool_registry(client):
    tools = client.get("/api/v1/tools").json()
    assert len(tools) == 15
    close = next(t for t in tools if t["name"] == "close_aisle")
    assert close["is_write"] and close["requires_approval"]
    assert close["parameters"]["required"] == ["aisle_id"]


def test_run_then_approve_and_reject(client):
    run = client.post("/api/v1/agents/run", json={"request": "Close aisle 12 for maintenance."})
    body = run.json()
    assert run.status_code == 200 and body["planner"] == "offline playbooks"
    assert [s["tool"] for s in body["steps"]] == ["get_warehouse_state", "close_aisle"]
    assert body["pending"] and body["pending"][0]["tool"] == "close_aisle"
    assert "AISLE_12" not in simulator.engine.hazards.closures  # nothing changed yet
    aid = body["pending"][0]["action_id"]
    assert agents.status()["pending"][0]["action_id"] == aid
    done = client.post(f"/api/v1/agents/actions/{aid}/approve").json()
    assert done["approved_by"] and done["result"]["status"] in ("queued", "scheduled")
    again = client.post(f"/api/v1/agents/actions/{aid}/approve")
    assert again.status_code == 404  # decided once

    run = client.post("/api/v1/agents/run", json={"request": "Close aisle 20 for spill cleanup."})
    aid = run.json()["pending"][0]["action_id"]
    assert client.post(f"/api/v1/agents/actions/{aid}/reject").json()["rejected_by"]
    assert not agents.status()["pending"]


def test_read_only_request_has_no_pending(client):
    body = client.post("/api/v1/agents/run", json={"request": "Robot R3 has stopped. Handle it."})
    body = body.json()
    assert body["steps"][0]["tool"] == "get_robot_status" and not body["pending"]
    assert "R3" in body["answer"]


def test_approval_needs_the_actions_permission(client):
    run = client.post("/api/v1/agents/run", json={"request": "Close aisle 33 for maintenance."})
    aid = run.json()["pending"][0]["action_id"]
    with pytest.raises(PermissionError):
        agents.approve(aid, "clerk", can=lambda p: p != "robots:command")
    assert agents.status()["pending"]  # still waiting for someone allowed to approve it

"""Copilot API (Phase 6): read-only commands are answered at once, write commands run only after
approval, the live warehouse is checked before acting, and everything lands in the audit trail.

The keyword parser is used so the tests need no trained model; the tick loop is not started, so
tests advance the engine explicitly."""

import pytest
from fastapi.testclient import TestClient

from ai.nlp.intent_parser import RuleParser
from ai.nlp.understanding import understand
from app.main import app
from app.services.copilot import copilot
from app.services.simulator import simulator
from simulation.environment.engine import SimulationEngine

API = "/api/v1/copilot"


@pytest.fixture()
def client():
    original, original_parser = simulator.engine, copilot.parser
    # The configured large layout: the small default one has no named aisles to close.
    engine = SimulationEngine(seed=11, overrides={"orders": {"arrival_prob_per_tick": 0.0}})
    simulator.engine = engine
    copilot.attach(engine)
    copilot.parser = RuleParser()
    copilot.history.clear()
    yield TestClient(app)  # no context manager: lifespan (background tick loop) stays off
    simulator.engine, copilot.parser = original, original_parser
    copilot.attach(original)


def _chat(client, text: str) -> dict:
    response = client.post(f"{API}/chat", json={"text": text})
    assert response.status_code == 200
    return response.json()


def test_status_reports_the_loaded_parser(client):
    body = client.get(f"{API}/status").json()
    assert body["loaded"] and body["write_actions_need_approval"]
    assert "pause_robot" in body["intents"]


def test_read_command_is_answered_without_approval(client):
    reply = _chat(client, "where is robot 7?")
    assert reply["action"] is None and reply["answer"].startswith("R7 is")
    assert client.get(f"{API}/history").json()[0]["outcome"] == "answered"


def test_write_command_runs_only_after_approval(client):
    engine = simulator.engine
    reply = _chat(client, "pause R-12 now")
    assert reply["understanding"]["requires_approval"] and reply["action"]
    engine.tick()
    assert engine.robots["R12"].status.value != "PAUSED"  # nothing happens before approval

    result = client.post(f"{API}/actions/{reply['action']['id']}/approve").json()
    assert result["ok"]
    engine.tick()  # commands are applied at the start of the next tick
    assert engine.robots["R12"].status.value == "PAUSED"
    assert client.get(f"{API}/history").json()[0]["outcome"] == "approved and executed"
    again = client.post(f"{API}/actions/{reply['action']['id']}/approve").json()
    assert not again["ok"]  # an action runs once


def test_rejected_action_changes_nothing(client):
    reply = _chat(client, "pause robot 3")
    assert client.post(f"{API}/actions/{reply['action']['id']}/reject").json()["ok"]
    simulator.engine.tick()
    assert simulator.engine.robots["R3"].status.value != "PAUSED"
    assert client.get(f"{API}/history").json()[0]["outcome"] == "rejected"


def test_impossible_commands_are_explained_not_proposed(client):
    reply = _chat(client, "pause robot 99")
    assert reply["action"] is None and "no robot R99" in reply["answer"]
    reply = _chat(client, "resume robot 4")
    assert reply["action"] is None and "not paused" in reply["answer"]
    assert _chat(client, "order me a pizza")["understanding"]["status"] == "out_of_scope"


def test_approval_checks_the_warehouse_again(client):
    engine = simulator.engine
    reply = _chat(client, "pause robot 5")
    engine.robots["R5"].status = type(engine.robots["R5"].status)("PAUSED")  # changed meanwhile
    result = client.post(f"{API}/actions/{reply['action']['id']}/approve").json()
    assert not result["ok"] and "already paused" in result["answer"]


def test_close_and_reopen_an_aisle(client):
    engine = simulator.engine
    aisle = next(a for a in engine.layout.aisles if not engine.hazards.blockers(a.aisle_id))
    number = int(aisle.aisle_id[-2:])

    reply = _chat(client, f"close aisle {number} for maintenance")
    assert client.post(f"{API}/actions/{reply['action']['id']}/approve").json()["ok"]
    engine.tick()
    assert aisle.aisle_id in engine.hazards.closures
    for _ in range(50):  # an operator closure does not expire by itself
        engine.tick()
    assert aisle.aisle_id in engine.hazards.closures
    assert "already closed" in _chat(client, f"close aisle {number}")["answer"]

    reply = _chat(client, f"open aisle {number}")
    assert client.post(f"{API}/actions/{reply['action']['id']}/approve").json()["ok"]
    engine.tick()
    assert aisle.aisle_id not in engine.hazards.closures


def test_message_length_is_validated(client):
    assert client.post(f"{API}/chat", json={"text": ""}).status_code == 422
    assert client.post(f"{API}/chat", json={"text": "x" * 501}).status_code == 422


class _UnsureParser:
    """Always reads "pause" with low confidence (like DistilBERT on "unpause robot 8")."""

    name = "unsure"

    def parse(self, text: str) -> dict:
        return understand(
            text, "pause_robot", 0.6, [{"type": "ROBOT", "start": 0, "end": 3, "text": "R08"}]
        )


def test_low_confidence_write_is_flagged_not_sure(client):
    copilot.parser = _UnsureParser()
    reply = _chat(client, "R08 unpause")
    assert reply["action"]["unsure"] and "not sure" in reply["answer"]
    copilot.parser = RuleParser()
    assert not _chat(client, "pause R-12 now")["action"]["unsure"]

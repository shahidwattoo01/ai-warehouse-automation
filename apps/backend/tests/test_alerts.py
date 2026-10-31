"""Alert centre: incidents open, escalate, are acknowledged and resolved; notifications report
their outcome; the API and its permissions."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.alerts import AlertCentre
from app.services.alerts import centre as alert_centre
from app.services.simulator import simulator
from simulation.environment.engine import SimulationEngine
from simulation.warehouse.entities import RobotStatus


@pytest.fixture()
def engine():
    e = SimulationEngine(seed=3, overrides={"layout": "default"})
    e.start()
    return e


def step_to_next_check(e, centre, ticks=30):
    e.time += ticks - e.time % ticks  # the centre looks every 30 ticks
    centre.evaluate(e, {})


def wait_for(entry, status="PENDING", timeout=5.0):
    end = time.time() + timeout
    while entry["status"] == status and time.time() < end:
        time.sleep(0.05)


def test_a_fault_opens_escalates_and_resolves(engine):
    centre = AlertCentre()
    robot = engine.robots["R1"]
    robot.status = RobotStatus.FAULT
    step_to_next_check(engine, centre)
    inc = next(i for i in centre.incidents.values() if i.rule == "robot_fault")
    assert inc.subject == "R1" and inc.status == "OPEN" and inc.severity == "critical"
    step_to_next_check(engine, centre)
    assert (
        len([i for i in centre.incidents.values() if i.rule == "robot_fault"]) == 1
    )  # no duplicate
    engine.time += 5 * 60  # 5 simulated minutes (600 ticks per hour) without acknowledgement
    step_to_next_check(engine, centre)
    assert inc.escalated and inc.history[-1]["event"] == "ESCALATED"
    robot.status = RobotStatus.IDLE
    step_to_next_check(engine, centre)
    assert inc.status == "OPEN"  # absent once: not resolved yet (against flapping)
    step_to_next_check(engine, centre)
    assert inc.status == "RESOLVED" and inc.resolved_by == "system"


def test_noisy_rules_open_only_when_the_condition_persists(engine):
    centre = AlertCentre()
    flag = {"robots": {"R4": {"abnormal": True, "reason": "moving slowly"}}}
    engine.time += 30 - engine.time % 30
    centre.evaluate(engine, flag)
    assert not centre.incidents  # seen once
    engine.time += 30
    centre.evaluate(engine, {})  # gone again: forgotten
    engine.time += 30
    centre.evaluate(engine, flag)
    assert not centre.incidents
    engine.time += 30
    centre.evaluate(engine, flag)  # second check in a row
    assert [i.rule for i in centre.incidents.values()] == ["robot_abnormal"]


def test_acknowledge_stops_escalation_and_manual_resolve_stays_quiet(engine):
    centre = AlertCentre()
    engine.robots["R2"].status = RobotStatus.FAULT
    step_to_next_check(engine, centre)
    inc = next(iter(centre.incidents.values()))
    centre.acknowledge(inc.alert_id, "sara", "technician on the way", engine.time)
    engine.time += 30 * 60
    step_to_next_check(engine, centre)
    assert inc.status == "ACKNOWLEDGED" and not inc.escalated and inc.acknowledged_by == "sara"
    with pytest.raises(ValueError):
        centre.acknowledge(inc.alert_id, "sara", None, engine.time)
    centre.resolve(inc.alert_id, "sara", "robot replaced", engine.time)
    step_to_next_check(engine, centre)
    assert len(centre.incidents) == 1  # still in fault, but resolved by hand: no new incident
    engine.robots["R2"].status = RobotStatus.IDLE
    step_to_next_check(engine, centre)
    engine.robots["R2"].status = RobotStatus.FAULT
    step_to_next_check(engine, centre)
    assert len(centre.incidents) == 2  # a new fault after it had cleared is a new incident


def test_disabled_rules_and_thresholds(engine):
    centre = AlertCentre()
    centre.rules["robot_fault"]["enabled"] = False
    engine.robots["R1"].status = RobotStatus.FAULT
    engine.robots["R3"].battery = 5.0
    step_to_next_check(engine, centre)
    rules = {i.rule for i in centre.incidents.values()}
    assert "robot_fault" not in rules and "battery_critical" in rules


def test_notifications_report_their_outcome(engine, monkeypatch):
    from app.core.config import get_settings

    received = []

    class Hook(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Hook)
    threading.Thread(target=server.handle_request, daemon=True).start()
    monkeypatch.setattr(
        get_settings(), "alert_webhook_url", f"http://127.0.0.1:{server.server_port}/hook"
    )
    monkeypatch.setattr(get_settings(), "smtp_host", "")
    centre = AlertCentre()
    engine.robots["R1"].status = RobotStatus.FAULT  # notify: screen + webhook
    step_to_next_check(engine, centre)
    by_channel = {n["channel"]: n for n in centre.notifications}
    wait_for(by_channel["webhook"])
    server.server_close()
    assert by_channel["screen"]["status"] == "SHOWN"
    assert by_channel["webhook"]["status"] == "SENT"
    assert received and received[0]["alert"]["rule"] == "robot_fault"
    engine.time += 5 * 60  # escalation: email (not configured) + webhook
    step_to_next_check(engine, centre)
    email = next(n for n in centre.notifications if n["channel"] == "email")
    wait_for(email)
    assert email["status"] == "NOT_CONFIGURED"


def test_api_lists_and_handles_incidents():
    client = TestClient(app)
    original = simulator.engine
    simulator.engine = SimulationEngine(seed=3, overrides={"layout": "default"})
    alert_centre.reset()
    try:
        simulator.engine.robots["R1"].status = RobotStatus.FAULT
        step_to_next_check(simulator.engine, alert_centre)
        page = client.get("/api/v1/alerts").json()
        inc = next(i for i in page["incidents"] if i["rule"] == "robot_fault")
        assert page["summary"]["critical"] >= 1 and inc["name"] == "Robot in fault"
        done = client.post(f"/api/v1/alerts/{inc['alert_id']}/acknowledge", json={"note": "on it"})
        assert done.json()["acknowledged_by"] == "test-admin"
        assert (
            client.post(f"/api/v1/alerts/{inc['alert_id']}/acknowledge", json={}).status_code == 409
        )
        rule = client.put("/api/v1/alerts/rules/battery_critical", json={"threshold": 15}).json()
        assert rule["threshold"] == 15
        bad = client.put("/api/v1/alerts/rules/robot_fault", json={"threshold": 3})
        assert bad.status_code == 422  # this rule has no threshold
        assert client.get("/api/v1/alerts/notifications").json()
    finally:
        alert_centre.rules["battery_critical"]["threshold"] = 10
        alert_centre.reset()
        simulator.engine = original

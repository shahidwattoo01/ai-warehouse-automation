"""Monitoring: liveness and readiness, the Prometheus metrics endpoint, request ids, JSON logs,
and that every metric the alert rules and the Grafana dashboard use is really exported."""

import json
import logging
import re
import time
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app import main
from app.core.observability import JsonFormatter, RequestIdFilter, request_id
from app.main import app
from app.services.simulator import simulator

ROOT = Path(__file__).resolve().parents[3]
SAMPLE = re.compile(r'^[a-zA-Z_:][a-zA-Z0-9_:]*(\{([a-z_]+="[^"]*",?)*\})? -?[0-9.e+-]+$|.* \+Inf$')


@pytest.fixture()
def client():
    with TestClient(app) as c:  # runs the lifespan: the simulator loop is ticking
        yield c


def test_health_and_ready(client):
    assert client.get("/health").json()["status"] == "ok"
    body = client.get("/ready").json()
    assert body["ready"] is True
    assert body["checks"]["simulator_loop"]["ok"] and body["checks"]["simulator_loop"]["required"]
    assert body["checks"]["knowledge_base"]["required"] is False  # the floor works without it


def test_not_ready_when_the_loop_stalls(client):
    beat = simulator.loop_heartbeat
    task = simulator._task
    try:
        simulator._task = None  # as if the loop had died
        r = client.get("/ready")
        assert r.status_code == 503 and r.json()["checks"]["simulator_loop"]["ok"] is False
    finally:
        simulator._task, simulator.loop_heartbeat = task, beat


def test_metrics_format_and_route_templates(client):
    client.get("/api/v1/robots/R1")
    client.get("/api/v1/robots/R2")
    client.get("/no/such/page")
    r = client.get("/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain; version=0.0.4")
    lines = [x for x in r.text.splitlines() if x and not x.startswith("#")]
    bad = [x for x in lines if not SAMPLE.match(x)]
    assert not bad, bad[:5]
    text = r.text
    # one series per route template, never per robot id
    assert 'route="/api/v1/robots/{robot_id}",status="200"} 2' in text
    assert "R1" not in "".join(x for x in lines if x.startswith("warehouse_http"))
    assert 'route="unmatched",status="404"' in text
    for name in ("warehouse_sim_ticks_total", "warehouse_robots", "warehouse_safety_state",
                 "warehouse_alert_incidents", "warehouse_vda5050_vehicles"):  # fmt: skip
        assert f"\n{name}" in text, name
    assert r.headers["content-security-policy"].startswith("default-src 'none'")


def test_metrics_token(client, monkeypatch):
    monkeypatch.setattr(main.settings, "metrics_token", "scrape-secret-123")
    assert client.get("/metrics").status_code == 401
    wrong = {"Authorization": "Bearer nope"}
    assert client.get("/metrics", headers=wrong).status_code == 401
    right = {"Authorization": "Bearer scrape-secret-123"}
    assert client.get("/metrics", headers=right).status_code == 200


def exported_names(text: str) -> set[str]:
    return {line.split()[2] for line in text.splitlines() if line.startswith("# TYPE")}


def used_names(expr: str) -> set[str]:
    names = set(re.findall(r"\bwarehouse_[a-z0-9_]+", expr))
    return {re.sub(r"_(bucket|sum|count)$", "", n) for n in names}


def test_rules_and_dashboard_use_exported_metrics(client):
    time.sleep(0.6)  # at least one tick
    exported = exported_names(client.get("/metrics").text)
    rules = yaml.safe_load((ROOT / "monitoring/prometheus/alert_rules.yml").read_text())
    exprs = [rule["expr"] for g in rules["groups"] for rule in g["rules"]]
    dash = json.loads((ROOT / "monitoring/grafana/dashboards/warehouse.json").read_text())
    exprs += [t["expr"] for p in dash["panels"] for t in p.get("targets", [])]
    missing = {n for e in exprs for n in used_names(e)} - exported
    assert not missing, missing
    assert len({p["id"] for p in dash["panels"]}) == len(dash["panels"])


def test_request_id_header(client):
    r = client.get("/health", headers={"X-Request-ID": "trace-abc-123"})
    assert r.headers["x-request-id"] == "trace-abc-123"
    r = client.get("/health", headers={"X-Request-ID": "bad id\r\nX-Evil: 1"})
    assert re.fullmatch(r"[0-9a-f]{32}", r.headers["x-request-id"])  # unsafe ids are replaced


def test_json_log_lines():
    record = logging.LogRecord("app.test", logging.WARNING, __file__, 1, "aisle %s closed", ("A3",),
                               None)  # fmt: skip
    record.robot_id = "R7"
    token = request_id.set("req-12345678")
    try:
        RequestIdFilter().filter(record)
    finally:
        request_id.reset(token)
    data = json.loads(JsonFormatter().format(record))
    assert data["message"] == "aisle A3 closed" and data["level"] == "WARNING"
    assert data["request_id"] == "req-12345678" and data["robot_id"] == "R7"
    assert data["time"].endswith("Z")

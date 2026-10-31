"""ERP API: the signed order webhook, status, outbox and the mock ERP."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.services.erp import erp
from app.services.simulator import simulator
from integration.erp.connector import sign
from simulation.environment.engine import SimulationEngine

API = "/api/v1/erp"


@pytest.fixture()
def client(monkeypatch):
    original = simulator.engine
    simulator.engine = SimulationEngine(
        seed=11, overrides={"layout": "default", "inventory_model": "wms"}
    )
    simulator.engine.start()
    monkeypatch.setattr(get_settings(), "erp_webhook_secret", "hook-secret")
    erp.attach(simulator.engine)
    erp.connector.stop()  # the test drives the connector itself
    yield TestClient(app)
    simulator.engine = original
    erp.attach(original)


def post_signed(client, order: dict, secret="hook-secret", ts=None):
    body = json.dumps(order).encode()
    ts = ts or str(int(time.time()))
    headers = {"X-ERP-Timestamp": ts, "X-ERP-Signature": sign(secret, ts, body),
               "Content-Type": "application/json"}  # fmt: skip
    return client.post(f"{API}/webhooks/orders", content=body, headers=headers)


def test_signed_webhook_creates_one_order(client):
    wms = simulator.engine.inventory.wms
    order = {"number": "SO-W1", "customer_id": "C-0004", "service": "ECONOMY",
             "lines": [{"sku": wms.orderable()[0], "qty": 1}]}  # fmt: skip
    r = post_signed(client, order)
    assert r.status_code == 200 and r.json()["accepted"]
    oid = r.json()["wms_order_id"]
    assert simulator.engine.orders[oid].source == "ERP"
    assert wms.out.orders[oid].external_ref == "SO-W1"
    assert post_signed(client, order).json()["wms_order_id"] == oid  # retried push: same order
    assert post_signed(client, order, secret="guess").status_code == 401
    old = str(int(time.time()) - 3600)
    assert post_signed(client, order, ts=old).status_code == 401
    unsigned = client.post(f"{API}/webhooks/orders", json=order)
    assert unsigned.status_code == 401
    bad = post_signed(client, {**order, "number": "SO-W2", "lines": [{"sku": "P-X", "qty": 1}]})
    assert bad.status_code == 422 and "unknown SKU" in bad.json()["detail"]["message"]


def test_status_mock_orders_and_pull(client):
    created = client.post(f"{API}/mock/orders", json={"service": "EXPRESS"})
    assert created.status_code == 201 and created.json()["status"] == "RELEASED"
    assert client.post(f"{API}/pull").json() == {"pull": "requested"}
    erp.connector.work_once()
    erp.connector.after_tick()  # the order is created on the loop
    erp.connector.work_once()  # and acknowledged
    s = client.get(f"{API}/status").json()
    assert s["client"] == "in-process mock" and s["imported"] == 1 and s["webhook"] is True
    assert s["mock"]["orders"]["ACCEPTED"] == 1
    box = client.get(f"{API}/outbox").json()
    assert box[0]["kind"] == "ack" and box[0]["status"] == "SENT"

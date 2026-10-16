"""Orders API: manual dispatch (create, assign, assignment mode). The tick loop is not started, so
tests advance the engine explicitly with engine.tick()."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.simulator import simulator
from simulation.environment.engine import SimulationEngine

API = "/api/v1"


@pytest.fixture()
def client():
    original = simulator.engine
    simulator.engine = SimulationEngine(
        seed=11, overrides={"layout": "default", "orders": {"arrival_prob_per_tick": 0.0}}
    )
    yield TestClient(app)  # no context manager: lifespan (background tick loop) stays off
    simulator.engine = original


def _tick(n: int = 1) -> None:
    for _ in range(n):
        simulator.engine.tick()


def test_manual_mode_keeps_orders_waiting_until_operator_assigns(client):
    assert (
        client.put(f"{API}/simulation/assignment-mode", json={"mode": "manual"}).status_code == 202
    )
    _tick()
    assert client.get(f"{API}/simulation/assignment-mode").json() == {"mode": "manual"}

    created = client.post(f"{API}/orders", json={"priority": "HIGH"}).json()
    order_id = created["order_id"]
    _tick(5)
    order = next(o for o in client.get(f"{API}/orders").json() if o["order_id"] == order_id)
    assert order["status"] == "PENDING" and order["source"] == "MANUAL"

    r = client.post(f"{API}/orders/{order_id}/assign", json={"robot_id": "R4"})
    assert r.status_code == 202
    _tick()
    order = next(o for o in client.get(f"{API}/orders").json() if o["order_id"] == order_id)
    assert (
        order["status"] == "ASSIGNED"
        and order["assigned_robot"] == "R4"
        and order["manual_assignment"]
    )
    assert simulator.engine.robots["R4"].current_task == order_id


def test_create_with_specific_product_and_robot(client):
    product = client.get(f"{API}/inventory").json()[0]
    r = client.post(
        f"{API}/orders",
        json={"items": [{"product_id": product["product_id"], "quantity": 1}], "robot_id": "R2"},
    )
    assert r.status_code == 202
    _tick()
    order = simulator.engine.orders[r.json()["order_id"]]
    assert order.assigned_robot == "R2" and order.items[0].product_id == product["product_id"]


def test_assign_rejects_busy_robot_and_unknown_order(client):
    a = client.post(f"{API}/orders", json={"robot_id": "R1"}).json()["order_id"]
    _tick()
    b = client.post(f"{API}/orders", json={}).json()["order_id"]
    client.put(f"{API}/simulation/assignment-mode", json={"mode": "manual"})
    _tick()
    busy = client.post(f"{API}/orders/{b}/assign", json={"robot_id": "R1"})
    assert busy.status_code == 409 and "busy" in busy.json()["detail"]["message"]
    assert (
        client.post(f"{API}/orders/{a}/assign", json={"robot_id": "R2"}).status_code == 409
    )  # already assigned
    assert client.post(f"{API}/orders/O99999/assign", json={"robot_id": "R2"}).status_code == 404
    assert (
        client.post(f"{API}/orders", json={"items": [{"product_id": "P-nope"}]}).status_code == 422
    )

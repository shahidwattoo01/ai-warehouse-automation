"""Platform events: CloudEvents for robots, orders, outbound, safety and alerts on the bus,
replay after a sequence number, and the Server-Sent Events stream."""

import json
import threading

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.alerts import AlertCentre
from app.services.events import events_service
from app.services.simulator import simulator
from simulation.environment.engine import SimulationEngine
from simulation.warehouse.entities import RobotStatus


@pytest.fixture()
def world():
    original = simulator.engine
    e = SimulationEngine(seed=7, overrides={"layout": "default", "inventory_model": "wms"})
    e.start()
    simulator.engine = e
    events_service.attach(e)
    seen = []
    events_service.bus.subscribe("warehouse/v1/#", lambda t, p: seen.append((t, p)))
    yield e, seen
    simulator.engine = original
    events_service.attach(original)


def test_simulator_wms_safety_and_alert_events(world):
    e, seen = world
    centre = AlertCentre()
    for _ in range(400):
        events = e.tick()
        if e.time == 200:
            e.safety.engage("sara", "test stop")
        if e.time == 210:
            e.robots["R1"].status = RobotStatus.FAULT
        if e.time % 30 == 0:
            centre.evaluate(e, {})
        events_service.after_tick(events, centre.take_changed())
    topics = {t for t, _ in seen}
    expected_topics = ["orders/created", "orders/assigned", "orders/delivered_to_packing"]
    expected_topics += ["orders/at_pack", "orders/packed", "safety/estop", "alerts/opened"]
    for expected in expected_topics:
        assert f"warehouse/v1/{expected}" in topics, expected
    event = next(p for t, p in seen if t.endswith("orders/packed"))
    assert event["specversion"] == "1.0" and event["type"] == "com.warehouseai.orders.packed"
    assert event["data"]["from"] == "AT_PACK" and event["subject"]
    stop = next(p for t, p in seen if t.endswith("safety/estop"))
    assert stop["data"]["user"] == "sara"
    seqs = [p["sequence"] for _, p in seen]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)  # one running number


def test_replay_and_catalog(world):
    e, _ = world
    for _ in range(100):
        events_service.after_tick(e.tick(), [])
    client = TestClient(app)
    cat = client.get("/api/v1/events/catalog").json()
    assert cat["mqtt_topic_filter"] == "warehouse/v1/#" and cat["sequence"] > 0
    all_events = client.get("/api/v1/events", params={"limit": 2000}).json()
    middle = all_events[len(all_events) // 2]["sequence"]
    later = client.get("/api/v1/events", params={"after": middle}).json()
    assert later and all(x["sequence"] > middle for x in later)
    orders = client.get("/api/v1/events", params={"prefix": "orders"}).json()
    assert orders and all(x["topic"].startswith("warehouse/v1/orders") for x in orders)


def test_server_sent_events_stream(world):
    """The stream's body as an HTTP client reads it (the test client cannot hold an endless
    response open, so the endpoint runs on a loop here and events arrive from a thread)."""
    import asyncio

    from app.api.v1.events import stream

    e, _ = world

    async def read() -> list[str]:
        response = await stream(prefix="orders")
        assert response.media_type == "text/event-stream"
        body = response.body_iterator
        chunks = [await body.__anext__()]  # "retry" and the subscription comment

        def produce():
            for _ in range(80):
                events_service.after_tick(e.tick(), [])

        threading.Thread(target=produce, daemon=True).start()  # like the MQTT network thread
        while sum(c.startswith("id: ") for c in chunks) < 2:
            chunks.append(await asyncio.wait_for(body.__anext__(), timeout=10))
        await body.aclose()
        return chunks

    chunks = asyncio.run(read())
    assert chunks[0].startswith("retry: 3000")
    events = [c for c in chunks if c.startswith("id: ")]
    for c in events:
        data = json.loads(c.split("data: ", 1)[1])
        assert data["topic"].startswith("warehouse/v1/orders") and data["specversion"] == "1.0"
    assert not events_service.publisher.subscribers  # unsubscribed when the client went away

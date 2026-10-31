"""VDA 5050: message rules, the simulated robots as vehicles, master control, the transports."""

import pytest

from integration.vda5050 import messages as m
from integration.vda5050.master import MasterControl
from integration.vda5050.transport import InMemoryBus, MqttTransport, matches
from integration.vda5050.vehicle import VehicleFleet
from simulation.environment.engine import SimulationEngine
from simulation.warehouse.entities import RobotStatus


@pytest.fixture()
def setup():
    e = SimulationEngine(seed=3, overrides={"layout": "default"})
    e.start()
    bus = InMemoryBus()
    fleet = VehicleFleet(e, bus)
    master = MasterControl(e, bus)

    def run(ticks):
        for _ in range(ticks):
            master.after_tick(e.tick())
            fleet.tick()

    return e, bus, fleet, master, run


def test_topics_headers_and_order_rules():
    assert m.topic("R7", "state") == "uagv/v2/WarehouseAI/R7/state"
    assert m.parse_topic("uagv/v2/WarehouseAI/R7/order") == ("WarehouseAI", "R7", "order")
    assert m.parse_topic("other/R7") is None
    h = m.Headers()
    assert [h("R1", "state")["headerId"] for _ in range(3)] == [0, 1, 2]
    assert h("R1", "order")["headerId"] == 0  # counted per topic
    a, b = m.node("A", 0, 1, 2), m.node("B", 2, 3, 4)
    good = {**h("R1", "order"), "orderId": "O1", "orderUpdateId": 0, "nodes": [a, b],
            "edges": [m.edge(a, b)]}  # fmt: skip
    assert m.validate("order", good) == [] and good["edges"][0]["sequenceId"] == 1
    assert "node sequenceIds must be even" in m.validate(
        "order", {**good, "nodes": [a, m.node("C", 3, 0, 0)]}
    )


def test_orders_go_out_and_vehicles_report_progress(setup):
    e, bus, fleet, master, run = setup
    run(300)
    orders = [x for x in bus.log if x["topic"].endswith("/order")]
    assert orders and all(m.validate("order", x["payload"]) == [] for x in orders)
    first = orders[-1]["payload"]
    assert first["nodes"][0]["nodeId"].endswith("-start") and first["nodes"][-1][
        "nodeId"
    ].startswith("PACK")
    states = [x["payload"] for x in bus.log if x["topic"].endswith("/state")]
    assert states and all(m.validate("state", s) == [] for s in states)
    rows = {r["serial"]: r for r in master.summary()}
    assert len(rows) == len(e.robots) and all(r["connection"] == "ONLINE" for r in rows.values())
    done = [r for r in rows.values() if r["order_id"] and r["nodes_left"] == 0]
    assert done and all(r["last_node"].startswith("PACK") for r in done)  # delivered: last node


def test_instant_actions_act_on_the_simulator(setup):
    e, bus, fleet, master, run = setup
    master.instant_action(["R1"], "startPause")
    run(1)
    assert e.robots["R1"].status == RobotStatus.PAUSED
    assert master.states["R1"]["paused"] is True
    master.instant_action(["R1"], "stopPause")
    ids = master.instant_action(["R1"], "cancelOrder")
    run(1)
    assert e.robots["R1"].status != RobotStatus.PAUSED
    states = {a["actionId"]: a for a in master.states["R1"]["actionStates"]}
    assert states[ids[0]]["actionStatus"] == "FAILED"
    with pytest.raises(ValueError):
        master.instant_action(["R1"], "selfDestruct")


def test_an_invalid_order_is_reported_as_a_vehicle_error(setup):
    e, bus, fleet, master, run = setup
    a = m.node("A", 0, 1, 1)
    bad = {**m.Headers()("R2", "order"), "orderId": "X1", "orderUpdateId": 0, "nodes": [a, a],
           "edges": []}  # fmt: skip
    bus.publish(m.topic("R2", "order"), bad)
    run(1)
    errors = master.states["R2"]["errors"]
    assert errors and errors[0]["errorType"] == "validationError"


def test_topic_matching_and_retained_messages():
    assert matches("uagv/v2/+/+/state", "uagv/v2/WarehouseAI/R1/state")
    assert not matches("uagv/v2/+/+/state", "uagv/v2/WarehouseAI/R1/order")
    assert matches("uagv/#", "uagv/v2/x/y/z")
    bus = InMemoryBus()
    bus.publish("uagv/v2/W/R1/connection", {"connectionState": "ONLINE"}, retain=True)
    got = []
    bus.subscribe("uagv/v2/+/+/connection", lambda t, p: got.append(p))
    assert got == [{"connectionState": "ONLINE"}]  # a late subscriber gets the retained message


def test_mqtt_transport_publishes_and_drains(monkeypatch):
    import paho.mqtt.client as mqtt

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.published, self.subscribed, self.will = [], [], None

        def username_pw_set(self, user, password):
            self.user = user

        def will_set(self, topic, payload, qos, retain):
            self.will = (topic, payload, retain)

        def connect_async(self, host, port):
            self.address = (host, port)

        def loop_start(self):
            pass

        def publish(self, topic, payload, qos, retain):
            self.published.append((topic, payload, retain))

        def subscribe(self, pattern, qos):
            self.subscribed.append(pattern)

    monkeypatch.setattr(mqtt, "Client", FakeClient)
    t = MqttTransport("mqtt://fleet:pw@broker.local:1884", "master", will=("w/t", {"a": 1}))
    assert t.client.address == ("broker.local", 1884) and t.client.user == "fleet"
    assert t.client.will[2] is True  # retained last will (CONNECTIONBROKEN)
    got = []
    t.subscribe("uagv/v2/+/+/state", lambda topic, p: got.append(p))
    t._on_connect(t.client, None, None, type("R", (), {"is_failure": False})())
    assert t.client.subscribed == ["uagv/v2/+/+/state"]  # (re)subscribed on connect
    t.publish("uagv/v2/W/R1/order", {"orderId": "O1"}, qos=1)
    assert t.client.published[0][0] == "uagv/v2/W/R1/order"
    msg = type("M", (), {"topic": "uagv/v2/W/R1/state", "payload": b'{"headerId": 3}'})()
    t._on_message(t.client, None, msg)
    t._on_message(t.client, None, type("M", (), {"topic": "x", "payload": b"not json"})())
    assert got == []  # nothing runs on the network thread
    t.drain()
    assert got == [{"headerId": 3}] and t.counts["invalid"] == 1

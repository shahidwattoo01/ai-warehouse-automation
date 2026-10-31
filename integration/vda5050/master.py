"""Master control: the fleet manager's side of VDA 5050.

When the dispatcher gives an order to a robot, master control publishes a VDA 5050 `order`:
the robot's position, then one node per pick face (named after its rack location), then the
packing station, joined by edges. It keeps the latest `state` and `connection` of every vehicle
on the bus (simulated or real) and sends `instantActions` on request.
"""

from __future__ import annotations

import itertools

from integration.vda5050 import messages as m
from simulation.events.events import EventType


class MasterControl:
    def __init__(self, engine, bus) -> None:
        self.engine = engine
        self.bus = bus
        self.headers = m.Headers()
        self.states: dict[str, dict] = {}
        self.connections: dict[str, str] = {}
        self.invalid: list[dict] = []
        self._action_ids = itertools.count(1)
        base = f"{m.INTERFACE}/{m.MAJOR}/+/+"
        bus.subscribe(f"{base}/state", self._on_state)
        bus.subscribe(f"{base}/connection", self._on_connection)

    def _on_state(self, topic: str, msg: dict) -> None:
        parsed = m.parse_topic(topic)
        problems = m.validate("state", msg)
        if problems:
            self.invalid.append({"topic": topic, "problems": problems})
            self.invalid = self.invalid[-50:]
            return
        self.states[parsed[1]] = msg

    def _on_connection(self, topic: str, msg: dict) -> None:
        parsed = m.parse_topic(topic)
        self.connections[parsed[1]] = msg.get("connectionState", "?")

    # ----- orders ----------------------------------------------------------------------------
    def build_order(self, robot_id: str, order_id: str) -> dict | None:
        eng = self.engine
        task = eng.controller.tasks.get(robot_id)
        order = eng.orders.get(order_id)
        if task is None or order is None or task.order_id != order_id:
            return None
        robot = eng.robots[robot_id]
        points = [(f"{robot_id}-start", task.metrics.get("start", robot.position))]
        points += list(zip(task.stop_names, task.stops, strict=False))
        points.append((order.destination or "PACK", task.drop))
        nodes = [m.node(name, 2 * i, *cell) for i, (name, cell) in enumerate(points)]
        nodes[0]["released"] = True
        edges = [m.edge(a, b) for a, b in zip(nodes, nodes[1:], strict=False)]
        return {
            **self.headers(robot_id, "order"),
            "orderId": order_id,
            "orderUpdateId": 0,
            "nodes": nodes,
            "edges": edges,
        }

    def after_tick(self, events: list) -> None:
        for e in events:
            if e.type == EventType.ORDER_ASSIGNED:
                msg = self.build_order(e.payload["robot_id"], e.entity_id)
                if msg:
                    self.bus.publish(m.topic(e.payload["robot_id"], "order"), msg, qos=1)

    # ----- instant actions -------------------------------------------------------------------
    def instant_action(self, serials: list[str], action_type: str) -> list[str]:
        if action_type not in m.INSTANT_ACTIONS:
            raise ValueError(f"unsupported instant action {action_type}")
        ids = []
        for serial in serials:
            action_id = f"ia-{next(self._action_ids):06d}"
            msg = {
                **self.headers(serial, "instantActions"),
                "actions": [m.action(action_type, action_id)],
            }
            self.bus.publish(m.topic(serial, "instantActions"), msg, qos=1)
            ids.append(action_id)
        return ids

    def summary(self) -> list[dict]:
        rows = []
        for serial in sorted(set(self.states) | set(self.connections), key=_robot_order):
            s = self.states.get(serial, {})
            rows.append(
                {
                    "serial": serial,
                    "connection": self.connections.get(serial, "?"),
                    "order_id": s.get("orderId") or None,
                    "last_node": s.get("lastNodeId") or None,
                    "nodes_left": len(s.get("nodeStates", [])),
                    "driving": s.get("driving"),
                    "paused": s.get("paused"),
                    "battery": (s.get("batteryState") or {}).get("batteryCharge"),
                    "errors": [err["errorType"] for err in s.get("errors", [])],
                    "e_stop": (s.get("safetyState") or {}).get("eStop"),
                    "header_id": s.get("headerId"),
                    "timestamp": s.get("timestamp"),
                }
            )
        return rows


def _robot_order(serial: str) -> tuple:
    digits = "".join(ch for ch in serial if ch.isdigit())
    return (serial.rstrip("0123456789"), int(digits) if digits else 0)

"""The simulated robots as VDA 5050 vehicles.

Each robot subscribes to its `order` and `instantActions` topics and publishes `connection`
(ONLINE, retained), `factsheet` (retained) and `state` (every 10 ticks, at once after a change).
Orders are checked and followed node by node: the robot's progress through its pick faces and the
packing station shows as lastNodeId / nodeStates. Instant actions act on the simulator:
startPause / stopPause pause and resume the robot, stateRequest / factsheetRequest answer at
once; cancelOrder is refused (FAILED): a picked order cannot be dropped in this simulator.
"""

from __future__ import annotations

from integration.vda5050 import messages as m
from simulation.environment.engine import Command

STATE_EVERY = 10  # ticks (5 s at the live 2 Hz; the standard asks for at least every 30 s)


class Vehicle:
    def __init__(self, fleet, robot_id: str) -> None:
        self.fleet = fleet
        self.serial = robot_id
        self.order: dict | None = None
        self.order_nodes: list[dict] = []  # still to reach
        self.last_node: tuple[str, int] = ("", 0)
        self.actions: dict[str, dict] = {}  # actionId -> actionState
        self.errors: list[dict] = []
        self._dirty = True

    # ----- incoming --------------------------------------------------------------------------
    def on_order(self, msg: dict) -> None:
        problems = m.validate("order", msg)
        if self.order and msg["orderId"] == self.order["orderId"]:
            if msg["orderUpdateId"] <= self.order["orderUpdateId"]:
                problems.append("orderUpdateId must increase")
        if problems:
            self.errors.append(
                {
                    "errorType": "validationError",
                    "errorLevel": "WARNING",
                    "errorDescription": "; ".join(problems),
                    "errorReferences": [
                        {"referenceKey": "orderId", "referenceValue": msg.get("orderId")}
                    ],
                }
            )
        else:
            self.order = msg
            self.order_nodes = list(msg["nodes"])
            self.errors = [e for e in self.errors if e["errorType"] != "validationError"]
        self._dirty = True

    def on_instant_actions(self, msg: dict) -> None:
        eng = self.fleet.engine
        for a in msg.get("actions", []):
            state = {"actionId": a["actionId"], "actionType": a["actionType"],
                     "actionStatus": "FINISHED", "resultDescription": ""}  # fmt: skip
            kind = a["actionType"]
            if kind in ("startPause", "stopPause"):
                name = "pause_robot" if kind == "startPause" else "resume_robot"
                eng.submit(Command(name, {"robot_id": self.serial}))
            elif kind == "stateRequest":
                self._dirty = True
            elif kind == "factsheetRequest":
                self.publish_factsheet()
            elif kind == "cancelOrder":
                state["actionStatus"] = "FAILED"
                state["resultDescription"] = "orders cannot be cancelled on the vehicle here"
            else:
                state["actionStatus"] = "FAILED"
                state["resultDescription"] = f"unsupported action {kind}"
            self.actions[a["actionId"]] = state
        while len(self.actions) > 20:  # report the latest actions only
            self.actions.pop(next(iter(self.actions)))
        self._dirty = True

    # ----- outgoing --------------------------------------------------------------------------
    def publish_connection(self, status: str = "ONLINE") -> None:
        msg = {**self.fleet.headers(self.serial, "connection"), "connectionState": status}
        self.fleet.bus.publish(m.topic(self.serial, "connection"), msg, retain=True, qos=1)

    def publish_factsheet(self) -> None:
        cfg = self.fleet.engine.config
        msg = {
            **self.fleet.headers(self.serial, "factsheet"),
            "typeSpecification": {
                "seriesName": "AMR-500 (simulated)",
                "agvKinematic": "DIFF",
                "agvClass": "CARRIER",
                "maxLoadMass": 30,
                "localizationTypes": ["NATURAL"],
                "navigationTypes": ["AUTONOMOUS"],
            },
            "physicalParameters": {
                "speedMin": 0.0,
                "speedMax": float(cfg.get("tick_hz", 2)),  # one 1 m cell per tick
                "length": 0.9,
                "width": 0.7,
                "heightMax": 0.4,
            },
            "protocolLimits": {"maxStringLens": {}, "maxArrayLens": {}, "timing": {}},
            "protocolFeatures": {
                "agvActions": [
                    {"actionType": t, "actionScopes": ["INSTANT"]} for t in m.INSTANT_ACTIONS
                ],
                "optionalParameters": [],
            },
        }
        self.fleet.bus.publish(m.topic(self.serial, "factsheet"), msg, retain=True)

    def state(self) -> dict:
        eng = self.fleet.engine
        robot = eng.robots[self.serial]
        self._advance()
        held = eng.safety.holds(robot)
        order_id = self.order["orderId"] if self.order else ""
        return {
            **self.fleet.headers(self.serial, "state"),
            "orderId": order_id,
            "orderUpdateId": self.order["orderUpdateId"] if self.order else 0,
            "lastNodeId": self.last_node[0],
            "lastNodeSequenceId": self.last_node[1],
            "nodeStates": [
                {
                    "nodeId": n["nodeId"],
                    "sequenceId": n["sequenceId"],
                    "released": True,
                    "nodePosition": n["nodePosition"],
                }
                for n in self.order_nodes
            ],  # fmt: skip
            "edgeStates": [
                {"edgeId": e["edgeId"], "sequenceId": e["sequenceId"], "released": True}
                for e in (self.order or {}).get("edges", [])
                if e["sequenceId"] > self.last_node[1]
            ],
            "agvPosition": {
                "x": float(robot.position[0]),
                "y": float(robot.position[1]),
                "theta": round(getattr(robot, "heading", 0.0) or 0.0, 3),
                "mapId": m.MAP_ID,
                "positionInitialized": True,
            },
            "velocity": {"vx": 0.0, "vy": 0.0, "omega": 0.0},
            "driving": bool(robot.route)
            and robot.status.value not in ("PAUSED", "FAULT")
            and not held,
            "paused": robot.status.value == "PAUSED" or held,
            "newBaseRequest": False,
            "distanceSinceLastNode": 0.0,
            "loads": [{"loadId": order_id, "loadType": "TOTE"}] if robot.load else [],
            "actionStates": list(self.actions.values()),
            "batteryState": {
                "batteryCharge": round(robot.battery, 1),
                "charging": robot.status.value == "CHARGING",
                "reach": None,
            },
            "operatingMode": "AUTOMATIC",
            "errors": self.errors
            + (
                [
                    {
                        "errorType": "robotFault",
                        "errorLevel": "FATAL",
                        "errorDescription": "stop event (simulated fault)",
                    }
                ]
                if robot.status.value == "FAULT"
                else []
            ),  # fmt: skip
            "information": [],
            "safetyState": {"eStop": "REMOTE" if held else "NONE", "fieldViolation": False},
        }

    def _advance(self) -> None:
        """Follow the order: nodes the robot has passed leave nodeStates."""
        if not self.order:
            return
        eng = self.fleet.engine
        task = eng.controller.tasks.get(self.serial)
        sim_order = eng.orders.get(self.order["orderId"])
        finished = sim_order is None or sim_order.status.value in ("DELIVERED", "LATE")
        remaining_picks = len(task.stops) if task and task.order_id == self.order["orderId"] else 0
        picks_total = len(self.order["nodes"]) - 2  # start node, pick faces, packing station
        reached = (1 + picks_total - remaining_picks) if not finished else len(self.order["nodes"])
        if task and task.order_id == self.order["orderId"] and task.stage == "DROPPING":
            reached = len(self.order["nodes"])
        reached = max(1, min(reached, len(self.order["nodes"])))
        done = self.order["nodes"][:reached]
        if done and done[-1]["nodeId"] != self.last_node[0]:
            self.last_node = (done[-1]["nodeId"], done[-1]["sequenceId"])
            self._dirty = True
        self.order_nodes = self.order["nodes"][reached:]

    def tick(self, time: int) -> None:
        if self._dirty or time % STATE_EVERY == 0:
            self.fleet.bus.publish(m.topic(self.serial, "state"), self.state())
            self._dirty = False


class VehicleFleet:
    """All robots of the simulator as VDA 5050 vehicles on one transport."""

    def __init__(self, engine, bus) -> None:
        self.engine = engine
        self.bus = bus
        self.headers = m.Headers()
        self.vehicles = {rid: Vehicle(self, rid) for rid in engine.robots}
        bus.subscribe(f"{m.INTERFACE}/{m.MAJOR}/{m.MANUFACTURER}/+/order", self._route("order"))
        bus.subscribe(
            f"{m.INTERFACE}/{m.MAJOR}/{m.MANUFACTURER}/+/instantActions",
            self._route("instantActions"),
        )
        for v in self.vehicles.values():
            v.publish_connection("ONLINE")
            v.publish_factsheet()

    def _route(self, name: str):
        def handle(topic: str, msg: dict) -> None:
            parsed = m.parse_topic(topic)
            vehicle = self.vehicles.get(parsed[1]) if parsed else None
            if vehicle is None:
                return
            if name == "order":
                vehicle.on_order(msg)
            else:
                vehicle.on_instant_actions(msg)

        return handle

    def tick(self) -> None:
        for v in self.vehicles.values():
            v.tick(self.engine.time)

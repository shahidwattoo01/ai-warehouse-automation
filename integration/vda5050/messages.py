"""VDA 5050 v2.0 messages: topics, headers and the order / instantActions / state / connection /
factsheet payloads, as plain JSON-ready dicts.

Topic: {interface}/{major version}/{manufacturer}/{serial number}/{topic}, e.g.
uagv/v2/WarehouseAI/R7/state. Master control publishes `order` and `instantActions`; the
vehicle publishes `state`, `connection`, `visualization` and `factsheet`.
"""

from __future__ import annotations

import datetime as dt

INTERFACE = "uagv"
VERSION = "2.0.0"
MAJOR = "v2"
MANUFACTURER = "WarehouseAI"
MAP_ID = "warehouse"

MASTER_TOPICS = ("order", "instantActions")
VEHICLE_TOPICS = ("state", "connection", "visualization", "factsheet")
ACTION_STATUS = ("WAITING", "INITIALIZING", "RUNNING", "PAUSED", "FINISHED", "FAILED")
INSTANT_ACTIONS = ("startPause", "stopPause", "cancelOrder", "stateRequest", "factsheetRequest")


def topic(serial: str, name: str, manufacturer: str = MANUFACTURER) -> str:
    return f"{INTERFACE}/{MAJOR}/{manufacturer}/{serial}/{name}"


def parse_topic(t: str) -> tuple[str, str, str] | None:
    """(manufacturer, serial number, topic) or None for a topic that is not VDA 5050."""
    parts = t.split("/")
    if len(parts) != 5 or parts[0] != INTERFACE or parts[1] != MAJOR:
        return None
    return parts[2], parts[3], parts[4]


def timestamp() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Headers:
    """headerId counts up per topic and sender, as the standard requires."""

    def __init__(self) -> None:
        self._ids: dict[str, int] = {}

    def __call__(self, serial: str, name: str) -> dict:
        key = f"{serial}/{name}"
        self._ids[key] = self._ids.get(key, -1) + 1
        return {
            "headerId": self._ids[key],
            "timestamp": timestamp(),
            "version": VERSION,
            "manufacturer": MANUFACTURER,
            "serialNumber": serial,
        }


def node(node_id: str, seq: int, x: float, y: float, released=True, actions=None) -> dict:
    return {
        "nodeId": node_id,
        "sequenceId": seq,  # nodes have even sequence ids, edges odd ones
        "released": released,
        "nodePosition": {"x": float(x), "y": float(y), "mapId": MAP_ID},
        "actions": actions or [],
    }


def edge(start: dict, end: dict, released=True) -> dict:
    return {
        "edgeId": f"{start['nodeId']}->{end['nodeId']}",
        "sequenceId": start["sequenceId"] + 1,
        "released": released,
        "startNodeId": start["nodeId"],
        "endNodeId": end["nodeId"],
        "actions": [],
    }


def action(action_type: str, action_id: str, blocking: str = "HARD", **params) -> dict:
    return {
        "actionType": action_type,
        "actionId": action_id,
        "blockingType": blocking,  # NONE | SOFT | HARD
        "actionParameters": [{"key": k, "value": v} for k, v in params.items()],
    }


def validate(name: str, msg: dict) -> list[str]:
    """The required fields of the messages used here (a subset of the JSON schemas)."""
    need = {
        "order": ["headerId", "orderId", "orderUpdateId", "nodes", "edges"],
        "instantActions": ["headerId", "actions"],
        "state": ["headerId", "orderId", "lastNodeId", "nodeStates", "edgeStates", "driving",
                  "actionStates", "batteryState", "operatingMode", "errors", "safetyState"],
        "connection": ["headerId", "connectionState"],
        "factsheet": ["headerId", "typeSpecification", "physicalParameters"],
    }.get(name, ["headerId"])  # fmt: skip
    problems = [f"missing {f}" for f in need if f not in msg]
    if name == "order":
        seqs = [n["sequenceId"] for n in msg.get("nodes", [])]
        if any(s % 2 for s in seqs):
            problems.append("node sequenceIds must be even")
        if len(msg.get("edges", [])) != max(0, len(seqs) - 1):
            problems.append("an order needs one edge between each pair of nodes")
    if name == "instantActions":
        for a in msg.get("actions", []):
            if not {"actionType", "actionId", "blockingType"} <= set(a):
                problems.append(f"incomplete action {a.get('actionId')}")
    return problems

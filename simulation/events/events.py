"""Simulation events (TRD 4.4). Every state change emits one."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum


class EventType(str, Enum):
    ORDER_CREATED = "ORDER_CREATED"
    ORDER_ASSIGNED = "ORDER_ASSIGNED"
    ROBOT_MOVED = "ROBOT_MOVED"
    ITEM_PICKED = "ITEM_PICKED"
    ORDER_DELIVERED = "ORDER_DELIVERED"
    COLLISION = "COLLISION"
    ROBOT_BLOCKED = "ROBOT_BLOCKED"
    BATTERY_LOW = "BATTERY_LOW"
    ROBOT_FAULT = "ROBOT_FAULT"
    FAULT_CLEARED = "FAULT_CLEARED"
    INVENTORY_RESTOCKED = "INVENTORY_RESTOCKED"
    COMMAND_REJECTED = "COMMAND_REJECTED"
    ROBOT_PAUSED = "ROBOT_PAUSED"
    ROBOT_RESUMED = "ROBOT_RESUMED"
    ROUTE_CHANGED = "ROUTE_CHANGED"
    AISLE_CLOSED = "AISLE_CLOSED"
    AISLE_OPENED = "AISLE_OPENED"
    HAZARD_DETECTED = "HAZARD_DETECTED"
    HAZARD_CLEARED = "HAZARD_CLEARED"


@dataclass
class Event:
    tick: int
    type: EventType
    entity_id: str | None = None
    payload: dict = field(default_factory=dict)
    is_injected_fault: bool = False

    def to_dict(self) -> dict:
        return {
            "tick": self.tick,
            "type": self.type.value,
            "entity_id": self.entity_id,
            "payload": self.payload,
            "is_injected_fault": self.is_injected_fault,
        }


class EventBus:
    """Collects events per tick and fans them out to subscribers (DB writer, WS stream)."""

    def __init__(self) -> None:
        self._subscribers: list[Callable[[Event], None]] = []
        self._external: set[int] = set()  # ids of handlers owned by services outside the engine
        self.buffer: list[Event] = []

    def subscribe(self, handler: Callable[[Event], None], external: bool = False) -> None:
        """`external`: the handler belongs to a service around the engine (copilot, live
        models). It is left out when the engine is saved; the service subscribes again when it
        attaches to the restored engine."""
        self._subscribers.append(handler)
        if external:
            self._external.add(id(handler))

    def __getstate__(self) -> dict:
        state = dict(self.__dict__)
        state["_subscribers"] = [h for h in self._subscribers if id(h) not in self._external]
        state["_external"] = set()
        return state

    def emit(self, event: Event) -> None:
        self.buffer.append(event)
        for handler in self._subscribers:
            handler(event)

    def drain(self) -> list[Event]:
        events, self.buffer = self.buffer, []
        return events

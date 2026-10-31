"""Platform events for other systems (backlog PR-15).

Each event is a CloudEvents 1.0 message (structured JSON), published to an MQTT-style topic
`warehouse/v1/{category}/{event}` (e.g. warehouse/v1/orders/shipped) on the message transport:
the MQTT broker when MQTT_URL is set, else the in-process bus. The last 2,000 events are kept for
replay (`after` a sequence number), and live HTTP subscribers (Server-Sent Events) get every new
event through their own bounded queue: a slow subscriber loses old events, never blocks the
platform.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from collections import deque

PREFIX = "warehouse/v1"
SOURCE = "/warehouse-ai/dc-1"
TYPE_PREFIX = "com.warehouseai"

# The event catalogue: topic suffix -> what it means. Order statuses and safety kinds add their
# own names under orders/ and safety/ (see `catalog()`).
CATALOG = {
    "robots/fault": "A robot stopped with a fault (data: fault type)",
    "robots/fault_cleared": "A robot's fault cleared",
    "robots/battery_low": "A robot's battery fell below the low threshold",
    "robots/paused": "A robot was paused (operator, copilot or VDA 5050 startPause)",
    "robots/resumed": "A paused robot was resumed",
    "robots/collision": "Two robots met in one cell (should never happen)",
    "orders/created": "A new order (source: generator, manual, ERP, backorder)",
    "orders/assigned": "An order was given to a robot",
    "orders/delivered_to_packing": "The robot dropped the order's tote at a packing station",
    "orders/{status}": "Outbound status: waiting_stock, ready, on_hold, released, picking, "
    "at_pack, packed, loaded, shipped, cancelled",
    "floor/aisle_closed": "An aisle was closed (maintenance, spill, operator)",
    "floor/aisle_opened": "A closed aisle reopened",
    "floor/hazard_detected": "A dropped parcel or fallen pallet blocks a cell",
    "floor/hazard_cleared": "A floor hazard was removed",
    "safety/{kind}": "Safety log: estop, estop_released, estop_reset, reset_confirmed, near_miss, "
    "robot_fault, settings ...",
    "alerts/{event}": "Alert centre incident: opened, acknowledged, escalated, resolved",
    "inventory/alert": "Warehouse message: short pick, damaged receipt, expiry, missed truck ...",
    "models/{event}": "Model operations: status_ok, status_warn, status_drift, retrain_started, "
    "candidate_rejected, candidate_ready, promoted, rolled_back, retrain_failed",
}


def now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class EventPublisher:
    def __init__(self, bus, keep: int = 2000) -> None:
        self.bus = bus
        self.recent: deque = deque(maxlen=keep)
        self.seq = 0
        self.subscribers: dict[asyncio.Queue, asyncio.AbstractEventLoop] = {}
        self.counts: dict[str, int] = {}

    def publish(self, topic: str, subject: str | None, data: dict, sim_tick: int) -> dict:
        """Wrap `data` as a CloudEvent and send it on `warehouse/v1/{topic}`."""
        self.seq += 1
        event = {
            "specversion": "1.0",
            "id": str(uuid.uuid4()),
            "source": SOURCE,
            "type": f"{TYPE_PREFIX}.{topic.replace('/', '.')}",
            "time": now(),
            "subject": subject,
            "datacontenttype": "application/json",
            "data": data,
            # extension attributes (lower-case letters only, per the spec)
            "sequence": self.seq,
            "simtick": sim_tick,
        }
        full = f"{PREFIX}/{topic}"
        self.bus.publish(full, event)
        self.recent.append({"topic": full, **event})
        self.counts[topic.split("/")[0]] = self.counts.get(topic.split("/")[0], 0) + 1
        for q, loop in list(self.subscribers.items()):
            # Queues belong to the loop of their HTTP stream; hand over thread-safely.
            loop.call_soon_threadsafe(_offer, q, (full, event))
        return event

    def replay(self, after: int = 0, prefix: str | None = None, limit: int = 200) -> list[dict]:
        rows = [
            e
            for e in self.recent
            if e["sequence"] > after and (not prefix or e["topic"].startswith(f"{PREFIX}/{prefix}"))
        ]
        return rows[-limit:]

    def subscribe(self) -> asyncio.Queue:
        """A queue for one live subscriber (call from its event loop)."""
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self.subscribers[q] = asyncio.get_running_loop()
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.subscribers.pop(q, None)


def _offer(q: asyncio.Queue, item) -> None:
    if q.full():  # a slow reader: drop its oldest event rather than wait
        q.get_nowait()
    q.put_nowait(item)


def catalog() -> list[dict]:
    return [
        {"topic": f"{PREFIX}/{t}", "type": f"{TYPE_PREFIX}.{t.replace('/', '.')}", "meaning": m}
        for t, m in CATALOG.items()
    ]

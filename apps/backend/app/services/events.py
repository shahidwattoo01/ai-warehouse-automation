"""Platform events on the message bus (backlog PR-15): what happens in the simulator, the WMS,
the safety layer and the alert centre, as CloudEvents for other systems."""

from __future__ import annotations

from app.core.config import get_settings
from integration.events.publisher import EventPublisher
from integration.vda5050.transport import InMemoryBus, MqttTransport
from simulation.events.events import EventType

ENGINE_EVENTS = {
    EventType.ROBOT_FAULT: "robots/fault",
    EventType.FAULT_CLEARED: "robots/fault_cleared",
    EventType.BATTERY_LOW: "robots/battery_low",
    EventType.ROBOT_PAUSED: "robots/paused",
    EventType.ROBOT_RESUMED: "robots/resumed",
    EventType.COLLISION: "robots/collision",
    EventType.ORDER_CREATED: "orders/created",
    EventType.ORDER_ASSIGNED: "orders/assigned",
    EventType.ORDER_DELIVERED: "orders/delivered_to_packing",
    EventType.AISLE_CLOSED: "floor/aisle_closed",
    EventType.AISLE_OPENED: "floor/aisle_opened",
    EventType.HAZARD_DETECTED: "floor/hazard_detected",
    EventType.HAZARD_CLEARED: "floor/hazard_cleared",
}


class EventService:
    def __init__(self) -> None:
        self.bus = None
        self.publisher: EventPublisher | None = None
        self.engine = None

    def attach(self, engine) -> None:
        s = get_settings()
        if self.bus is not None:
            self.bus.close()
        self.engine = engine
        if s.mqtt_url:
            self.bus = MqttTransport(s.mqtt_url, "warehouse-ai-events")
        else:
            self.bus = InMemoryBus()
        old = self.publisher
        self.publisher = EventPublisher(self.bus)
        if old is not None:  # live subscribers carry over to the new run
            self.publisher.subscribers = old.subscribers
        self._order_status: dict[str, str] = {}
        self._safety_seq = 0
        self._alert_seq = 0

    def after_tick(self, events: list, incidents: list) -> None:
        if self.publisher is None:
            return
        eng, pub = self.engine, self.publisher
        t = eng.time
        for e in events:
            topic = ENGINE_EVENTS.get(e.type)
            if topic:
                pub.publish(topic, e.entity_id, dict(e.payload), t)
        wms = getattr(eng.inventory, "wms", None)
        if wms is not None:
            seen = self._order_status
            for oid, rec in wms.out.orders.items():
                if seen.get(oid) != rec.status:
                    if oid in seen:  # a change (the creation is orders/created)
                        pub.publish(
                            f"orders/{rec.status.lower()}",
                            oid,
                            {"from": seen[oid], "to": rec.status, "customer_id": rec.customer_id,
                             "carrier": rec.carrier, "external_ref": rec.external_ref},
                            t,
                        )  # fmt: skip
                    seen[oid] = rec.status
            if len(seen) > len(wms.out.orders) + 500:
                self._order_status = {k: v for k, v in seen.items() if k in wms.out.orders}
            for a in reversed(wms.alerts):
                if a.get("seq", 0) > self._alert_seq:
                    self._alert_seq = a["seq"]
                    pub.publish(
                        "inventory/alert", a.get("ref"), {"level": a["level"], "text": a["text"]}, t
                    )
        for entry in reversed(eng.safety.log):
            if entry.get("seq", 0) > self._safety_seq:
                self._safety_seq = entry["seq"]
                data = {
                    k: entry[k] for k in ("severity", "text", "zone", "x", "y", "user", "detail")
                }
                pub.publish(f"safety/{entry['kind'].lower()}", entry.get("robot_id"), data, t)
        for inc in incidents:
            event = inc.history[-1]["event"].lower() if inc.history else "changed"
            pub.publish(
                f"alerts/{event}",
                inc.subject,
                {"alert_id": inc.alert_id, "rule": inc.rule, "severity": inc.severity,
                 "title": inc.title, "status": inc.status, "user": inc.history[-1]["user"]},
                t,
            )  # fmt: skip


events_service = EventService()

"""Live operational KPIs (project map §22-23): throughput, completion time, late rate, utilisation.

Listens to the event bus, so it sees every order the moment it is created or delivered, even
though the state only keeps the most recent finished orders.
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

from simulation.events.events import Event, EventType

if TYPE_CHECKING:
    from simulation.environment.engine import SimulationEngine

RECENT = 100  # average completion time over this many latest deliveries


class Kpis:
    def __init__(self, engine: SimulationEngine) -> None:
        self.engine = engine
        self.created = 0
        self.delivered = 0
        self.late = 0
        self._completion_ticks: deque[int] = deque(maxlen=RECENT)  # order created -> delivered
        self._delivery_ticks: deque[int] = deque()  # ticks of deliveries in the last simulated hour
        engine.events.subscribe(self._on_event)

    def _on_event(self, event: Event) -> None:
        if event.type == EventType.ORDER_CREATED:
            self.created += 1
        elif event.type == EventType.ORDER_DELIVERED:
            self.delivered += 1
            self.late += bool(event.payload.get("late"))
            self._completion_ticks.append(event.tick - event.payload["order_time"])
            self._delivery_ticks.append(event.tick)

    def snapshot(self) -> dict:
        eng = self.engine
        ticks_per_hour = eng.config.get("ticks_per_hour", 3600)
        while self._delivery_ticks and self._delivery_ticks[0] <= eng.time - ticks_per_hour:
            self._delivery_ticks.popleft()
        elapsed = min(eng.time, ticks_per_hour) or 1
        busy = sum(not eng.controller.available(r) for r in eng.robots.values())
        recent = self._completion_ticks
        return {
            "orders_created": self.created,
            "orders_completed": self.delivered,
            "late_percent": round(100 * self.late / self.delivered, 1) if self.delivered else 0.0,
            # Average over the latest deliveries, in ticks (order created -> delivered).
            "avg_completion_ticks": round(sum(recent) / len(recent), 1) if recent else None,
            # Deliveries in the last simulated hour (scaled up during the first hour).
            "throughput_per_hour": round(len(self._delivery_ticks) * ticks_per_hour / elapsed, 1),
            "utilisation_percent": round(100 * busy / len(eng.robots), 1) if eng.robots else 0.0,
        }

    def clock(self) -> dict:
        """Simulated wall clock: day, hour and minute from the tick count."""
        ticks_per_hour = self.engine.config.get("ticks_per_hour", 3600)
        hours = self.engine.time / ticks_per_hour
        return {
            "day": int(hours // 24) + 1,
            "hour": int(hours % 24),
            "minute": int((hours % 1) * 60),
            "seconds_per_tick": 3600 / ticks_per_hour,  # converts tick counts to simulated time
        }

"""Warehouse KPIs measured during one simulation run (project map §23, Phase 4 experiments).

Attach to an engine before it runs; it listens to the event bus and samples the state:

    avg_completion_ticks   order created -> delivered, averaged over delivered orders
    p90_completion_ticks   the same, 90th percentile (how bad the slow orders get)
    late_percent           delivered after the deadline
    throughput_per_hour    delivered orders per simulated hour
    avg_queue_ticks        order created -> assigned (time waiting for a robot)
    distance_m             metres driven by the whole fleet (1 move = 1 m)
    blocked_events         times a robot had to step aside to break a standoff
    route_changes          re-plans (traffic, closures, standoffs, dynamic replanning)
    avg_pending            orders waiting, sampled every 60 ticks
    utilisation_percent    robots busy (order or charging), sampled every 60 ticks
    charges                battery-low trips to a charger
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from simulation.events.events import Event, EventType
from simulation.warehouse.entities import OrderStatus

if TYPE_CHECKING:
    from simulation.environment.engine import SimulationEngine

SAMPLE_EVERY = 60


class RunMetrics:
    def __init__(self, engine: SimulationEngine) -> None:
        self.engine = engine
        self.created: dict[str, int] = {}
        self.assigned: dict[str, int] = {}
        self.completion: list[int] = []
        self.queue: list[int] = []
        self.late = 0
        self.moves = 0
        self.blocked = 0
        self.route_changes = 0
        self.charges = 0
        self.pending: list[int] = []
        self.busy: list[float] = []
        engine.events.subscribe(self._on_event)

    def _on_event(self, e: Event) -> None:
        t = e.type
        if t == EventType.ROBOT_MOVED:
            self.moves += 1
        elif t == EventType.ORDER_CREATED:
            self.created[e.entity_id] = e.tick
        elif t == EventType.ORDER_ASSIGNED:
            if e.entity_id in self.created:
                self.assigned[e.entity_id] = e.tick
                self.queue.append(e.tick - self.created[e.entity_id])
        elif t == EventType.ORDER_DELIVERED:
            self.completion.append(e.tick - e.payload["order_time"])
            self.late += bool(e.payload["late"])
        elif t == EventType.ROBOT_BLOCKED:
            self.blocked += 1
        elif t == EventType.ROUTE_CHANGED:
            self.route_changes += 1
        elif t == EventType.BATTERY_LOW:
            self.charges += 1

    def after_tick(self) -> None:
        eng = self.engine
        if eng.time % SAMPLE_EVERY:
            return
        self.pending.append(sum(o.status == OrderStatus.PENDING for o in eng.orders.values()))
        robots = list(eng.robots.values())
        self.busy.append(sum(not eng.controller.available(r) for r in robots) / len(robots))

    def summary(self) -> dict:
        eng = self.engine
        hours = eng.time / eng.config.get("ticks_per_hour", 600)
        done = len(self.completion)
        return {
            "orders_created": len(self.created),
            "orders_delivered": done,
            "avg_completion_ticks": round(float(np.mean(self.completion)), 2) if done else None,
            "p90_completion_ticks": round(float(np.percentile(self.completion, 90)), 1)
            if done
            else None,
            "late_percent": round(100 * self.late / done, 2) if done else None,
            "throughput_per_hour": round(done / hours, 2) if hours else None,
            "avg_queue_ticks": round(float(np.mean(self.queue)), 2) if self.queue else None,
            "distance_m": self.moves,
            "distance_per_order_m": round(self.moves / done, 1) if done else None,
            "blocked_events": self.blocked,
            "route_changes": self.route_changes,
            "charges": self.charges,
            "avg_pending": round(float(np.mean(self.pending)), 2) if self.pending else None,
            "utilisation_percent": round(100 * float(np.mean(self.busy)), 1) if self.busy else None,
        }

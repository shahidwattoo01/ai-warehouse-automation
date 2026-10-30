"""Dispatcher: decides which robot gets which order (TR-SIM-03; Phase 4 swaps in smarter policies).

Baseline policy: highest priority first, then oldest; each order goes to the nearest free robot
with at least the low-battery threshold of charge. In manual mode the dispatcher assigns nothing
and orders wait for an operator.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from simulation.events.events import Event, EventType
from simulation.robots.controller import manhattan
from simulation.warehouse.entities import OrderStatus, Priority

if TYPE_CHECKING:
    from simulation.environment.engine import SimulationEngine

PRIORITY_RANK = {Priority.HIGH: 0, Priority.MEDIUM: 1, Priority.LOW: 2}


class Dispatcher:
    def __init__(self, engine: SimulationEngine) -> None:
        self.engine = engine
        self.auto = engine.config["strategies"].get("auto_assign", True)
        # Phase 4 hooks (ai/optimization/optimizer.py). None = the built-in baseline behaviour.
        self.strategy = None  # AssignmentStrategy: which free robot takes which order
        self.top_up_threshold: float | None = None  # predictive charging override

    def step(self) -> None:
        eng = self.engine
        ctl = eng.controller
        low = eng.config["battery"]["low_threshold"]

        for robot in eng.robots.values():
            if ctl.available(robot) and robot.battery < low:
                ctl.send_to_charger(robot)

        waiting = sorted(
            (
                o
                for o in eng.orders.values()
                if o.status == OrderStatus.PENDING and eng.inventory.releasable(o.order_id)
            ),
            key=lambda o: (PRIORITY_RANK[o.priority], o.order_time),
        )
        closed = eng.layout.grid.closed
        if self.auto and self.strategy is not None:
            self._assign_with_strategy(waiting, low)
            waiting = []
        for order in waiting if self.auto else []:
            free = [r for r in eng.robots.values() if ctl.available(r) and r.battery >= low]
            if not free:
                break
            if closed and self.needs_closed_cell(order):
                continue  # a rack it needs is in a closed aisle: wait until it reopens
            first_rack = eng.inventory.face[order.items[0].product_id]
            ctl.start_order(order, min(free, key=lambda r: manhattan(r.position, first_rack)))

        # Opportunity charging: with no orders waiting, idle robots below the threshold top up,
        # so the robots standing in the parking row are the fully charged ones.
        if not any(o.status == OrderStatus.PENDING for o in eng.orders.values()):
            top_up = self.top_up_threshold
            if top_up is None:
                top_up = eng.config["battery"].get("opportunity_threshold", 0)
            for robot in sorted(eng.robots.values(), key=lambda r: r.battery):
                if (
                    ctl.available(robot)
                    and robot.battery < top_up
                    and not ctl.send_to_charger(robot, low=False)
                ):
                    break  # every charger bay is taken

    def _assign_with_strategy(self, waiting: list, low: float) -> None:
        """Let a Phase 4 strategy pair waiting orders with free robots."""
        eng = self.engine
        ctl = eng.controller
        free = [r for r in eng.robots.values() if ctl.available(r) and r.battery >= low]
        if not free:
            return
        closed = eng.layout.grid.closed
        orders = [o for o in waiting if not (closed and self.needs_closed_cell(o))]
        for order, robot in self.strategy.assign(orders, free):
            ctl.start_order(order, robot)

    def needs_closed_cell(self, order) -> bool:
        closed = self.engine.layout.grid.closed
        face = self.engine.inventory.face
        return any(face[i.product_id] in closed for i in order.items)

    def assign_manual(self, order_id: str, robot_id: str) -> None:
        """Operator assignment; rejected (with an event saying why) if it is no longer valid."""
        eng = self.engine
        order = eng.orders.get(order_id)
        robot = eng.robots.get(robot_id)
        if order is None or robot is None:
            reason = f"unknown order or robot ({order_id}, {robot_id})"
        elif order.status != OrderStatus.PENDING:
            reason = f"{order_id} is already {order.status.value.lower()}"
        elif self.needs_closed_cell(order):
            reason = f"{order_id} needs a rack in a closed aisle"
        elif not eng.inventory.releasable(order_id):
            reason = f"{order_id} is waiting for stock to be replenished"
        else:
            reason = eng.controller.unavailable_reason(robot)
        if reason:
            eng.events.emit(
                Event(eng.time, EventType.COMMAND_REJECTED, order_id, {"reason": reason})
            )
            return
        order.manual_assignment = True
        eng.controller.start_order(order, robot)

"""Dispatcher: decides which robot gets which order (TR-SIM-03; Phase 4 swaps in smarter policies).

Baseline policy: highest priority first, then oldest; each order goes to the nearest free robot
with at least the low-battery threshold of charge. In manual mode the dispatcher assigns nothing
and orders wait for an operator.

PR-03: when batch_picking.enabled, cluster nearby same-priority orders into one tote trip.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from simulation.events.events import Event, EventType
from simulation.robots.controller import manhattan
from simulation.warehouse.entities import Order, OrderStatus, Priority, RobotStatus

if TYPE_CHECKING:
    from simulation.environment.engine import SimulationEngine
    from simulation.warehouse.entities import Robot

PRIORITY_RANK = {Priority.HIGH: 0, Priority.MEDIUM: 1, Priority.LOW: 2}


class Dispatcher:
    def __init__(self, engine: SimulationEngine) -> None:
        self.engine = engine
        self.auto = engine.config["strategies"].get("auto_assign", True)
        # Phase 4 hooks (ai/optimization/optimizer.py). None = the built-in baseline behaviour.
        self.strategy = None  # AssignmentStrategy: which free robot takes which order
        self.top_up_threshold: float | None = None  # predictive charging override
        # Phase 9 — PR-03: batch picking config
        bp = engine.config.get("batch_picking", {})
        self._batch_enabled: bool = bp.get("enabled", False)
        self._tote_capacity: int = bp.get("tote_capacity", 3)
        self._cluster_radius: int = bp.get("cluster_radius", 8)

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

        if self._batch_enabled and self.auto:
            self._assign_batches(waiting, low, closed)
        else:
            for order in waiting if self.auto else []:
                free = [r for r in eng.robots.values() if ctl.can_take_order(r) and r.battery >= low]
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

    def _assign_batches(self, waiting: list[Order], low: float, closed: set) -> None:
        """Batch picking: cluster nearby same-priority orders into one tote trip (PR-03)."""
        eng = self.engine
        ctl = eng.controller
        assigned_ids: set[str] = set()

        for order in waiting:
            if order.order_id in assigned_ids:
                continue
            free = [r for r in eng.robots.values() if ctl.can_take_order(r) and r.battery >= low]
            if not free:
                break
            if closed and self.needs_closed_cell(order):
                continue

            first_rack = eng.inventory.face[order.items[0].product_id]
            robot = min(free, key=lambda r: manhattan(r.position, first_rack))

            # Gather nearby same-priority orders to fill the tote
            batch = self._cluster_for_robot(order, waiting, assigned_ids, closed)
            assigned_ids.update(o.order_id for o in batch)
            ctl.start_batch(batch, robot)

    def _cluster_for_robot(
        self,
        seed: Order,
        waiting: list[Order],
        already_assigned: set[str],
        closed: set,
    ) -> list[Order]:
        """Return up to tote_capacity orders clustered around `seed` (same priority, nearby racks)."""
        eng = self.engine
        seed_rack = eng.inventory.face[seed.items[0].product_id]
        batch: list[Order] = [seed]

        for candidate in waiting:
            if len(batch) >= self._tote_capacity:
                break
            if candidate.order_id == seed.order_id or candidate.order_id in already_assigned:
                continue
            if candidate.priority != seed.priority:
                continue  # don't mix priorities in one tote
            if closed and self.needs_closed_cell(candidate):
                continue
            cand_rack = eng.inventory.face[candidate.items[0].product_id]
            if manhattan(cand_rack, seed_rack) <= self._cluster_radius:
                batch.append(candidate)

        return batch

    def _assign_with_strategy(self, waiting: list, low: float) -> None:
        """Let a Phase 4 strategy pair waiting orders with free robots."""
        eng = self.engine
        ctl = eng.controller
        free = [r for r in eng.robots.values() if ctl.can_take_order(r) and r.battery >= low]
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

    def _release_from_stopped(self, order) -> str | None:
        """Take an order off a paused or faulted robot so another robot can carry it (SOP-03
        step 3: an urgent order cannot wait for the fault to clear). Only before any item is in
        that robot's tote: picked items are physically on it. None = released."""
        eng = self.engine
        holder = eng.robots.get(order.assigned_robot)
        task = eng.controller.tasks.get(order.assigned_robot)
        if holder is None or task is None or task.order_id != order.order_id:
            return f"{order.order_id} is already {order.status.value.lower()}"
        if holder.status not in (RobotStatus.PAUSED, RobotStatus.FAULT):
            return f"{order.order_id} is being carried by {holder.robot_id}"
        if len(task.stops) < len(order.items):
            return f"{holder.robot_id} already picked items of {order.order_id}"
        eng.controller.tasks.pop(holder.robot_id)
        holder.current_task, holder.route = None, []
        order.status, order.assigned_robot, order.destination = OrderStatus.PENDING, None, None
        return None

    def assign_manual(self, order_id: str, robot_id: str) -> None:
        """Operator assignment; rejected (with an event saying why) if it is no longer valid."""
        eng = self.engine
        order = eng.orders.get(order_id)
        robot = eng.robots.get(robot_id)
        if order is None or robot is None:
            reason = f"unknown order or robot ({order_id}, {robot_id})"
        elif order.status == OrderStatus.ASSIGNED and order.assigned_robot != robot_id:
            # SOP-03 step 3; the new robot is checked first, so a refusal releases nothing
            reason = eng.controller.unavailable_reason(robot) or self._release_from_stopped(order)
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

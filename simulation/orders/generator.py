"""Order generation: simulated customer demand plus operator-created orders (TR-SIM-03).

Arrivals are random each tick, scaled by the hour of the simulated day (configs/simulation.yaml
`orders.hourly_profile`), so there are quiet nights and busy peaks.
"""

from __future__ import annotations

import random

from simulation.inventory.inventory import Inventory
from simulation.warehouse.entities import Order, OrderItem, Priority

# Safety cap on the waiting queue (configs/simulation.yaml orders.max_pending). It must sit well
# above normal backlogs: while it is hit, customer demand is no longer recorded faithfully.
DEFAULT_MAX_PENDING = 150


class OrderGenerator:
    def __init__(self, config: dict, rng: random.Random) -> None:
        self.cfg = config["orders"]
        self.rng = rng
        self.max_pending: int = self.cfg.get("max_pending", DEFAULT_MAX_PENDING)
        self._seq = 0

    def next_id(self) -> str:
        self._seq += 1
        return f"O{self._seq:05d}"

    def _deadline(self, time: int, priority: Priority) -> int:
        return time + self.cfg["deadline_ticks"][priority.value]

    def customer_order(
        self, time: int, hour: int, inventory: Inventory, pending: int
    ) -> Order | None:
        """Maybe create one customer order this tick (None most ticks)."""
        profile = self.cfg.get("hourly_profile") or [1.0]
        busyness = profile[hour % len(profile)] / (sum(profile) / len(profile))
        if self.rng.random() > self.cfg.get("arrival_prob_per_tick", 0.0) * busyness:
            return None
        if pending >= self.max_pending:
            return None
        mix = self.cfg["priority_mix"]
        priority = Priority(self.rng.choices(list(mix), weights=list(mix.values()))[0])
        in_stock = inventory.in_stock()
        if not in_stock:
            return None
        lo, hi = self.cfg["items_per_order"]
        count = min(len(in_stock), self.rng.randint(lo, hi))
        products = self.rng.sample(in_stock, count)
        return Order(
            order_id=self.next_id(),
            items=[OrderItem(p, self.rng.randint(1, 3)) for p in products],
            priority=priority,
            order_time=time,
            deadline=self._deadline(time, priority),
        )

    def operator_order(
        self,
        order_id: str,
        time: int,
        priority: Priority,
        items: list[OrderItem],
        inventory: Inventory,
    ) -> Order:
        """An order created from the UI or API. With no (known) items, pick in-stock ones."""
        items = [i for i in items if i.product_id in inventory]
        if not items:
            in_stock = inventory.in_stock()
            picks = self.rng.sample(in_stock, min(2, len(in_stock)))
            items = [OrderItem(p, self.rng.randint(1, 3)) for p in picks]
        return Order(
            order_id=order_id,
            items=items,
            priority=priority,
            order_time=time,
            deadline=self._deadline(time, priority),
            source="MANUAL",
        )

"""The WMS (wms/) behind the simulator's inventory interface (`inventory_model: wms`).

The simulator, the API and the copilot keep using `face`, `catalog`, `stock`, `in_stock()` ...;
underneath, stock is allocated when an order is created, picked and shipped through the WMS
ledger, and replenished by associates from reserve stock and supplier deliveries.
"""

from __future__ import annotations

import random

from simulation.inventory.inventory import Inventory as SimpleInventory
from simulation.warehouse.layout import Layout
from wms.warehouse import Warehouse


class WmsStock:
    model = "wms"

    def __init__(
        self,
        layout: Layout,
        seed: int,
        ticks_per_hour: int,
        config: dict | None = None,
        orders: dict | None = None,
    ) -> None:
        # The bay geometry and catalogue come from the simple model (same layout rules); its
        # random opening stock is discarded. The WMS has its own random stream.
        base = SimpleInventory(layout, random.Random(f"{seed}:wms-geometry"))
        self.face = base.face
        self.catalog = base.catalog
        config = dict(config or {})
        if orders and "expected_units_per_hour" not in config:
            # Demand prior from the order settings: orders/hour x lines per order x ~2 units.
            per_hour = orders.get("arrival_prob_per_tick", 0.14) * ticks_per_hour
            per_hour *= sum(orders.get("hourly_profile", [1.0])) / len(
                orders.get("hourly_profile", [1.0])
            )
            config["expected_units_per_hour"] = (
                per_hour * sum(orders.get("items_per_order", [1, 2])) / 2 * 2
            )
        self.wms = Warehouse(
            layout,
            self.catalog,
            self.face,
            random.Random(f"{seed}:wms"),
            ticks_per_hour,
            config,
            outbound_rng=random.Random(f"{seed}:outbound"),
        )
        self.weights = self.wms.popularity  # order generator: popular items are ordered more

    # ----- the interface of simulation/inventory/inventory.py --------------------------------
    def __contains__(self, product_id: str) -> bool:
        return product_id in self.face

    @property
    def stock(self) -> dict[str, int]:
        """Available to promise per product (what can still be ordered)."""
        return {sku: max(0, self.wms.atp(sku)) for sku in sorted(self.face)}

    def stock_of(self, product_id: str) -> int:
        """One product's available to promise (`stock` computes every product: use this for one)."""
        return max(0, self.wms.atp(product_id))

    def in_stock(self, min_units: int = 3) -> list[str]:
        """Products that can take an order line (up to 3 units), in a stable order."""
        return [s for s in sorted(self.face) if self.wms.atp(s) >= min_units]

    def restocking(self, product_id: str) -> bool:
        return bool(self.wms._open_task("REPLENISH", sku=product_id)) or any(
            ln.sku == product_id
            for po in self.wms.pos.values()
            if po.status != "CLOSED"
            for ln in po.lines
        )

    def step(self, time: int, on_restock) -> None:
        self.wms.step(time)

    @staticmethod
    def location(product_id: str) -> str:
        return product_id.removeprefix("P-")

    # ----- order hooks (the simple model ignores these) ----------------------------------------
    def order_created(self, order) -> None:
        self.wms.allocate_order(order)

    def releasable(self, order_id: str) -> bool:
        return self.wms.releasable(order_id)

    def picked(self, order, line: int, robot_id: str) -> tuple[int, int]:
        return self.wms.pick_line(order.order_id, line, robot_id)

    def shipped(self, order, robot_id: str, station: str) -> None:
        """The robot reached its packing station (the order ships later, on a truck)."""
        self.wms.deliver_to_pack(order.order_id, robot_id, station)

    def take_new_orders(self) -> list[dict]:
        """Follow-up orders for backorders whose stock has arrived."""
        return self.wms.out.take_new_orders()

    def cancelled(self, order_id: str) -> None:
        self.wms.cancel_order(order_id)

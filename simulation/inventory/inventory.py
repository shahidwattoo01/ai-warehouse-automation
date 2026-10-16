"""Stock per product and its replenishment (TR-SIM-05).

One product (SKU) per rack bay, named after its rack location: shelf SH-A-05-12 holds product
P-A-05-12. Robots pick from the walkable aisle cell beside the bay (the pick face).
"""

from __future__ import annotations

import random
from collections.abc import Callable

from simulation.inventory.catalog import Product, build_catalog
from simulation.warehouse.layout import Layout

Cell = tuple[int, int]

REORDER_POINT = 10  # restock a bay when its stock falls below this
RESTOCK_LEAD_TICKS = (300, 900)  # replenishment arrives this long after the reorder
RESTOCK_UNITS = (60, 120)


class Inventory:
    def __init__(self, layout: Layout, rng: random.Random) -> None:
        self.rng = rng
        self.face: dict[str, Cell] = {}  # product_id -> pick face cell
        self.stock: dict[str, int] = {}
        self._restock_due: dict[str, int] = {}  # product_id -> tick the replenishment lands
        self.catalog: dict[str, Product] = build_catalog(layout)  # name, category, weight

        grid = layout.grid
        for shelf in layout.shelves:
            face = next(
                (
                    (shelf.x, shelf.y + dy)
                    for dy in (1, -1)
                    if grid.is_walkable(shelf.x, shelf.y + dy)
                ),
                None,
            )
            if face:
                product_id = f"P-{shelf.shelf_id[3:]}"
                self.face[product_id] = face
                self.stock[product_id] = rng.randint(20, 120)

    def __contains__(self, product_id: str) -> bool:
        return product_id in self.face

    def in_stock(self) -> list[str]:
        """Products with stock, in a stable order (sorted) so random picks are reproducible."""
        return sorted(p for p in self.face if self.stock[p] > 0)

    def restocking(self, product_id: str) -> bool:
        """A replenishment for this bay is on its way."""
        return product_id in self._restock_due

    def take(self, product_id: str, quantity: int) -> None:
        self.stock[product_id] = max(0, self.stock[product_id] - quantity)

    def step(self, time: int, on_restock: Callable[[str, int], None]) -> None:
        """Reorder low bays and land replenishments that are due."""
        for product_id, stock in self.stock.items():
            if stock < REORDER_POINT and product_id not in self._restock_due:
                self._restock_due[product_id] = time + self.rng.randint(*RESTOCK_LEAD_TICKS)
        for product_id, due in list(self._restock_due.items()):
            if time >= due:
                added = self.rng.randint(*RESTOCK_UNITS)
                self.stock[product_id] += added
                del self._restock_due[product_id]
                on_restock(product_id, added)

    @staticmethod
    def location(product_id: str) -> str:
        """Rack location label, e.g. "A-05-12" (zone A, row y=5, bay x=12)."""
        return product_id.removeprefix("P-")

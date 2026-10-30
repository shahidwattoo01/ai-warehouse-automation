"""Master data for the simulated site: item master, suppliers and the location master.

Locations follow the racking: every bay has 4 levels. Level 1 is the item's **pick face**
(robots pick there); levels 2-4 are **reserve** positions, each holding one license plate (a
stack of cases of any item). Six dock doors on the north wall receive trucks, with a staging lane
behind each; a quarantine area and a returns area sit by the docks; the packing stations are the
shipping points.

Everything is derived from stable checksums of the ids (never from the simulation's random
stream), so building the master data does not change any simulation run.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass

from simulation.inventory.catalog import Product
from wms.barcodes import gtin13, gtin14
from wms.model import Item, Location, LocationType


def _c(text: str) -> int:
    return zlib.crc32(text.encode())


def _between(text: str, lo: float, hi: float) -> float:
    return lo + (_c(text) % 10_000) / 9_999 * (hi - lo)


@dataclass(frozen=True)
class Supplier:
    supplier_id: str
    name: str
    category: str
    lead_time_hours: tuple[int, int]  # order to truck at the dock (simulated hours)

    def to_dict(self) -> dict:
        return {**self.__dict__, "lead_time_hours": list(self.lead_time_hours)}


# category -> (supplier name, unit cost range $, units per case range, shelf life days or None,
#              serial numbers above this unit cost or None)
CATEGORY_RULES: dict[
    str, tuple[str, tuple[float, float], tuple[int, int], tuple[int, int] | None, float | None]
] = {
    "Electronics": ("Volta Electronics Supply", (8, 160), (4, 12), None, 60.0),
    "Home & Kitchen": ("Hearth & Home Wholesale", (4, 60), (4, 12), None, None),
    "Apparel": ("Threadline Apparel", (3, 45), (10, 24), None, None),
    "Toys & Games": ("Playwise Distribution", (4, 50), (6, 12), None, None),
    "Books & Media": ("Pageturn Books", (2, 30), (10, 20), None, None),
    "Sports & Outdoors": ("Summit Sports Trade", (5, 90), (2, 8), None, None),
    "Beauty & Health": ("Bloom Health & Beauty", (2, 35), (12, 24), (180, 540), None),
    "Grocery": ("Harvest Foods", (1, 15), (12, 24), (45, 180), None),
    "Office Supplies": ("Deskline Office", (1, 40), (10, 20), None, None),
    "Tools & DIY": ("Forge Tools", (4, 120), (2, 6), None, None),
}


def suppliers() -> dict[str, Supplier]:
    out = {}
    for i, (category, (name, *_)) in enumerate(CATEGORY_RULES.items(), start=1):
        sid = f"SUP-{i:02d}"
        lead = (3 + _c(sid) % 3, 6 + _c(sid) % 5)  # 3-5 to 6-10 hours
        out[sid] = Supplier(sid, name, category, lead)
    return out


def build_items(
    products: dict[str, Product], shelf_cells: dict[str, tuple[int, int]]
) -> list[Item]:
    by_category = {s.category: s.supplier_id for s in suppliers().values()}
    items = []
    for ref, product in enumerate(sorted(products.values(), key=lambda p: p.product_id), start=1):
        _, cost_range, case_range, shelf_life, serial_above = CATEGORY_RULES[product.category]
        pid = product.product_id
        cost = round(_between(pid + "cost", *cost_range), 2)
        case_qty = int(round(_between(pid + "case", *case_range)))
        pick_max = case_qty * 3  # a pick face holds about three cases
        unit = gtin13(ref)
        items.append(
            Item(
                sku=pid,
                gtin=unit,
                case_gtin=gtin14(unit),
                name=product.name,
                category=product.category,
                supplier_id=by_category[product.category],
                unit_cost=cost,
                weight_kg=product.weight_kg,
                case_qty=case_qty,
                pallet_cases=4 + _c(pid + "lpn") % 5,  # 4-8 cases per reserve license plate
                home=f"{product.location}-1",
                pick_min=max(2, case_qty),  # replenish when less than a case is left
                pick_max=pick_max,
                lot_controlled=True,
                shelf_life_days=int(_between(pid + "life", *shelf_life)) if shelf_life else None,
                serial_controlled=serial_above is not None and cost >= serial_above,
            )
        )
    return items


def build_locations(
    layout, inventory_faces: dict[str, tuple[int, int]], items: list[Item]
) -> list[Location]:
    """inventory_faces: product id -> the aisle cell beside its bay (simulation/inventory)."""
    out: list[Location] = []
    home_of = {i.sku: i for i in items}
    for shelf in layout.shelves:
        location = shelf.shelf_id.removeprefix("SH-")
        sku = f"P-{location}"
        if sku not in inventory_faces:
            continue
        fx, fy = inventory_faces[sku]
        zone = shelf.zone_id.removeprefix("ZONE_")
        for level in range(1, shelf.levels + 1):
            code = f"{location}-{level}"
            if level == 1:
                out.append(
                    Location(
                        code,
                        LocationType.PICK,
                        zone,
                        fx,
                        fy,
                        level,
                        capacity=home_of[sku].pick_max,
                        sku=sku,
                        check=f"{_c(code) % 100:02d}",
                    )
                )
            else:
                out.append(
                    Location(
                        code,
                        LocationType.RESERVE,
                        zone,
                        fx,
                        fy,
                        level,
                        capacity=1,
                        check=f"{_c(code) % 100:02d}",
                    )
                )
    width = layout.grid.width
    doors = [round(width * (i + 0.5) / 6) for i in range(6)]
    for i, x in enumerate(doors, start=1):
        out.append(
            Location(
                f"DOCK-{i:02d}", LocationType.DOCK, None, x, 0, check=f"{_c(f'D{i}') % 100:02d}"
            )
        )
        out.append(
            Location(
                f"STAGE-{i:02d}", LocationType.STAGING, None, x, 2, check=f"{_c(f'S{i}') % 100:02d}"
            )
        )
    out.append(Location("QA-01", LocationType.QUARANTINE, None, 1, 2, check="17"))
    out.append(Location("RET-01", LocationType.RETURNS, None, width - 2, 2, check="42"))
    for station in layout.stations:
        if station.type == "PACKING":
            out.append(
                Location(
                    station.station_id, LocationType.PACK, None, station.x, station.y, check="00"
                )
            )
    return out

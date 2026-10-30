"""Master data for the simulated site: item master, suppliers and the location master.

Locations follow the racking: every bay has 4 levels. Level 1 is the item's **pick face**
(robots pick there); levels 2-4 are **reserve** positions, each holding one license plate (a
stack of cases of any item). Six dock doors on the north wall receive trucks, with a staging lane
behind each; a quarantine area and a returns area sit by the docks. Outbound runs along the south
wall: the packing stations, one sort lane per carrier and three shipping doors with trailers.

Customers and carriers are fictitious (any likeness to a real business is a coincidence).

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


# Packed litres per kg of product: light bulky goods (apparel, toys) need bigger cartons.
LITRES_PER_KG = {
    "Electronics": 2.5,
    "Home & Kitchen": 2.0,
    "Apparel": 6.0,
    "Toys & Games": 4.0,
    "Books & Media": 1.4,
    "Sports & Outdoors": 2.5,
    "Beauty & Health": 1.5,
    "Grocery": 1.2,
    "Office Supplies": 1.6,
    "Tools & DIY": 0.9,
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
                volume_l=round(
                    max(0.2, product.weight_kg * LITRES_PER_KG[product.category])
                    * _between(pid + "vol", 0.8, 1.25),
                    2,
                ),
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
    packing = [s for s in layout.stations if s.type == "PACKING"]
    for station in packing:
        out.append(
            Location(station.station_id, LocationType.PACK, None, station.x, station.y, check="00")
        )
    south = max((s.y for s in packing), default=layout.grid.height - 1)
    for i, carrier in enumerate(carriers().values()):
        x = round(width * (i + 0.5) / 3)
        lane = f"LANE-{carrier.code}"
        out.append(Location(lane, LocationType.LANE, None, x, south, check=f"{_c(lane) % 100:02d}"))
        out.append(
            Location(
                carrier.door,
                LocationType.SHIP_DOCK,
                None,
                x,
                south,
                check=f"{_c(carrier.door) % 100:02d}",
            )
        )
    return out


# ----- outbound master data ---------------------------------------------------------------------
@dataclass(frozen=True)
class Carrier:
    code: str  # EXP | STD | ECO
    name: str
    service: str
    door: str  # shipping door where its trailer is loaded
    departures: tuple[int, ...]  # hours of the day the truck leaves
    tracking_prefix: str

    def to_dict(self) -> dict:
        return {**self.__dict__, "departures": list(self.departures)}


def carriers() -> dict[str, Carrier]:
    """Three services, chosen by order priority: HIGH -> express, MEDIUM -> standard, LOW ->
    economy. Each truck leaves at a fixed hour; the cut-off is some minutes before."""
    return {
        c.code: c
        for c in (
            Carrier("EXP", "Swiftline Couriers", "Express", "SHIP-01", (7, 12, 17, 22), "SWX"),
            Carrier("STD", "RoadLink Parcel", "Standard", "SHIP-02", (9, 15, 21), "RLP"),
            Carrier("ECO", "Freightway Cargo", "Economy", "SHIP-03", (6, 18), "FWC"),
        )
    }


@dataclass(frozen=True)
class Customer:
    customer_id: str
    name: str
    kind: str  # B2C marketplace seller / B2B retailer
    address: str
    city: str
    postal_code: str
    allow_partial: bool  # accepts a partial shipment with the rest on backorder

    def to_dict(self) -> dict:
        return dict(self.__dict__)


CITIES = [
    ("Lahore", "54000"),
    ("Karachi", "74200"),
    ("Islamabad", "44000"),
    ("Rawalpindi", "46000"),
    ("Faisalabad", "38000"),
    ("Multan", "60000"),
    ("Peshawar", "25000"),
    ("Gujranwala", "52250"),
    ("Sialkot", "51310"),
    ("Hyderabad", "71000"),
    ("Quetta", "87300"),
    ("Bahawalpur", "63100"),
]
_NAME_A = ["Northgate", "Riverbend", "Bluepeak", "Greenfield", "Starling", "Cedar", "Brightway",
           "Oakridge", "Silverline", "Harbor", "Meadow", "Summit"]  # fmt: skip
_NAME_B = ["Retail", "Mart", "Online", "Stores", "Traders", "Outlet"]


def customers(count: int = 60) -> dict[str, Customer]:
    out = {}
    for i in range(1, count + 1):
        cid = f"C-{i:04d}"
        city, postal = CITIES[_c(cid + "city") % len(CITIES)]
        name = f"{_NAME_A[_c(cid + 'a') % len(_NAME_A)]} {_NAME_B[_c(cid + 'b') % len(_NAME_B)]}"
        out[cid] = Customer(
            cid,
            f"{name} {i:02d}",
            "B2B" if _c(cid + "kind") % 4 == 0 else "B2C",
            f"Plot {1 + _c(cid + 'plot') % 240}, Block {chr(65 + _c(cid + 'blk') % 8)}",
            city,
            postal,
            allow_partial=_c(cid + "partial") % 10 < 7,  # 70 % accept partial shipments
        )
    return out

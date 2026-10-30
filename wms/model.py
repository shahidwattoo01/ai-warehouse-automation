"""WMS records: items, locations, lots, license plates, stock rows, transactions, allocations."""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field
from enum import Enum


class LocationType(str, Enum):
    PICK = "PICK"  # rack level 1: the item's home pick face, picked by robots
    RESERVE = "RESERVE"  # rack levels 3-4: one pallet / case stack (LPN) of any item
    DOCK = "DOCK"  # dock door on the north wall: trucks unload here
    STAGING = "STAGING"  # received goods waiting for putaway
    QUARANTINE = "QUARANTINE"  # damaged or doubtful goods waiting for a decision
    RETURNS = "RETURNS"  # customer returns waiting for inspection
    PACK = "PACK"  # packing station: picked goods leave the stock here (shipped)
    ROBOT = "ROBOT"  # on a robot between pick and pack


STORAGE = (LocationType.PICK, LocationType.RESERVE)


class StockStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    QC_HOLD = "QC_HOLD"  # quality check / quarantine
    DAMAGED = "DAMAGED"
    EXPIRED = "EXPIRED"
    HOLD = "HOLD"  # blocked for a count investigation or by an operator


class TxnType(str, Enum):
    RECEIVE = "RECEIVE"
    PUTAWAY = "PUTAWAY"
    MOVE = "MOVE"
    REPLENISH = "REPLENISH"
    ALLOCATE = "ALLOCATE"
    DEALLOCATE = "DEALLOCATE"
    PICK = "PICK"
    SHORT_PICK = "SHORT_PICK"
    SHIP = "SHIP"
    ADJUST = "ADJUST"
    COUNT = "COUNT"
    STATUS = "STATUS"  # hold / release / quarantine / expire
    RETURN = "RETURN"
    SCRAP = "SCRAP"


# Reason codes required on every adjustment (stock changed without a normal movement).
REASONS = {
    "COUNT_VARIANCE": "difference found by a cycle count",
    "DAMAGED": "damaged in the warehouse",
    "FOUND": "stock found that the system did not know",
    "LOST": "stock missing, not found after search",
    "EXPIRED": "past its expiry date",
    "QUALITY": "failed quality inspection",
    "DATA_ERROR": "correction of a booking mistake",
    "RETURN_RESTOCK": "customer return put back to stock",
    "RETURN_SCRAP": "customer return not resaleable",
}


@dataclass
class Item:
    sku: str  # P-A-05-12 (named after its home bay)
    gtin: str  # GTIN-13 of one unit (EAN-13 barcode)
    case_gtin: str  # GTIN-14 of a case
    name: str
    category: str
    supplier_id: str
    unit_cost: float  # purchase price per unit (inventory value)
    weight_kg: float
    case_qty: int  # units per case
    pallet_cases: int  # cases per pallet / reserve LPN
    home: str  # pick face location code
    pick_min: int  # replenish the pick face below this
    pick_max: int  # ... up to this (pick face capacity)
    lot_controlled: bool = True
    shelf_life_days: int | None = None  # set: expiry-controlled, picked FEFO
    serial_controlled: bool = False
    abc: str = "C"  # A / B / C by recent pick volume
    uom: str = "EA"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Location:
    code: str  # A-05-12-1 (zone A, row 5, bay 12, level 1), DOCK-01, STAGE-01 ...
    type: LocationType
    zone: str | None
    x: int  # floor cell the location is reached from
    y: int
    level: int = 0
    capacity: int | None = None  # units (PICK) or LPNs (RESERVE); None = unlimited
    sku: str | None = None  # fixed item of a pick face
    blocked: bool = False  # blocked for a count or investigation: no picks, no putaway
    check: str = "00"  # two check digits a picker reads out (voice picking) to confirm

    def to_dict(self) -> dict:
        d = asdict(self)
        d["type"] = self.type.value
        return d


@dataclass
class Lot:
    sku: str
    lot: str
    expiry: dt.date | None
    received_tick: int

    def to_dict(self) -> dict:
        return {**asdict(self), "expiry": self.expiry.isoformat() if self.expiry else None}


@dataclass(frozen=True)
class StockKey:
    sku: str
    location: str
    lot: str
    status: StockStatus = StockStatus.AVAILABLE
    lpn: str | None = None  # SSCC of the pallet / case stack it is on (reserve, staging)


@dataclass
class Txn:
    """One line of the inventory ledger. Never edited or deleted: corrections are new lines."""

    txn_id: int
    tick: int
    type: TxnType
    sku: str
    qty: int
    from_loc: str | None = None
    to_loc: str | None = None
    lot: str | None = None
    lpn: str | None = None
    status: str | None = None
    reason: str | None = None
    ref: str | None = None  # order, purchase order, count or task id
    user: str = "system"
    serials: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["type"] = self.type.value
        return d


@dataclass
class Allocation:
    order_id: str
    line: int
    sku: str
    location: str
    lot: str
    qty: int
    picked: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

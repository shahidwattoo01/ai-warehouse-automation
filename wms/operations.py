"""Work records of the WMS: tasks for associates, purchase orders with their advance shipping
notices (ASN), cycle counts and customer returns."""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field

# Lower number = done first. An empty pick face with orders waiting beats everything.
TASK_PRIORITY = {
    "REPLENISH_URGENT": 0,
    "RECEIVE": 1,
    "PUTAWAY": 2,
    "REPLENISH": 3,
    "RETURN": 4,
    "QUARANTINE": 5,
    "COUNT": 6,
    # outbound crews (separate people, so these never delay inbound work)
    "PUTBACK": 0,
    "AUDIT": 1,
    "PACK": 2,
    "LOAD": 3,
}
TASK_CREW = {"PACK": "pack", "AUDIT": "pack", "LOAD": "dock", "PUTBACK": "dock"}  # else inbound


@dataclass
class Task:
    task_id: str
    type: str  # RECEIVE | PUTAWAY | REPLENISH(_URGENT) | COUNT | RETURN | QUARANTINE |
    #            PACK | AUDIT | LOAD | PUTBACK
    created: int
    data: dict
    status: str = "OPEN"  # OPEN | IN_PROGRESS | DONE | CANCELLED
    assignee: str | None = None
    started: int | None = None
    done_at: int | None = None
    result: str | None = None

    @property
    def priority(self) -> int:
        return TASK_PRIORITY[self.type]

    def to_dict(self) -> dict:
        return {**asdict(self), "priority": self.priority}


@dataclass
class POLine:
    sku: str
    qty: int  # units ordered (whole cases)
    received: int = 0
    damaged: int = 0


@dataclass
class PurchaseOrder:
    po_id: str
    supplier_id: str
    created: int
    eta: int  # tick the truck is expected at the dock
    lines: list[POLine]
    status: str = "OPEN"  # OPEN | IN_TRANSIT | AT_DOCK | RECEIVING | CLOSED
    dock: str | None = None
    arrived: int | None = None
    closed: int | None = None
    asn: list[dict] = field(default_factory=list)  # license plates on the truck

    def to_dict(self) -> dict:
        d = asdict(self)
        for lpn in d["asn"]:
            if isinstance(lpn.get("expiry"), dt.date):
                lpn["expiry"] = lpn["expiry"].isoformat()
        return d


@dataclass
class Count:
    count_id: str
    location: str
    sku: str
    reason: str  # CYCLE | SHORT_PICK | RECOUNT | MANUAL
    created: int
    status: str = "OPEN"  # OPEN | COUNTED | PENDING_APPROVAL | ADJUSTED | MATCHED | REJECTED
    expected: int | None = None  # system quantity when counted (hidden from the counter)
    counted: int | None = None
    variance: int | None = None
    counter: str | None = None
    recount_of: str | None = None
    value: float | None = None  # variance x unit cost
    decided_by: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Return:
    rma_id: str
    order_id: str
    sku: str
    qty: int
    due: int  # tick the parcel reaches the returns area
    reason: str
    status: str = "EXPECTED"  # EXPECTED | RECEIVED | RESTOCKED | SCRAPPED
    lot: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

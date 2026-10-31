"""Warehouse management endpoints: inventory, scanning, receiving, putaway, moves, adjustments,
holds, cycle counts, purchase orders, tasks, labels, and outbound (customer orders, waves,
packing, loading, carrier departures, backorders).

Every change is booked in the inventory ledger under the logged-in user (from the access token,
never from the request body). Endpoints run on the event loop between simulator ticks, so the
WMS is never changed by two requests at once.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from app.core.auth import Principal, need, require
from app.services import printers
from app.services.simulator import simulator
from wms import barcodes as bc
from wms import exports, labels, zpl
from wms.inventory import InventoryError
from wms.model import REASONS, LocationType, StockStatus
from wms.outbound import FINAL, OutboundError

router = APIRouter(prefix="/wms", tags=["wms"])


def _wms():
    wms = getattr(simulator.engine.inventory, "wms", None)
    if wms is None:
        raise HTTPException(
            409, detail={"code": "wms_off", "message": "Set INVENTORY_MODEL=wms to use the WMS"}
        )
    return wms


def _bad(err: Exception) -> HTTPException:
    return HTTPException(422, detail={"code": "rejected", "message": str(err)})


def _item_row(wms, sku: str) -> dict:
    item = wms.inv.items[sku]
    s = wms.inv.summary(sku)
    on_order = sum(
        ln.qty - ln.received
        for po in wms.pos.values()
        if po.status != "CLOSED"
        for ln in po.lines
        if ln.sku == sku
    )
    return {
        "sku": sku,
        "name": item.name,
        "category": item.category,
        "gtin": item.gtin,
        "abc": item.abc,
        "home": item.home,
        "unit_cost": item.unit_cost,
        "pick_min": item.pick_min,
        "pick_max": item.pick_max,
        "on_order": on_order,
        "expiry_controlled": item.shelf_life_days is not None,
        "serial_controlled": item.serial_controlled,
        **{k: v for k, v in s.items() if k != "by_status"},
        "on_hold": s["on_hand"] - s["available"],
    }


def _rows(wms, **filters) -> list[dict]:
    out = []
    for key, qty in wms.inv.rows(**filters):
        lot = wms.inv.lots.get((key.sku, key.lot))
        out.append(
            {
                "sku": key.sku,
                "location": key.location,
                "lot": key.lot,
                "expiry": lot.expiry.isoformat() if lot and lot.expiry else None,
                "status": key.status.value,
                "lpn": key.lpn,
                "qty": qty,
                "allocated": wms.inv._allocated.get((key.sku, key.location, key.lot), 0)
                if key.lpn is None and key.status == StockStatus.AVAILABLE
                else 0,
            }
        )
    return out


# ----- overview ----------------------------------------------------------------------------------
@router.get("/kpis", dependencies=[need("wms:view")])
async def kpis() -> dict:
    wms = _wms()
    return {**wms.kpis(), "date": wms.inv.date().isoformat(), "tick": wms.inv.tick}


@router.get("/alerts", dependencies=[need("wms:view")])
async def alerts(limit: int = Query(50, le=200)) -> list[dict]:
    return list(_wms().alerts)[:limit]


@router.get("/reasons", dependencies=[need("wms:view")])
async def reasons() -> dict:
    return REASONS


# ----- items, locations, stock, ledger --------------------------------------------------------
@router.get("/items", dependencies=[need("wms:view")])
async def items(
    q: str = "",
    category: str | None = None,
    abc: Literal["A", "B", "C"] | None = None,
    filter: Literal["all", "low", "out", "hold", "expiring"] = "all",
    limit: int = Query(100, le=500),
    offset: int = 0,
) -> dict:
    wms = _wms()
    rows = []
    soon = wms.inv.date() + dt.timedelta(days=wms.cfg["near_expiry_days"])
    for sku in sorted(wms.inv.items):
        item = wms.inv.items[sku]
        text = f"{sku} {item.name} {item.gtin}".lower()
        if (
            q
            and q.lower() not in text
            or category
            and item.category != category
            or abc
            and item.abc != abc
        ):
            continue
        row = _item_row(wms, sku)
        if filter == "low" and row["pick_face"] >= item.pick_min:
            continue
        if filter == "out" and row["atp"] > 0:
            continue
        if filter == "hold" and row["on_hold"] == 0:
            continue
        if filter == "expiring" and not any(
            lot.expiry
            and lot.expiry <= soon
            and any(True for _ in wms.inv.rows(sku=sku, lot=lot.lot))
            for (s, _), lot in wms.inv.lots.items()
            if s == sku
        ):
            continue
        rows.append(row)
    return {"total": len(rows), "items": rows[offset : offset + limit]}


@router.get("/items/{sku}", dependencies=[need("wms:view")])
async def item(sku: str) -> dict:
    wms = _wms()
    if sku not in wms.inv.items:
        raise HTTPException(404, detail=f"No item {sku}")
    it = wms.inv.items[sku]
    rop, up_to = wms.reorder_point(sku)
    serials = [
        s for s, v in wms.inv.serials.items() if v["sku"] == sku and v["state"] == "IN_STOCK"
    ]
    return {
        **_item_row(wms, sku),
        "item": it.to_dict(),
        "supplier": wms.suppliers[it.supplier_id].to_dict(),
        "demand_per_hour": round(wms.demand[sku], 2),
        "reorder_point": round(rop, 1),
        "order_up_to": round(up_to, 1),
        "stock": _rows(wms, sku=sku),
        "allocations": [
            a.to_dict() for lines in wms.inv.allocations.values() for a in lines if a.sku == sku
        ],
        "purchase_orders": [
            {
                "po_id": po.po_id,
                "status": po.status,
                "eta": po.eta,
                "qty": ln.qty,
                "received": ln.received,
            }
            for po in wms.pos.values()
            for ln in po.lines
            if ln.sku == sku and po.status != "CLOSED"
        ],
        "serials_in_stock": len(serials),
        "serial_sample": sorted(serials)[:10],
        "transactions": [t.to_dict() for t in wms.inv.ledger if t.sku == sku][-50:][::-1],
    }


@router.get("/locations", dependencies=[need("wms:view")])
async def locations(
    type: LocationType | None = None,
    zone: str | None = None,
    q: str = "",
    occupied: bool | None = None,
    limit: int = Query(200, le=1000),
    offset: int = 0,
) -> dict:
    wms = _wms()
    out = []
    for code in sorted(wms.inv.locations):
        loc = wms.inv.locations[code]
        if loc.type == LocationType.ROBOT or type and loc.type != type or zone and loc.zone != zone:
            continue
        if q and q.upper() not in code:
            continue
        units = sum(q_ for _, q_ in wms.inv.rows(location=code))
        if occupied is not None and (units > 0) != occupied:
            continue
        out.append({**loc.to_dict(), "units": units})
    return {"total": len(out), "locations": out[offset : offset + limit]}


@router.get("/locations/{code}", dependencies=[need("wms:view")])
async def location(code: str) -> dict:
    wms = _wms()
    loc = wms.inv.locations.get(code)
    if loc is None:
        raise HTTPException(404, detail=f"No location {code}")
    return {**loc.to_dict(), "stock": _rows(wms, location=code)}


@router.get("/transactions", dependencies=[need("wms:view")])
async def transactions(
    sku: str | None = None,
    location: str | None = None,
    type: str | None = None,
    ref: str | None = None,
    user: str | None = None,
    limit: int = Query(200, le=2000),
) -> list[dict]:
    out = []
    for t in reversed(_wms().inv.ledger):
        if (
            sku
            and t.sku != sku
            or type
            and t.type.value != type
            or ref
            and t.ref != ref
            or user
            and t.user != user
        ):
            continue
        if location and location not in (t.from_loc, t.to_loc):
            continue
        out.append(t.to_dict())
        if len(out) >= limit:
            break
    return out


@router.get("/lots", dependencies=[need("wms:view")])
async def lots(expiring_within_days: int | None = None) -> list[dict]:
    wms = _wms()
    limit = (
        wms.inv.date() + dt.timedelta(days=expiring_within_days)
        if expiring_within_days is not None
        else None
    )
    out = []
    for (sku, lot), info in sorted(
        wms.inv.lots.items(), key=lambda kv: (kv[1].expiry or dt.date.max, kv[0])
    ):
        if limit and (not info.expiry or info.expiry > limit):
            continue
        units = sum(q for _, q in wms.inv.rows(sku=sku, lot=lot))
        if units:
            out.append({**info.to_dict(), "units": units})
    return out[:500]


# ----- scanning --------------------------------------------------------------------------------
class ScanIn(BaseModel):
    code: str = Field(min_length=1, max_length=200)


@router.post("/scan", dependencies=[need("wms:view")])
async def scan(body: ScanIn) -> dict:
    """Decode any barcode and say what it is in this warehouse (item, location, plate ...)."""
    wms = _wms()
    s = bc.parse_scan(body.code)
    out: dict = {"scan": s.to_dict()}
    gtin = s.gtin
    if gtin:
        sku = wms.inv.by_gtin.get(gtin)
        out["item"] = _item_row(wms, sku) if sku else None
        if sku and gtin == wms.inv.items[sku].case_gtin:
            out["unit"] = f"case of {wms.inv.items[sku].case_qty}"
    if s.kind == "location":
        loc = wms.inv.locations.get(s.code)
        out["location"] = {**loc.to_dict(), "stock": _rows(wms, location=s.code)} if loc else None
    if s.sscc:
        on_hand = _rows(wms, lpn=s.sscc)
        expected = next(
            (
                {
                    "po_id": po.po_id,
                    "dock": po.dock,
                    "status": po.status,
                    **{k: v for k, v in p.items() if k != "expiry"},
                    "expiry": p["expiry"].isoformat() if p["expiry"] else None,
                }
                for po in wms.pos.values()
                for p in po.asn
                if p["sscc"] == s.sscc
            ),
            None,
        )
        out["plate"] = {"sscc": s.sscc, "stock": on_hand, "asn": expected}
        if expected and on_hand:
            out["putaway_suggestion"] = wms.putaway_target(on_hand[0]["sku"], on_hand[0]["qty"])
    return out


# ----- inbound -----------------------------------------------------------------------------------
@router.get("/purchase-orders", dependencies=[need("wms:view")])
async def purchase_orders(status: str | None = None, limit: int = Query(100, le=500)) -> list[dict]:
    wms = _wms()
    out = []
    for po in sorted(wms.pos.values(), key=lambda p: p.created, reverse=True):
        if status and po.status != status:
            continue
        d = po.to_dict()
        d["supplier"] = wms.suppliers[po.supplier_id].name
        d["plates_received"] = sum(1 for p in po.asn if p["received"])
        out.append(d)
    return out[:limit]


class ReceiveIn(BaseModel):
    po_id: str
    sscc: str
    qty: int | None = Field(default=None, ge=0)
    damaged: int = Field(default=0, ge=0)
    lot: str | None = Field(default=None, max_length=20)
    expiry: dt.date | None = None


@router.post("/receive")
async def receive(
    body: ReceiveIn, who: Annotated[Principal, Depends(require("wms:receive"))]
) -> dict:
    wms = _wms()
    if body.po_id not in wms.pos:
        raise HTTPException(404, detail=f"No purchase order {body.po_id}")
    try:
        result = wms.receive_plate(
            body.po_id,
            body.sscc.removeprefix("LPN"),
            body.qty,
            body.damaged,
            body.lot,
            body.expiry,
            user=who.username,
        )
    except (InventoryError, StopIteration) as err:
        raise _bad(
            err if isinstance(err, InventoryError) else ValueError("plate not on this ASN")
        ) from err
    rows = _rows(wms, lpn=body.sscc.removeprefix("LPN"))
    suggestion = wms.putaway_target(rows[0]["sku"], rows[0]["qty"]) if rows else []
    return {"result": result, "plate": rows, "putaway_suggestion": suggestion}


class PutawayIn(BaseModel):
    sscc: str
    location: str  # scanned destination
    qty: int | None = Field(default=None, ge=1)


@router.post("/putaway")
async def putaway(
    body: PutawayIn, who: Annotated[Principal, Depends(require("wms:receive"))]
) -> dict:
    """Move (part of) a received plate to the scanned location: the item's pick face, or a
    free reserve position (the plate goes there whole)."""
    from wms.model import TxnType

    wms = _wms()
    sscc = body.sscc.removeprefix("LPN")
    rows = [r for r in wms.inv.rows(lpn=sscc, status=StockStatus.AVAILABLE)]
    if not rows:
        raise _bad(ValueError(f"plate {sscc} holds no available stock"))
    key, qty = rows[0]
    dest = wms.inv.locations.get(body.location)
    if dest is None:
        raise _bad(ValueError(f"unknown location {body.location}"))
    item = wms.inv.items[key.sku]
    po_ref = next(
        (po.po_id for po in wms.pos.values() if any(p["sscc"] == sscc for p in po.asn)), None
    )
    try:
        if dest.type == LocationType.PICK:
            if dest.sku != key.sku:
                raise InventoryError(
                    f"{body.location} is the pick face of {dest.sku}, not {key.sku}"
                )
            room = item.pick_max - wms.inv.qty(key.sku, location=dest.code)
            move = min(qty, body.qty or qty, max(room, 0))
            if move <= 0:
                raise InventoryError(f"{body.location} is full")
            wms.inv.move(
                key.sku,
                move,
                key.location,
                dest.code,
                key.lot,
                TxnType.PUTAWAY,
                from_lpn=sscc,
                ref=po_ref,
                user=who.username,
            )
        elif dest.type == LocationType.RESERVE:
            if any(True for _ in wms.inv.rows(location=dest.code)):
                raise InventoryError(f"{body.location} is occupied")
            move = qty
            wms.inv.move(
                key.sku,
                move,
                key.location,
                dest.code,
                key.lot,
                TxnType.PUTAWAY,
                from_lpn=sscc,
                to_lpn=sscc,
                ref=po_ref,
                user=who.username,
            )
        else:
            raise InventoryError(f"cannot put away into a {dest.type.value} location")
    except InventoryError as err:
        raise _bad(err) from err
    wms._retry_waiting(key.sku)
    return {"moved": move, "to": dest.code, "left_on_plate": qty - move}


# ----- inventory control ----------------------------------------------------------------------
class MoveIn(BaseModel):
    sku: str
    qty: int = Field(ge=1)
    from_location: str
    to_location: str
    lot: str
    lpn: str | None = None


@router.post("/moves")
async def move(body: MoveIn, who: Annotated[Principal, Depends(require("wms:move"))]) -> dict:
    wms = _wms()
    try:
        t = wms.inv.move(
            body.sku,
            body.qty,
            body.from_location,
            body.to_location,
            body.lot,
            from_lpn=body.lpn,
            user=who.username,
        )
    except InventoryError as err:
        raise _bad(err) from err
    return t.to_dict()


class AdjustIn(BaseModel):
    sku: str
    location: str
    lot: str
    delta: int
    reason: str


@router.post("/adjustments")
async def adjust(body: AdjustIn, who: Annotated[Principal, Depends(require("wms:adjust"))]) -> dict:
    wms = _wms()
    try:
        t = wms.inv.adjust(
            body.sku, body.location, body.lot, body.delta, body.reason, user=who.username
        )
    except InventoryError as err:
        raise _bad(err) from err
    wms._check_pick_face(body.sku)
    return t.to_dict()


class HoldIn(BaseModel):
    sku: str
    lot: str | None = None
    reason: str = Field(min_length=3, max_length=120)
    release: bool = False


@router.post("/holds")
async def hold(body: HoldIn, who: Annotated[Principal, Depends(require("wms:hold"))]) -> dict:
    wms = _wms()
    if body.sku not in wms.inv.items:
        raise HTTPException(404, detail=f"No item {body.sku}")
    units = wms.hold(body.sku, body.lot, body.reason, who.username, release=body.release)
    return {"units": units, "action": "released" if body.release else "held"}


# ----- counts --------------------------------------------------------------------------------
@router.get("/counts", dependencies=[need("wms:view")])
async def counts(status: str | None = None, limit: int = Query(200, le=1000)) -> list[dict]:
    out = [
        c.to_dict()
        for c in sorted(_wms().counts.values(), key=lambda c: c.created, reverse=True)
        if not status or c.status == status
    ]
    for c in out:
        if c["status"] == "OPEN":
            c["expected"] = None  # blind count: the counter must not see the system quantity
    return out[:limit]


class CountIn(BaseModel):
    location: str


@router.post("/counts", dependencies=[need("wms:count")])
async def create_count(body: CountIn) -> dict:
    wms = _wms()
    loc = wms.inv.locations.get(body.location)
    if loc is None or loc.type != LocationType.PICK:
        raise _bad(ValueError("counts are created for pick faces"))
    return wms.create_count(loc.code, loc.sku, "MANUAL").to_dict()


class CountResult(BaseModel):
    counted: int = Field(ge=0)


@router.post("/counts/{count_id}/submit")
async def submit_count(
    count_id: str, body: CountResult, who: Annotated[Principal, Depends(require("wms:count"))]
) -> dict:
    wms = _wms()
    if count_id not in wms.counts:
        raise HTTPException(404, detail=f"No count {count_id}")
    try:
        return wms.submit_count(count_id, body.counted, who.username).to_dict()
    except InventoryError as err:
        raise _bad(err) from err


class Decision(BaseModel):
    approve: bool


@router.post("/counts/{count_id}/decide")
async def decide_count(
    count_id: str, body: Decision, who: Annotated[Principal, Depends(require("wms:count_approve"))]
) -> dict:
    wms = _wms()
    if count_id not in wms.counts:
        raise HTTPException(404, detail=f"No count {count_id}")
    try:
        return wms.decide_count(count_id, body.approve, who.username).to_dict()
    except InventoryError as err:
        raise _bad(err) from err


# ----- work and returns ---------------------------------------------------------------------
@router.get("/tasks", dependencies=[need("wms:view")])
async def tasks(status: Literal["open", "all"] = "open") -> dict:
    wms = _wms()
    rows = [
        t.to_dict()
        for t in sorted(wms.tasks.values(), key=lambda t: (t.priority, t.created))
        if status == "all" or t.status in ("OPEN", "IN_PROGRESS")
    ]
    return {
        "tasks": rows[:300],
        "associates": [
            {"name": n, **{k: v for k, v in a.items() if k in ("task", "until", "crew", "station")}}
            for n, a in sorted(wms.associates.items())
        ],
    }


class SettingsIn(BaseModel):
    auto_tasks: dict[str, bool] = Field(default_factory=dict)
    release_mode: Literal["continuous", "wave"] | None = None
    wave_minutes: int | None = Field(default=None, ge=5, le=120)


def _settings(wms) -> dict:
    return {
        "auto_tasks": wms.cfg["auto_tasks"],
        "release_mode": wms.cfg["release_mode"],
        "wave_minutes": wms.cfg["wave_minutes"],
    }


@router.get("/settings", dependencies=[need("wms:view")])
async def settings() -> dict:
    return _settings(_wms())


@router.put("/settings", dependencies=[need("wms:settings")])
async def update_settings(body: SettingsIn) -> dict:
    """Choose which work the associates do by themselves (the rest waits for an operator), and
    how orders are released to the robots: continuously or in waves."""
    wms = _wms()
    unknown = set(body.auto_tasks) - set(wms.cfg["auto_tasks"])
    if unknown:
        raise _bad(ValueError(f"unknown task types: {sorted(unknown)}"))
    wms.cfg["auto_tasks"].update(body.auto_tasks)
    if body.wave_minutes is not None:
        wms.cfg["wave_minutes"] = body.wave_minutes
    if body.release_mode is not None:
        wms.out.set_release_mode(body.release_mode)
    return _settings(wms)


def _return_row(wms, r) -> dict:
    customer = wms.out.customers.get(r.customer_id) if r.customer_id else None
    return {
        **r.to_dict(),
        "item": wms.inv.items[r.sku].name,
        "customer": customer.name if customer else None,
        "due_at": wms.out.clock(r.due),
        "received_at_time": wms.out.clock(r.received_at),
        "inspected_at_time": wms.out.clock(r.inspected_at),
    }


@router.get("/returns", dependencies=[need("wms:view")])
async def returns(status: str | None = None) -> dict:
    """Customer returns, newest first; status RECEIVED = waiting for inspection."""
    from wms.operations import RETURN_CONDITIONS

    wms = _wms()
    rows = [r for r in wms.returns.values() if status in (None, r.status)]
    rows.sort(key=lambda r: r.rma_id, reverse=True)
    counts: dict[str, int] = {}
    for r in wms.returns.values():
        counts[r.status] = counts.get(r.status, 0) + 1
    return {
        "returns": [_return_row(wms, r) for r in rows[:300]],
        "by_status": counts,
        "conditions": {k: {"restock": v[0], "label": v[1]} for k, v in RETURN_CONDITIONS.items()},
        "auto_inspection": wms.cfg["auto_tasks"].get("RETURN", True),
    }


class InspectIn(BaseModel):
    condition: Literal["NEW", "OPENED", "DAMAGED", "DEFECTIVE"]
    note: str | None = Field(None, max_length=200)


@router.post("/returns/{rma_id}/inspect")
async def inspect_return(
    rma_id: str, body: InspectIn, who: Annotated[Principal, Depends(require("wms:receive"))]
) -> dict:
    """Grade a received return: as new or opened goes back to its pick face, damaged or
    defective is scrapped (RETURN_RESTOCK / RETURN_SCRAP in the ledger)."""
    wms = _wms()
    try:
        rma = wms.inspect_return(rma_id, body.condition, body.note, who.username)
    except InventoryError as err:
        raise _bad(err) from err
    return _return_row(wms, rma)


# ----- outbound: customer orders, packing, loading, departures ---------------------------------
def _out():
    return _wms().out


def _refused(err: Exception) -> HTTPException:
    return HTTPException(409, detail={"code": "refused", "message": str(err)})


@router.get("/outbound/orders", dependencies=[need("wms:view")])
async def outbound_orders(
    status: str | None = None,
    q: str | None = Query(None, max_length=40),
    limit: int = Query(200, le=1000),
) -> dict:
    """Customer orders, earliest truck first; status=open (not shipped or cancelled) or one
    status; q searches order id, customer and city."""
    out = _out()
    recs = list(out.orders.values())
    if status == "open":
        recs = [r for r in recs if r.status not in FINAL]
    elif status:
        recs = [r for r in recs if r.status == status]
    rows = [out.order_row(r) for r in recs]
    if q:
        needle = q.lower()
        rows = [
            r
            for r in rows
            if needle in r["order_id"].lower()
            or needle in r["customer"].lower()
            or needle in r["city"].lower()
        ]
    rows.sort(key=lambda r: (r["status"] in FINAL, r["departure"], r["order_id"]))
    counts: dict[str, int] = {}
    for r in out.orders.values():
        counts[r.status] = counts.get(r.status, 0) + 1
    return {"orders": rows[:limit], "total": len(rows), "by_status": counts}


@router.get("/outbound/orders/{order_id}", dependencies=[need("wms:view")])
async def outbound_order(order_id: str) -> dict:
    try:
        detail = _out().order_detail(order_id)
    except OutboundError as err:
        raise HTTPException(404, detail=str(err)) from err
    sim = simulator.engine.orders.get(order_id)
    detail["robot"] = sim.assigned_robot if sim else None
    detail["robot_status"] = sim.status.value if sim else None
    return detail


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=120)


def _not_on_a_robot(order_id: str) -> None:
    sim = simulator.engine.orders.get(order_id)
    if sim is not None and sim.status.value in ("ASSIGNED", "IN_PROGRESS"):
        raise _refused(
            OutboundError(f"{order_id} is with robot {sim.assigned_robot}; wait for packing")
        )


@router.post("/outbound/orders/{order_id}/hold")
async def hold_order(
    order_id: str, body: ReasonIn, who: Annotated[Principal, Depends(require("orders:manage"))]
) -> dict:
    _not_on_a_robot(order_id)
    try:
        rec = _out().hold(order_id, body.reason, who.username)
    except OutboundError as err:
        raise _refused(err) from err
    return _out().order_row(rec)


@router.post("/outbound/orders/{order_id}/release-hold")
async def release_hold(
    order_id: str, who: Annotated[Principal, Depends(require("orders:manage"))]
) -> dict:
    try:
        rec = _out().release_hold(order_id, who.username)
    except OutboundError as err:
        raise _refused(err) from err
    return _out().order_row(rec)


@router.post("/outbound/orders/{order_id}/release")
async def release_order(
    order_id: str, who: Annotated[Principal, Depends(require("orders:manage"))]
) -> dict:
    """Release a ready order to the robots now, ahead of its wave."""
    try:
        rec = _out().release_now(order_id, who.username)
    except OutboundError as err:
        raise _refused(err) from err
    return _out().order_row(rec)


@router.post("/outbound/orders/{order_id}/ship-partial")
async def ship_partial(
    order_id: str, who: Annotated[Principal, Depends(require("orders:manage"))]
) -> dict:
    """Ship what is allocated now; the missing units go on backorder."""
    try:
        rec = _out().ship_partial(order_id, who.username)
    except OutboundError as err:
        raise _refused(err) from err
    return _out().order_row(rec)


@router.post("/outbound/orders/{order_id}/cancel")
async def cancel_order(
    order_id: str, body: ReasonIn, who: Annotated[Principal, Depends(require("orders:manage"))]
) -> dict:
    """Cancel before loading. Allocated stock is freed; units already picked are put back."""
    from simulation.warehouse.entities import OrderStatus

    _not_on_a_robot(order_id)
    try:
        rec = _out().cancel(order_id, body.reason, who.username)
    except OutboundError as err:
        raise _refused(err) from err
    sim = simulator.engine.orders.get(order_id)
    if sim is not None and sim.status == OrderStatus.PENDING:
        sim.status = OrderStatus.CANCELLED  # the dispatcher never sends a robot for it
    return _out().order_row(rec)


class OrderRef(BaseModel):
    order_id: str


class CartonScan(BaseModel):
    sscc: str = Field(min_length=18, max_length=80)  # SSCC, LPN<sscc> or a GS1 (00) scan


def _sscc(raw: str) -> str:
    scan = bc.parse_scan(raw)
    sscc = scan.sscc or raw.removeprefix("LPN")
    if not (sscc.isdigit() and len(sscc) == 18 and bc.valid(sscc)):
        raise _bad(ValueError(f"not a valid SSCC: {raw}"))
    return sscc


def _finish_task(wms, kind: str, user: str, **match) -> None:
    """A manual pack / audit / load replaces the crew's open task for it."""
    for t in wms.tasks.values():
        if (
            t.type == kind
            and t.status == "OPEN"
            and all(t.data.get(k) == v for k, v in match.items())
        ):
            t.status, t.assignee, t.done_at = "DONE", user, wms.inv.tick
            t.result = "done in the app"
            return
    raise _refused(OutboundError(f"no open {kind.lower()} task for {match}"))


@router.post("/outbound/pack")
async def pack(body: OrderRef, who: Annotated[Principal, Depends(require("wms:ship"))]) -> dict:
    """Pack an order waiting at a packing station (when packing is done by hand in the app)."""
    wms = _wms()
    _finish_task(wms, "PACK", who.username, order=body.order_id)
    try:
        cartons = wms.out.pack(body.order_id, who.username)
    except (OutboundError, InventoryError) as err:
        raise _refused(err) from err
    return {"cartons": [wms.out.carton_row(c) for c in cartons]}


@router.post("/outbound/audit")
async def audit(body: CartonScan, who: Annotated[Principal, Depends(require("wms:ship"))]) -> dict:
    wms = _wms()
    sscc = _sscc(body.sscc)
    _finish_task(wms, "AUDIT", who.username, sscc=sscc)
    try:
        return wms.out.carton_row(wms.out.audit(sscc, who.username))
    except (OutboundError, InventoryError) as err:
        raise _refused(err) from err


@router.post("/outbound/load")
async def load(body: CartonScan, who: Annotated[Principal, Depends(require("wms:ship"))]) -> dict:
    """Scan a carton in a sort lane onto its carrier's trailer."""
    wms = _wms()
    sscc = _sscc(body.sscc)
    _finish_task(wms, "LOAD", who.username, sscc=sscc)
    try:
        return wms.out.carton_row(wms.out.load(sscc, who.username))
    except (OutboundError, InventoryError) as err:
        raise _refused(err) from err


@router.get("/outbound/cartons", dependencies=[need("wms:view")])
async def cartons(status: str | None = None, limit: int = Query(200, le=1000)) -> list[dict]:
    out = _out()
    rows = [c for c in out.cartons.values() if status is None or c.status == status]
    rows.sort(key=lambda c: -(c.packed_at or 0))
    return [out.carton_row(c) for c in rows[:limit]]


@router.get("/outbound/cartons/{sscc}", dependencies=[need("wms:view")])
async def carton(sscc: str) -> dict:
    out = _out()
    found = out.cartons.get(_sscc(sscc))
    if found is None:
        raise HTTPException(404, detail=f"No carton {sscc}")
    return out.carton_row(found)


@router.get("/outbound/trips", dependencies=[need("wms:view")])
async def trips() -> list[dict]:
    """Carrier departures: the next trucks and the last two days."""
    out = _out()
    return [
        out.trip_row(t) for t in sorted(out.trips.values(), key=lambda t: (t.departs, t.carrier))
    ]


@router.get("/outbound/trips/{trip_id}", dependencies=[need("wms:view")])
async def trip_manifest(trip_id: str) -> dict:
    """The manifest of a trip: every carton with its order, customer and weight."""
    out = _out()
    trip = out.trips.get(trip_id)
    if trip is None:
        raise HTTPException(404, detail=f"No trip {trip_id}")
    cartons = [out.cartons[s] for s in trip.cartons if s in out.cartons]
    return {
        **out.trip_row(trip),
        "manifest": [
            {
                "sscc": c.sscc,
                "tracking": c.tracking,
                "order_id": c.order_id,
                "customer": out.customers[out.orders[c.order_id].customer_id].name
                if c.order_id in out.orders
                else None,
                "city": out.customers[out.orders[c.order_id].customer_id].city
                if c.order_id in out.orders
                else None,
                "weight_kg": c.scale_kg,
                "units": sum(r["qty"] for r in c.contents),
            }
            for c in cartons
        ],
    }


@router.get("/outbound/waves", dependencies=[need("wms:view")])
async def waves() -> list[dict]:
    return list(_out().waves)


@router.get("/outbound/backorders", dependencies=[need("wms:view")])
async def backorders(status: str | None = "OPEN") -> list[dict]:
    rows = [b.to_dict() for b in _out().backorders.values() if status in (None, b.status)]
    return sorted(rows, key=lambda b: b["bo_id"], reverse=True)[:500]


@router.get("/outbound/customers", dependencies=[need("wms:view")])
async def customer_master() -> list[dict]:
    return [c.to_dict() for c in _out().customers.values()]


@router.get("/outbound/carriers", dependencies=[need("wms:view")])
async def carrier_master() -> list[dict]:
    out = _out()
    return [
        {**c.to_dict(), "cutoff_minutes": out.cfg["cutoff_minutes"]} for c in out.carriers.values()
    ]


@router.get("/outbound/confirmations", dependencies=[need("wms:view")])
async def confirmations(limit: int = Query(100, le=500)) -> list[dict]:
    """Ship confirmations (what an ERP would receive): order, trip, tracking, units shipped."""
    out = _out()
    return [{**c, "time": out.clock(c["tick"])} for c in list(out.confirmations)[:limit]]


# ----- labels and barcodes -------------------------------------------------------------------
def _pdf(data: bytes, name: str) -> Response:
    return Response(
        data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{name}"'},
    )


LabelKind = Literal["items", "locations", "plates", "shipping"]


def _label_sources(kind: str, ref: str):
    """(PDF maker, ZPL maker, file stem) for one label job; 404 when it does not exist."""
    wms = _wms()
    if kind == "items":
        if ref not in wms.inv.items:
            raise HTTPException(404, detail=f"No item {ref}")
        items = [wms.inv.items[ref]]
        return (lambda: labels.item_labels(items)), (lambda: zpl.item_labels(items)), f"item-{ref}"
    if kind == "locations":
        locs = [
            loc
            for c, loc in sorted(wms.inv.locations.items())
            if c.startswith(ref) and loc.type != LocationType.ROBOT
        ][:500]
        if not locs:
            raise HTTPException(404, detail=f"No locations start with {ref}")
        return (
            (lambda: labels.location_labels(locs)),
            (lambda: zpl.location_labels(locs)),
            f"locations-{ref}",
        )
    if kind == "plates":
        sscc = ref.removeprefix("LPN")
        plate, item, supplier = None, None, None
        for po in wms.pos.values():
            for p in po.asn:
                if p["sscc"] == sscc:
                    plate, item = p, wms.inv.items[p["sku"]]
                    supplier = wms.suppliers[po.supplier_id].name
        if plate is None:
            rows = _rows(wms, lpn=sscc)
            if not rows:
                raise HTTPException(404, detail=f"No plate {sscc}")
            r = rows[0]
            plate = {
                "sscc": sscc,
                "sku": r["sku"],
                "qty": r["qty"],
                "lot": r["lot"],
                "expiry": dt.date.fromisoformat(r["expiry"]) if r["expiry"] else None,
            }
            item = wms.inv.items[r["sku"]]
            supplier = wms.suppliers[item.supplier_id].name
        return (
            (lambda: labels.pallet_label(plate, item, supplier)),
            (lambda: zpl.pallet_label(plate, item, supplier)),
            f"sscc-{sscc}",
        )
    out = wms.out  # shipping
    found = out.cartons.get(_sscc(ref))
    if found is None or found.order_id not in out.orders:
        raise HTTPException(404, detail=f"No carton {ref}")
    rec = out.orders[found.order_id]
    args = (
        found.to_dict(),
        out.customers[rec.customer_id].to_dict(),
        out.carriers[rec.carrier].to_dict(),
    )
    return (
        (lambda: labels.shipping_label(*args)),
        (lambda: zpl.shipping_label(*args)),
        f"ship-{found.sscc}",
    )


def _label_response(kind: str, ref: str, fmt: str) -> Response:
    make_pdf, make_zpl, stem = _label_sources(kind, ref)
    if fmt == "zpl":
        return Response(
            make_zpl(),
            media_type="text/plain; charset=us-ascii",
            headers={"Content-Disposition": f'attachment; filename="{stem}.zpl"'},
        )
    return _pdf(make_pdf(), f"{stem}.pdf")


Fmt = Annotated[Literal["pdf", "zpl"], Query(alias="format")]


@router.get("/labels/items/{sku}", dependencies=[need("wms:view")])
async def item_label(sku: str, fmt: Fmt = "pdf") -> Response:
    """Item label: EAN-13 of the unit and GS1-128 of the case. format=zpl for thermal printers."""
    return _label_response("items", sku, fmt)


@router.get("/labels/locations", dependencies=[need("wms:view")])
async def location_labels(
    prefix: str = Query(..., min_length=1, max_length=20), fmt: Fmt = "pdf"
) -> Response:
    """Labels for every location whose code starts with `prefix` (e.g. A-05 for a rack row)."""
    return _label_response("locations", prefix, fmt)


@router.get("/labels/plates/{sscc}", dependencies=[need("wms:view")])
async def plate_label(sscc: str, fmt: Fmt = "pdf") -> Response:
    return _label_response("plates", sscc, fmt)


@router.get("/labels/shipping/{sscc}", dependencies=[need("wms:view")])
async def shipping_label(sscc: str, fmt: Fmt = "pdf") -> Response:
    """GS1 shipping label of a packed carton (100 x 150 mm)."""
    return _label_response("shipping", sscc, fmt)


@router.get("/printers", dependencies=[need("wms:view")])
async def label_printers() -> list[str]:
    """Names of the configured network label printers (LABEL_PRINTERS)."""
    return sorted(printers.printers())


class PrintIn(BaseModel):
    kind: LabelKind
    ref: str = Field(min_length=1, max_length=40)
    printer: str = Field(min_length=1, max_length=40)
    copies: int = Field(1, ge=1, le=20)


@router.post("/labels/print")
async def print_label(
    body: PrintIn, who: Annotated[Principal, Depends(require("wms:view"))]
) -> dict:
    """Send a label as ZPL straight to a configured network printer (raw port 9100)."""
    import asyncio

    _, make_zpl, stem = _label_sources(body.kind, body.ref)
    try:
        sent = await asyncio.to_thread(printers.send, body.printer, make_zpl(), body.copies)
    except printers.PrinterError as err:
        raise HTTPException(502, detail={"code": "printer", "message": str(err)}) from err
    return {"printed": stem, "printer": body.printer, "copies": body.copies, "bytes": sent}


# ----- exports (CSV, PDF) ------------------------------------------------------------------------
def _csv(text: str, name: str) -> Response:
    return Response(
        text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


EXPORT_COLUMNS = {
    "items": ["sku", "name", "category", "abc", "gtin", "home", "on_hand", "available",
              "allocated", "atp", "pick_face", "reserve", "on_hold", "on_order", "unit_cost"],
    "stock": ["sku", "location", "lot", "expiry", "status", "lpn", "qty"],
    "transactions": ["txn_id", "tick", "type", "sku", "qty", "from_loc", "to_loc", "lot", "lpn",
                     "status", "reason", "ref", "user"],
    "counts": ["count_id", "location", "sku", "reason", "status", "expected", "counted",
               "variance", "value", "counter", "decided_by"],
    "orders": ["order_id", "status", "priority", "customer_id", "customer", "city", "service",
               "created_at", "departure_at", "shipped_at", "on_time", "units", "cartons",
               "backordered", "missed", "hold_reason"],
    "returns": ["rma_id", "order_id", "customer", "sku", "item", "qty", "reason", "status",
                "condition", "inspected_by", "inspected_at_time", "note"],
}  # fmt: skip


@router.get("/exports/{name}.csv", dependencies=[need("wms:view")])
async def export_csv(
    name: Literal["items", "stock", "transactions", "counts", "orders", "returns"],
    limit: int = Query(20_000, le=100_000),
) -> Response:
    """Download a table as CSV (opens in Excel). Transactions: the newest `limit` lines."""
    wms = _wms()
    if name == "items":
        rows = [_item_row(wms, s) for s in sorted(wms.inv.items)]
    elif name == "stock":
        rows = _rows(wms)
    elif name == "transactions":
        rows = [t.to_dict() for t in wms.inv.ledger[-limit:]]
    elif name == "counts":
        rows = [c.to_dict() for c in sorted(wms.counts.values(), key=lambda c: c.count_id)]
    elif name == "orders":
        rows = [wms.out.order_row(r) for r in wms.out.orders.values()]
    else:
        rows = [_return_row(wms, r) for r in sorted(wms.returns.values(), key=lambda r: r.rma_id)]
    stamp = wms.inv.date().isoformat()
    return _csv(exports.to_csv(rows[:limit], EXPORT_COLUMNS[name]), f"{name}-{stamp}.csv")


@router.get("/outbound/trips/{trip_id}/manifest.{fmt}", dependencies=[need("wms:view")])
async def trip_manifest_file(trip_id: str, fmt: Literal["csv", "pdf"]) -> Response:
    """The truck's manifest as a printable PDF (driver signs it) or CSV for the carrier."""
    detail = await trip_manifest(trip_id)
    if fmt == "csv":
        columns = ["tracking", "sscc", "order_id", "customer", "city", "units", "weight_kg"]
        return _csv(exports.to_csv(detail["manifest"], columns), f"manifest-{trip_id}.csv")
    return _pdf(exports.manifest_pdf(detail, detail["manifest"]), f"manifest-{trip_id}.pdf")


@router.get("/counts/sheet.pdf", dependencies=[need("wms:view")])
async def count_sheet() -> Response:
    """Blind count sheet of the open counts, for counting on paper (no system quantities)."""
    wms = _wms()
    open_counts = [
        c for c in sorted(wms.counts.values(), key=lambda c: c.location) if c.status == "OPEN"
    ]
    rows = [
        {
            "count_id": c.count_id,
            "location": c.location,
            "check": wms.inv.locations[c.location].check,
            "sku": c.sku,
            "item": wms.inv.items[c.sku].name,
        }
        for c in open_counts
    ]
    return _pdf(exports.count_sheet_pdf(rows, wms.out.clock(wms.inv.tick)), "count-sheet.pdf")


@router.get("/barcode.svg", dependencies=[need("wms:view")])
async def barcode(
    kind: Literal["ean13", "code128", "gs1-128"], value: str = Query(..., max_length=120)
) -> Response:
    try:
        svg = labels.barcode_svg(kind, value)
    except Exception as err:  # reportlab rejects characters a symbology cannot encode
        raise _bad(err) from err
    return Response(svg, media_type="image/svg+xml")

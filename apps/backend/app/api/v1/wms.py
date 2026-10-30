"""Warehouse management endpoints: inventory, scanning, receiving, putaway, moves, adjustments,
holds, cycle counts, purchase orders, tasks and labels.

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
from app.services.simulator import simulator
from wms import barcodes as bc
from wms import labels
from wms.inventory import InventoryError
from wms.model import REASONS, LocationType, StockStatus

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
            {"name": n, **{k: v for k, v in a.items() if k in ("task", "until")}}
            for n, a in sorted(wms.associates.items())
        ],
    }


class SettingsIn(BaseModel):
    auto_tasks: dict[str, bool]


@router.get("/settings", dependencies=[need("wms:view")])
async def settings() -> dict:
    return {"auto_tasks": _wms().cfg["auto_tasks"]}


@router.put("/settings", dependencies=[need("wms:settings")])
async def update_settings(body: SettingsIn) -> dict:
    """Choose which work the associates do by themselves; the rest waits for an operator."""
    wms = _wms()
    unknown = set(body.auto_tasks) - set(wms.cfg["auto_tasks"])
    if unknown:
        raise _bad(ValueError(f"unknown task types: {sorted(unknown)}"))
    wms.cfg["auto_tasks"].update(body.auto_tasks)
    return {"auto_tasks": wms.cfg["auto_tasks"]}


@router.get("/returns", dependencies=[need("wms:view")])
async def returns() -> list[dict]:
    return [
        r.to_dict() for r in sorted(_wms().returns.values(), key=lambda r: r.rma_id, reverse=True)
    ][:200]


# ----- labels and barcodes -------------------------------------------------------------------
def _pdf(data: bytes, name: str) -> Response:
    return Response(
        data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{name}"'},
    )


@router.get("/labels/items/{sku}", dependencies=[need("wms:view")])
async def item_label(sku: str) -> Response:
    wms = _wms()
    if sku not in wms.inv.items:
        raise HTTPException(404, detail=f"No item {sku}")
    return _pdf(labels.item_labels([wms.inv.items[sku]]), f"item-{sku}.pdf")


@router.get("/labels/locations", dependencies=[need("wms:view")])
async def location_labels(prefix: str = Query(..., min_length=1, max_length=20)) -> Response:
    """Labels for every location whose code starts with `prefix` (e.g. A-05 for a rack row)."""
    wms = _wms()
    locs = [
        loc
        for c, loc in sorted(wms.inv.locations.items())
        if c.startswith(prefix) and loc.type != LocationType.ROBOT
    ]
    if not locs:
        raise HTTPException(404, detail=f"No locations start with {prefix}")
    return _pdf(labels.location_labels(locs[:500]), f"locations-{prefix}.pdf")


@router.get("/labels/plates/{sscc}", dependencies=[need("wms:view")])
async def plate_label(sscc: str) -> Response:
    wms = _wms()
    sscc = sscc.removeprefix("LPN")
    for po in wms.pos.values():
        for plate in po.asn:
            if plate["sscc"] == sscc:
                item = wms.inv.items[plate["sku"]]
                return _pdf(
                    labels.pallet_label(plate, item, wms.suppliers[po.supplier_id].name),
                    f"sscc-{sscc}.pdf",
                )
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
    return _pdf(
        labels.pallet_label(plate, item, wms.suppliers[item.supplier_id].name), f"sscc-{sscc}.pdf"
    )


@router.get("/barcode.svg", dependencies=[need("wms:view")])
async def barcode(
    kind: Literal["ean13", "code128", "gs1-128"], value: str = Query(..., max_length=120)
) -> Response:
    try:
        svg = labels.barcode_svg(kind, value)
    except Exception as err:  # reportlab rejects characters a symbology cannot encode
        raise _bad(err) from err
    return Response(svg, media_type="image/svg+xml")

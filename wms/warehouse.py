"""The WMS of the simulated site: runs inbound, putaway, allocation, replenishment, purchasing,
cycle counts, expiry, returns and the associates who do the manual work.

    supplier ─► purchase order ─► truck at a dock door (ASN: license plates with lot / expiry)
            ─► RECEIVE (scan SSCC, check quantity, damage → quarantine) ─► staging lane
            ─► PUTAWAY: fill the pick face up to its max, the rest on a reserve position
    order   ─► ALLOCATE at pick faces (FEFO) ─► released to a robot ─► PICK ─► tote at packing
            short at the pick face?  urgent REPLENISH from reserve, order waits until it lands
            ─► PACK (cartons, weight check, label) ─► carrier lane ─► LOAD ─► truck departs: SHIP
            (wms/outbound.py: customers, carriers, waves, holds, cancellations, backorders)
    every hour: demand update, reorder (reorder point = demand over lead time + safety stock),
                cycle counts (A items most often), expiry check, shrinkage (simulated), returns

Associates take open tasks by priority; each task takes walking time plus handling time. Three
crews: inbound associates (receiving to counts), one packer per packing station, and dock loaders
(loading trailers, putting back cancelled orders). Operators can do the same work from the
app (scan-based) under their own name.
"""

from __future__ import annotations

import datetime as dt
import math
import random
from collections import Counter, defaultdict, deque

from wms import rf
from wms.inventory import AVAILABLE, Inventory, InventoryError
from wms.labour import Labour
from wms.master import build_items, build_locations, suppliers
from wms.model import LocationType, StockKey, StockStatus, TxnType
from wms.operations import (
    RETURN_CONDITIONS,
    TASK_CREW,
    Count,
    POLine,
    PurchaseOrder,
    Return,
    Task,
)
from wms.outbound import Outbound

DEFAULTS = {
    "associates": 8,  # people doing receiving, putaway, replenishment, counts, returns
    "walk_m_per_tick": 7.0,  # 1.2 m/s at 6 simulated seconds per tick
    "handling_ticks": {
        "RECEIVE": 15,
        "PUTAWAY": 8,
        "REPLENISH": 10,
        "REPLENISH_URGENT": 10,
        "COUNT": 6,
        "RETURN": 10,
        "QUARANTINE": 6,
        "PACK": 6,  # plus pack_ticks_per_unit for every unit in the tote
        "AUDIT": 8,
        "LOAD": 3,
        "PUTBACK": 8,
    },
    "pack_ticks_per_unit": 1,
    "packers_per_station": 1,
    "loaders": 2,
    # outbound
    "release_mode": "continuous",  # continuous (as soon as allocated) | wave
    "wave_minutes": 15,
    "wave_max_orders": 80,
    "cutoff_minutes": 30,  # cartons must be ready this long before the truck leaves
    "pack_buffer_minutes": 15,  # pick-by deadline + this = earliest truck an order is planned on
    "credit_hold_rate": 0.01,  # share of new orders held for a (simulated) credit check
    "hold_minutes": (20, 90),
    "backorder_after_minutes": 60,  # then ship partial if the customer accepts it
    "mispack_rate": 0.004,  # cartons with a wrong unit: caught by the weight check
    "service_level_z": 1.65,  # 95 % cycle service level for the safety stock
    "review_hours": 4,  # order-up-to: cover lead time + review period
    "opening_cover_days": 1.5,
    "shrinkage_per_hour": 0.004,  # share of pick faces whose shelf quietly loses 1-3 units
    "found_per_hour": 0.001,  # share where the shelf has 1-2 units more than recorded
    "damage_on_receipt": 0.02,  # share of received license plates with damaged units
    "return_rate": 0.015,  # share of shipped order lines returned
    "count_tolerance_pct": 5.0,  # variance accepted without a recount
    "auto_approve_value": 150.0,  # recount variances below this value ($) are approved
    "counts_per_hour": 12,  # cycle-count locations scheduled per hour (A items most often)
    "near_expiry_days": 7,
    # Task types the associates do by themselves; switched off, the work waits for an operator
    # with a scanner in the app (e.g. receiving at the docks done by hand-held scanning).
    "auto_tasks": {
        "RECEIVE": True,
        "PUTAWAY": True,
        "REPLENISH": True,
        "REPLENISH_URGENT": True,
        "COUNT": True,
        "RETURN": True,
        "QUARANTINE": True,
        "PACK": True,
        "AUDIT": True,
        "LOAD": True,
        "PUTBACK": True,
    },
}


class Warehouse:
    def __init__(
        self,
        layout,
        products,
        faces,
        rng: random.Random,
        ticks_per_hour: int,
        config=None,
        outbound_rng: random.Random | None = None,
    ):
        self.cfg = {**DEFAULTS, **(config or {})}
        self.cfg["auto_tasks"] = {**DEFAULTS["auto_tasks"], **self.cfg.get("auto_tasks", {})}
        self.rng = rng
        self.tph = ticks_per_hour
        self.layout = layout
        self.inv = Inventory(ticks_per_day=ticks_per_hour * 24)
        self.suppliers = suppliers()
        items = build_items(products, faces)
        for item in items:
            self.inv.add_item(item)
        for location in build_locations(layout, faces, items):
            self.inv.add_location(location)
        self.faces = faces
        self.tasks: dict[str, Task] = {}
        self.pos: dict[str, PurchaseOrder] = {}
        self.counts: dict[str, Count] = {}
        self.returns: dict[str, Return] = {}
        self.seq = Counter()
        self.associates = {
            f"AS{i + 1:02d}": {"task": None, "until": 0, "x": 40, "y": 2, "crew": "inbound"}
            for i in range(self.cfg["associates"])
        }
        packing = sorted(
            (loc for loc in self.inv.locations.values() if loc.type == LocationType.PACK),
            key=lambda p: p.code,
        )
        stations = [loc for loc in packing for _ in range(self.cfg["packers_per_station"])]
        for i, loc in enumerate(stations, start=1):
            self.associates[f"PK{i:02d}"] = {
                "task": None, "until": 0, "x": loc.x, "y": loc.y, "crew": "pack",
                "station": loc.code,
            }  # fmt: skip
        lane = next(loc for loc in self.inv.locations.values() if loc.type == LocationType.LANE)
        for i in range(self.cfg["loaders"]):
            self.associates[f"LD{i + 1:02d}"] = {
                "task": None, "until": 0, "x": lane.x, "y": lane.y, "crew": "dock",
            }  # fmt: skip
        # Standards and rates (wms/labour.py). Seeded from the generator's state without drawing
        # from it, so every other random choice of the WMS stays as it was.
        self.labour = Labour(self, seed=str(hash(rng.getstate())))
        self.waiting: dict[str, list[tuple[int, str, int]]] = {}  # order -> (line, sku, missing)
        self.ordered: dict[str, dict[int, list]] = {}  # order -> line -> [sku, units allocated]
        self.popularity = self._popularity()
        total = sum(self.popularity.values())
        # Prior for the demand of all SKUs together until real picks are observed.
        self.expected_units_per_hour = float(self.cfg.get("expected_units_per_hour", 250.0))
        self.demand = {
            s: self.expected_units_per_hour * w / total for s, w in self.popularity.items()
        }
        self._hour_units: Counter = Counter()
        self.alerts: deque = deque(maxlen=200)
        self.metrics = Counter()
        self.dock_to_stock: deque = deque(maxlen=500)  # ticks from truck arrival to putaway
        self._expiry_warned: set[tuple[str, str]] = set()
        self._opening_stock()
        self._classify_abc()
        self.out = Outbound(self, outbound_rng or random.Random(0))

    # ----- helpers ---------------------------------------------------------------------------
    def _id(self, prefix: str) -> str:
        self.seq[prefix] += 1
        return f"{prefix}-{self.seq[prefix]:06d}"

    def _alert(self, level: str, text: str, ref: str | None = None) -> None:
        self.metrics["alert_seq"] += 1
        self.alerts.appendleft(
            {"seq": self.metrics["alert_seq"], "tick": self.inv.tick, "level": level,
             "text": text, "ref": ref}
        )  # fmt: skip

    def _popularity(self) -> dict[str, float]:
        """Zipf-like demand: a deterministic shuffle ranks the SKUs; weight 1 / (rank + 10).
        About 20 % of the SKUs take about 70 % of the units, as in real e-commerce."""
        import zlib

        skus = sorted(self.inv.items, key=lambda s: zlib.crc32(s.encode()))
        return {s: 1.0 / (rank + 10) for rank, s in enumerate(skus)}

    def _new_lot(self, sku: str) -> str:
        self.seq["lot"] += 1
        return f"L{self.inv.date():%y%m%d}{self.seq['lot']:05d}"

    def _expiry(self, sku: str, age_days: int = 0):
        life = self.inv.items[sku].shelf_life_days
        return self.inv.date() + dt.timedelta(days=life - age_days) if life else None

    def _serials(self, sku: str, qty: int) -> list[str]:
        if not self.inv.items[sku].serial_controlled:
            return []
        out = []
        for _ in range(qty):
            self.seq["serial"] += 1
            out.append(f"SN{self.inv.items[sku].gtin[-6:]}{self.seq['serial']:07d}")
        return out

    def _classify_abc(self) -> None:
        ranked = sorted(self.demand, key=lambda s: -self.demand[s])
        total = sum(self.demand.values()) or 1.0
        running = 0.0
        for sku in ranked:
            running += self.demand[sku] / total
            self.inv.items[sku].abc = "A" if running <= 0.8 else "B" if running <= 0.95 else "C"

    # ----- opening stock -----------------------------------------------------------------------
    def _opening_stock(self) -> None:
        """Go-live load: pick faces filled between min and max, reserve plates for about
        `opening_cover_days` of demand, lots of different ages (some close to expiry)."""
        reserve_free = self._free_reserve_positions()
        for sku in sorted(self.inv.items):
            item = self.inv.items[sku]
            age = self.rng.randint(0, (item.shelf_life_days or 60) // 2)
            lot = self._new_lot(sku)
            qty = self.rng.randint(item.pick_min + 1, item.pick_max)
            self.inv.receive(
                sku,
                qty,
                lot,
                self._expiry(sku, age),
                item.home,
                None,
                ref="GO-LIVE",
                serials=self._serials(sku, qty),
            )
            need = self.demand[sku] * 24 * self.cfg["opening_cover_days"] - qty
            plate = item.case_qty * item.pallet_cases
            while need > 0 and reserve_free:
                loc = self._nearest_reserve(reserve_free, item.home)
                reserve_free.remove(loc)
                lot = self._new_lot(sku)
                age = self.rng.randint(0, (item.shelf_life_days or 60) // 3)
                self.inv.receive(
                    sku,
                    plate,
                    lot,
                    self._expiry(sku, age),
                    loc,
                    self.inv.new_lpn(),
                    ref="GO-LIVE",
                    serials=self._serials(sku, plate),
                )
                need -= plate
        self.inv.take_new_transactions()  # the go-live load is the starting balance, not activity
        self.inv.ledger.clear()

    def _free_reserve_positions(self) -> set[str]:
        used = {k.location for k, q in self.inv.stock.items() if q > 0}
        return {
            code
            for code, loc in self.inv.locations.items()
            if loc.type == LocationType.RESERVE and not loc.blocked and code not in used
        }

    def _nearest_reserve(self, free: set[str], home: str) -> str:
        """Same bay first, then the nearest free position (walking distance from the pick face)."""
        bay = home.rsplit("-", 1)[0]
        same_bay = sorted(c for c in free if c.startswith(bay + "-"))
        if same_bay:
            return same_bay[0]
        h = self.inv.locations[home]
        return min(
            free,
            key=lambda c: (
                abs(self.inv.locations[c].x - h.x) + abs(self.inv.locations[c].y - h.y),
                c,
            ),
        )

    # ----- orders (called by the simulator) ----------------------------------------------------
    def atp(self, sku: str) -> int:
        return self.inv.atp(sku)

    def orderable(self) -> list[str]:
        return sorted(s for s in self.inv.items if self.inv.atp(s) > 0)

    def allocate_order(self, order) -> bool:
        """Reserve stock for every line. Lines short at the pick face wait for an urgent
        replenishment; the order is released to robots only when everything is allocated."""
        self.ordered[order.order_id] = {}
        missing = []
        for line, item in enumerate(order.items):
            self.metrics["units_ordered"] += item.quantity
            got = self.inv.allocate(order.order_id, line, item.product_id, item.quantity)
            self.ordered[order.order_id][line] = [item.product_id, got]
            if got < item.quantity:
                missing.append((line, item.product_id, item.quantity - got))
                self._replenish(item.product_id, urgent=True)
        if missing:
            self.waiting[order.order_id] = missing
        self.out.register(order, waiting=bool(missing))
        return not missing

    def releasable(self, order_id: str) -> bool:
        """Fully allocated (or partly, with a backorder), not on hold, released to the robots."""
        return self.out.releasable(order_id)

    def _retry_waiting(self, sku: str) -> None:
        for order_id in sorted(self.waiting):
            still = []
            for line, s, need in self.waiting[order_id]:
                if s == sku:
                    got = self.inv.allocate(order_id, line, s, need)
                    self.ordered[order_id][line][1] += got
                    need -= got
                if need > 0:
                    still.append((line, s, need))
            if still:
                self.waiting[order_id] = still
            else:
                del self.waiting[order_id]
                self.out.stock_complete(order_id)

    def pick_line(self, order_id: str, line: int, robot: str) -> tuple[int, int]:
        picked, short = self.inv.pick(order_id, line, robot)
        self.metrics["units_picked"] += picked
        self.out.picked(order_id, line, picked, short)
        if picked or short:
            sku = next(
                (a.sku for a in self.inv.allocations.get(order_id, []) if a.line == line), None
            )
            if sku:
                self._hour_units[sku] += picked
                self._check_pick_face(sku)
        if short:
            self.metrics["units_short"] += short
            alloc = next(a for a in self.inv.allocations[order_id] if a.line == line)
            self._alert(
                "warning",
                f"Short pick: {alloc.sku} at {alloc.location} ({short} missing)",
                order_id,
            )
            self._exception_count(alloc.location, alloc.sku, "SHORT_PICK")
        return picked, short

    def deliver_to_pack(self, order_id: str, robot: str, station: str) -> int:
        """The robot reached the packing station; packing and shipping follow (outbound)."""
        self.ordered.pop(order_id, None)
        self.metrics["orders_at_pack"] += 1
        return self.out.delivered(order_id, robot, station)

    def cancel_order(self, order_id: str) -> None:
        self.inv.deallocate(order_id)
        self.waiting.pop(order_id, None)

    # ----- replenishment -----------------------------------------------------------------------
    def _check_pick_face(self, sku: str) -> None:
        item = self.inv.items[sku]
        if (
            self.inv.qty(sku, location=item.home) - self.inv.allocated(sku, item.home)
            < item.pick_min
        ):
            self._replenish(sku)

    def _open_task(self, type_prefix: str, **match) -> Task | None:
        for t in self.tasks.values():
            if t.status in ("OPEN", "IN_PROGRESS") and t.type.startswith(type_prefix):
                if all(t.data.get(k) == v for k, v in match.items()):
                    return t
        return None

    def _replenish(self, sku: str, urgent: bool = False) -> None:
        existing = self._open_task("REPLENISH", sku=sku)
        if existing:
            if urgent and existing.type == "REPLENISH" and existing.status == "OPEN":
                existing.type = "REPLENISH_URGENT"
            return
        if self._reserve_plates(sku):
            self._task("REPLENISH_URGENT" if urgent else "REPLENISH", sku=sku)
        elif urgent:
            self._alert("warning", f"{sku}: pick face empty and no reserve stock", sku)

    def _reserve_plates(self, sku: str) -> list[tuple[StockKey, int]]:
        """Reserve license plates of the item, first-expiry / first-received first."""
        plates = [
            (k, q)
            for k, q in self.inv.rows(sku=sku, status=AVAILABLE)
            if self.inv.locations[k.location].type == LocationType.RESERVE and k.lpn
        ]

        def order(kq):
            lot = self.inv.lots.get((sku, kq[0].lot))
            return (lot.expiry or dt.date.max, lot.received_tick, kq[0].location)

        return sorted(plates, key=order)

    def _do_replenish(self, task: Task, user: str) -> str:
        sku = task.data["sku"]
        item = self.inv.items[sku]
        room = item.pick_max - self.inv.qty(sku, location=item.home)
        moved = 0
        for key, qty in self._reserve_plates(sku):
            if room <= 0:
                break
            take = min(qty, max(room, item.case_qty))  # whole cases; may overfill by < 1 case
            take = min(qty, math.ceil(take / item.case_qty) * item.case_qty)
            self.inv.move(
                sku,
                take,
                key.location,
                item.home,
                key.lot,
                TxnType.REPLENISH,
                from_lpn=key.lpn,
                ref=task.task_id,
                user=user,
            )
            moved += take
            room -= take
        self._retry_waiting(sku)
        return f"moved {moved} units to {item.home}" if moved else "no reserve stock"

    # ----- purchasing ---------------------------------------------------------------------------
    def inventory_position(self, sku: str) -> int:
        on_order = sum(
            ln.qty - ln.received
            for po in self.pos.values()
            if po.status != "CLOSED"
            for ln in po.lines
            if ln.sku == sku
        )
        return self.inv.atp(sku) + on_order

    def reorder_point(self, sku: str) -> tuple[float, float]:
        """(reorder point, order-up-to level) in units: demand over the lead time plus safety
        stock z·σ·√L (Poisson-like σ), and up to lead time + review period of demand."""
        sup = self.suppliers[self.inv.items[sku].supplier_id]
        lead = sum(sup.lead_time_hours) / 2
        d = self.demand[sku]
        safety = self.cfg["service_level_z"] * math.sqrt(max(d, 0.05) * lead)
        rop = d * lead + safety
        return rop, rop + d * self.cfg["review_hours"]

    def _plan_purchases(self) -> None:
        lines: dict[str, list[POLine]] = defaultdict(list)
        for sku in sorted(self.inv.items):
            rop, up_to = self.reorder_point(sku)
            position = self.inventory_position(sku)
            if position <= rop:
                item = self.inv.items[sku]
                plate = item.case_qty * item.pallet_cases
                qty = max(plate, math.ceil((up_to - position) / plate) * plate)
                lines[item.supplier_id].append(POLine(sku, qty))
        for supplier_id, po_lines in sorted(lines.items()):
            self.create_po(supplier_id, po_lines, user="planner")

    def create_po(
        self, supplier_id: str, lines: list[POLine], user: str = "planner"
    ) -> PurchaseOrder:
        sup = self.suppliers[supplier_id]
        eta = self.inv.tick + self.rng.randint(*sup.lead_time_hours) * self.tph
        po = PurchaseOrder(
            self._id("PO"), supplier_id, self.inv.tick, eta, lines, status="IN_TRANSIT"
        )
        for ln in lines:  # the supplier's advance shipping notice: plates with lots and expiry
            item = self.inv.items[ln.sku]
            plate = item.case_qty * item.pallet_cases
            left = ln.qty
            while left > 0:
                q = min(plate, left)
                po.asn.append(
                    {
                        "sscc": self.inv.new_lpn(),
                        "sku": ln.sku,
                        "qty": q,
                        "lot": self._new_lot(ln.sku),
                        "expiry": self._expiry(ln.sku),
                        "received": False,
                    }
                )
                left -= q
        self.pos[po.po_id] = po
        self.metrics["purchase_orders"] += 1
        return po

    def _trucks(self) -> None:
        for po in sorted(self.pos.values(), key=lambda p: p.eta):
            if po.status == "IN_TRANSIT" and self.inv.tick >= po.eta:
                busy = {p.dock for p in self.pos.values() if p.status in ("AT_DOCK", "RECEIVING")}
                free = [
                    c
                    for c, loc in sorted(self.inv.locations.items())
                    if loc.type == LocationType.DOCK and c not in busy
                ]
                if not free:
                    break  # all doors taken: the truck waits in the yard
                po.status, po.dock, po.arrived = "AT_DOCK", free[0], self.inv.tick
                for plate in po.asn:
                    self._task("RECEIVE", po=po.po_id, sscc=plate["sscc"], dock=po.dock)
                self._alert(
                    "info",
                    f"Truck from {self.suppliers[po.supplier_id].name} at {po.dock} "
                    f"({len(po.asn)} plates)",
                    po.po_id,
                )

    def receive_plate(
        self,
        po_id: str,
        sscc: str,
        qty: int | None = None,
        damaged: int = 0,
        lot: str | None = None,
        expiry=None,
        user: str = "system",
        task: Task | None = None,
    ) -> str:
        """Receive one license plate of an ASN: good units to the staging lane on the plate,
        damaged units to quarantine. Quantities differing from the ASN are recorded."""
        po = self.pos[po_id]
        plate = next(p for p in po.asn if p["sscc"] == sscc)
        if plate["received"]:
            raise InventoryError(f"plate {sscc} already received")
        qty = plate["qty"] if qty is None else qty
        lot = lot or plate["lot"]
        expiry = expiry or plate["expiry"]
        stage = po.dock.replace("DOCK", "STAGE")
        good = qty - damaged
        sku = plate["sku"]
        if good > 0:
            self.inv.receive(
                sku,
                good,
                lot,
                expiry,
                stage,
                sscc,
                ref=po_id,
                user=user,
                serials=self._serials(sku, good),
            )
            self._task("PUTAWAY", sscc=sscc, sku=sku, po=po_id, arrived=po.arrived)
        if damaged > 0:
            self.inv.receive(
                sku,
                damaged,
                lot,
                expiry,
                "QA-01",
                None,
                ref=po_id,
                user=user,
                status=StockStatus.DAMAGED,
            )
            self._task("QUARANTINE", sku=sku, lot=lot)
            self._alert("warning", f"{damaged} damaged units of {sku} received ({po_id})", po_id)
        plate["received"] = True
        line = next(ln for ln in po.lines if ln.sku == sku)
        line.received += qty
        line.damaged += damaged
        if qty != plate["qty"]:
            self._alert(
                "warning", f"{po_id}: plate {sscc} had {qty} units, ASN said {plate['qty']}", po_id
            )
        po.status = "RECEIVING"
        if all(p["received"] for p in po.asn):
            po.status, po.closed = "CLOSED", self.inv.tick
        self.metrics["plates_received"] += 1
        return f"received {qty} ({damaged} damaged) of {sku}"

    def putaway_target(self, sku: str, qty: int) -> list[tuple[str, int]]:
        """Directed putaway: top up the pick face first, the rest to the nearest free reserve
        position (same bay first)."""
        item = self.inv.items[sku]
        room = max(0, item.pick_max - self.inv.qty(sku, location=item.home))
        out = []
        if room > 0 and not self.inv.locations[item.home].blocked:
            out.append((item.home, min(room, qty)))
        rest = qty - (out[0][1] if out else 0)
        if rest > 0:
            free = self._free_reserve_positions()
            if free:
                out.append((self._nearest_reserve(free, item.home), rest))
        return out

    def _do_putaway(self, task: Task, user: str) -> str:
        sscc = task.data["sscc"]
        rows = list(self.inv.rows(lpn=sscc, status=AVAILABLE))
        if not rows:
            return "plate empty"
        key, qty = rows[0]
        done = []
        for target, q in self.putaway_target(key.sku, qty):
            to_lpn = None if self.inv.locations[target].type == LocationType.PICK else sscc
            self.inv.move(
                key.sku,
                q,
                key.location,
                target,
                key.lot,
                TxnType.PUTAWAY,
                from_lpn=sscc,
                to_lpn=to_lpn,
                ref=task.data.get("po"),
                user=user,
            )
            done.append(f"{q} to {target}")
        if task.data.get("arrived") is not None:
            self.dock_to_stock.append(self.inv.tick - task.data["arrived"])
        self._retry_waiting(key.sku)
        return ", ".join(done) or "no free location"

    # ----- counts --------------------------------------------------------------------------------
    def _exception_count(self, location: str, sku: str, reason: str) -> None:
        if not any(c.location == location and c.status == "OPEN" for c in self.counts.values()):
            self.create_count(location, sku, reason)

    def create_count(
        self, location: str, sku: str, reason: str = "MANUAL", recount_of: str | None = None
    ) -> Count:
        count = Count(self._id("CNT"), location, sku, reason, self.inv.tick, recount_of=recount_of)
        self.counts[count.count_id] = count
        self._task("COUNT", count_id=count.count_id, location=location)
        return count

    def _schedule_counts(self) -> None:
        """ABC cycle counting: A pick faces are drawn most often (weights 6 : 3 : 1)."""
        open_locs = {c.location for c in self.counts.values() if c.status == "OPEN"}
        faces = [
            i
            for i in sorted(self.inv.items.values(), key=lambda i: i.sku)
            if i.home not in open_locs
        ]
        weights = [{"A": 6, "B": 3, "C": 1}[i.abc] for i in faces]
        for item in self.rng.choices(faces, weights=weights, k=self.cfg["counts_per_hour"]):
            if item.home not in open_locs:
                open_locs.add(item.home)
                self.create_count(item.home, item.sku, "CYCLE")

    def submit_count(self, count_id: str, counted: int, user: str) -> Count:
        """A blind count: the counter reports what is on the shelf; the system compares."""
        count = self.counts[count_id]
        if count.status != "OPEN":
            raise InventoryError(f"{count_id} is {count.status.lower()}")
        sku, loc = count.sku, count.location
        expected = sum(q for k, q in self.inv.rows(sku=sku, location=loc) if k.status == AVAILABLE)
        count.expected, count.counted, count.counter = expected, counted, user
        count.variance = counted - expected
        count.value = round(count.variance * self.inv.items[sku].unit_cost, 2)
        tol = max(1, math.ceil(expected * self.cfg["count_tolerance_pct"] / 100))
        self.metrics["counts_done"] += 1
        if count.variance == 0:
            count.status = "MATCHED"
            self.metrics["counts_accurate"] += 1
        elif abs(count.variance) <= tol and count.recount_of is None:
            self._book_count(count, "auto (within tolerance)")
            self.metrics["counts_accurate"] += 1
        elif count.recount_of is None:
            count.status = "COUNTED"
            self.create_count(loc, sku, "RECOUNT", recount_of=count_id)
        elif abs(count.value) < self.cfg["auto_approve_value"]:
            self._book_count(count, "auto (recount confirmed, below value limit)")
        else:
            count.status = "PENDING_APPROVAL"
            self._alert(
                "warning",
                f"Count {count_id}: {count.variance:+d} {sku} at {loc} "
                f"(${count.value:+.2f}) needs a supervisor",
                count_id,
            )
        return count

    def _book_count(self, count: Count, decided_by: str) -> None:
        """Adjust the system to the count, using the item's oldest lot at the location."""
        lots = sorted(
            k.lot
            for k, _ in self.inv.rows(sku=count.sku, location=count.location, status=AVAILABLE)
        )
        lot = lots[0] if lots else self._new_lot(count.sku)
        delta = count.variance
        if delta < 0:  # never below what is allocated: those orders will short-pick instead
            delta = max(delta, -(self.inv.free_at(count.sku, count.location, lot)))
        if delta:
            self.inv.adjust(
                count.sku,
                count.location,
                lot,
                delta,
                "COUNT_VARIANCE",
                ref=count.count_id,
                user=count.counter or "system",
                physical=False,
            )
        count.status, count.decided_by = "ADJUSTED", decided_by
        self._check_pick_face(count.sku)

    def decide_count(self, count_id: str, approve: bool, user: str) -> Count:
        count = self.counts[count_id]
        if count.status != "PENDING_APPROVAL":
            raise InventoryError(f"{count_id} is not waiting for approval")
        if approve:
            self._book_count(count, user)
        else:
            count.status, count.decided_by = "REJECTED", user
            self.create_count(count.location, count.sku, "MANUAL")
        return count

    def _do_count(self, task: Task, user: str) -> str:
        count = self.counts[task.data["count_id"]]
        physical = sum(
            q
            for k, q in self.inv.rows(sku=count.sku, location=count.location, physical=True)
            if k.status == AVAILABLE
        )
        self.submit_count(count.count_id, physical, user)
        return f"counted {physical} (system {count.expected})"

    # ----- holds, expiry, quarantine, returns --------------------------------------------------
    def hold(self, sku: str, lot: str | None, reason: str, user: str, release: bool = False) -> int:
        """Hold (or release) all free units of an item, or one lot of it, e.g. a supplier recall."""
        old, new = (StockStatus.HOLD, AVAILABLE) if release else (AVAILABLE, StockStatus.HOLD)
        moved = 0
        for key, qty in list(self.inv.rows(sku=sku, status=old, lot=lot)):
            if self.inv.locations[key.location].type not in (
                LocationType.PICK,
                LocationType.RESERVE,
                LocationType.STAGING,
            ):
                continue
            free = (
                qty if key.lpn or old != AVAILABLE else self.inv.free_at(sku, key.location, key.lot)
            )
            if free > 0:
                self.inv.set_status(
                    sku,
                    key.location,
                    key.lot,
                    free,
                    new,
                    old,
                    reason=reason,
                    user=user,
                    lpn=key.lpn,
                )
                moved += free
        return moved

    def _expiry_check(self) -> None:
        today = self.inv.date()
        soon = today + dt.timedelta(days=self.cfg["near_expiry_days"])
        for (sku, lot), info in sorted(self.inv.lots.items()):
            if not info.expiry:
                continue
            if info.expiry < today:
                for key, qty in list(self.inv.rows(sku=sku, lot=lot, status=AVAILABLE)):
                    free = qty if key.lpn else self.inv.free_at(sku, key.location, lot)
                    if free > 0 and self.inv.locations[key.location].type in (
                        LocationType.PICK,
                        LocationType.RESERVE,
                    ):
                        self.inv.set_status(
                            sku,
                            key.location,
                            lot,
                            free,
                            StockStatus.EXPIRED,
                            reason="EXPIRED",
                            lpn=key.lpn,
                        )
                        self._task("QUARANTINE", sku=sku, lot=lot)
                        self._alert("warning", f"Lot {lot} of {sku} expired ({free} units)", sku)
            elif info.expiry <= soon and (sku, lot) not in self._expiry_warned:
                if any(True for _ in self.inv.rows(sku=sku, lot=lot, status=AVAILABLE)):
                    self._alert("info", f"Lot {lot} of {sku} expires {info.expiry:%d %b}", sku)
                    self._expiry_warned.add((sku, lot))

    def _do_quarantine(self, task: Task, user: str) -> str:
        """Move expired / damaged units to quarantine and scrap them."""
        sku, lot = task.data["sku"], task.data["lot"]
        scrapped = 0
        for status in (StockStatus.EXPIRED, StockStatus.DAMAGED):
            for key, qty in list(self.inv.rows(sku=sku, lot=lot, status=status)):
                self.inv.adjust(
                    sku,
                    key.location,
                    lot,
                    -qty,
                    "EXPIRED" if status == StockStatus.EXPIRED else "DAMAGED",
                    ref=task.task_id,
                    user=user,
                    status=status,
                    lpn=key.lpn,
                )
                scrapped += qty
        return f"scrapped {scrapped}"

    def _maybe_return(self, order_id: str, lines: list[tuple[str, int]]) -> None:
        """A small share of shipped lines comes back some hours later (one unit each)."""
        reasons = ["changed mind", "wrong size", "damaged in transit", "not as described"]
        for sku, units in lines:
            if units and self.rng.random() < self.cfg["return_rate"]:
                arrives = self.inv.tick + self.rng.randint(4, 24) * self.tph
                rma = Return(self._id("RMA"), order_id, sku, 1, arrives, self.rng.choice(reasons))
                rec = self.out.orders.get(order_id)
                rma.customer_id = rec.customer_id if rec else None
                self.returns[rma.rma_id] = rma

    def _returns_arriving(self) -> None:
        for rma in sorted(self.returns.values(), key=lambda r: r.rma_id):
            if rma.status == "EXPECTED" and self.inv.tick >= rma.due:
                rma.lot = self._new_lot(rma.sku)
                self.inv.receive(
                    rma.sku,
                    rma.qty,
                    rma.lot,
                    self._expiry(rma.sku),
                    "RET-01",
                    None,
                    ref=rma.rma_id,
                    status=StockStatus.QC_HOLD,
                )
                rma.status, rma.received_at = "RECEIVED", self.inv.tick
                self._task("RETURN", rma=rma.rma_id)

    def inspect_return(self, rma_id: str, condition: str, note: str | None, user: str) -> Return:
        """A person inspects a received return in the app: grade it, restock or scrap it."""
        rma = self.returns.get(rma_id)
        if rma is None:
            raise InventoryError(f"unknown return {rma_id}")
        if condition not in RETURN_CONDITIONS:
            raise InventoryError(f"unknown condition {condition}")
        if rma.status != "RECEIVED":
            raise InventoryError(f"{rma_id} is {rma.status.lower()}, not waiting for inspection")
        task = next(
            (t for t in self.tasks.values() if t.type == "RETURN" and t.data.get("rma") == rma_id),
            None,
        )
        if task and task.status == "IN_PROGRESS":
            raise InventoryError(f"{task.assignee} is inspecting {rma_id} now")
        if task is None:
            task = self._task("RETURN", rma=rma_id)
        task.status, task.assignee, task.done_at = "DONE", user, self.inv.tick
        task.result = self._do_return(task, user, condition, note)
        return rma

    def _do_return(
        self, task: Task, user: str, condition: str | None = None, note: str | None = None
    ) -> str:
        rma = self.returns[task.data["rma"]]
        # Associates grade by what they find: a parcel damaged in transit is damaged; the rest
        # comes back as new (the simulation has no hidden condition beyond the return reason).
        condition = condition or ("DAMAGED" if rma.reason == "damaged in transit" else "NEW")
        ok = RETURN_CONDITIONS[condition][0]
        rma.condition, rma.inspected_by, rma.inspected_at = condition, user, self.inv.tick
        rma.note = note
        if ok:
            self.inv.set_status(
                rma.sku,
                "RET-01",
                rma.lot,
                rma.qty,
                AVAILABLE,
                StockStatus.QC_HOLD,
                reason="RETURN_RESTOCK",
                ref=rma.rma_id,
                user=user,
            )
            item = self.inv.items[rma.sku]
            self.inv.move(
                rma.sku,
                rma.qty,
                "RET-01",
                item.home,
                rma.lot,
                TxnType.RETURN,
                ref=rma.rma_id,
                user=user,
            )
            rma.status = "RESTOCKED"
            self._retry_waiting(rma.sku)
        else:
            self.inv.adjust(
                rma.sku,
                "RET-01",
                rma.lot,
                -rma.qty,
                "RETURN_SCRAP",
                ref=rma.rma_id,
                user=user,
                status=StockStatus.QC_HOLD,
            )
            rma.status = "SCRAPPED"
        return rma.status.lower()

    # ----- simulated reality: shrinkage -------------------------------------------------------
    def _shrinkage(self) -> None:
        faces = sorted(self.inv.items.values(), key=lambda i: i.sku)
        for item in faces:
            r = self.rng.random()
            keys = [k for k, q in self.inv.rows(sku=item.sku, location=item.home, physical=True)]
            if not keys:
                continue
            key = keys[0]
            if r < self.cfg["shrinkage_per_hour"]:
                self.inv.shelf_change(key, -self.rng.randint(1, 3))
            elif r < self.cfg["shrinkage_per_hour"] + self.cfg["found_per_hour"]:
                self.inv.shelf_change(key, self.rng.randint(1, 2))

    # ----- labour ----------------------------------------------------------------------------
    def _task(self, type_: str, **data) -> Task:
        task = Task(self._id("T"), type_, self.inv.tick, data)
        self.tasks[task.task_id] = task
        return task

    def _task_location(self, task: Task) -> tuple[int, int]:
        d = task.data
        code = d.get("location") or d.get("dock")
        if not code and d.get("sku"):
            code = self.inv.items[d["sku"]].home
        loc = self.inv.locations.get(code or "RET-01")
        return (loc.x, loc.y) if loc else (40, 2)

    def _labour(self) -> None:
        handlers = {
            "RECEIVE": self._do_receive,
            "PUTAWAY": self._do_putaway,
            "REPLENISH": self._do_replenish,
            "REPLENISH_URGENT": self._do_replenish,
            "COUNT": self._do_count,
            "RETURN": self._do_return,
            "QUARANTINE": self._do_quarantine,
            "PACK": self._do_pack,
            "AUDIT": self._do_audit,
            "LOAD": self._do_load,
            "PUTBACK": self._do_putback,
        }
        for name, a in sorted(self.associates.items()):
            task = self.tasks.get(a["task"]) if a["task"] else None
            if task and self.inv.tick >= a["until"]:
                try:
                    task.result = handlers[task.type](task, name)
                    task.status = "DONE"
                except InventoryError as err:
                    task.result, task.status = f"failed: {err}", "CANCELLED"
                task.done_at = self.inv.tick
                if task.data.get("_standard") is not None:
                    self.labour.done(name, task.type, task.data.pop("_standard"),
                                     task.started, self.inv.tick)  # fmt: skip
                a["task"] = None
                self.metrics[f"tasks_{task.type.lower()}"] += 1
        idle = [n for n, a in sorted(self.associates.items()) if a["task"] is None]
        if not idle:
            return
        open_tasks = sorted(
            (
                t
                for t in self.tasks.values()
                if t.status == "OPEN" and self.cfg["auto_tasks"].get(t.type, True)
            ),
            key=lambda t: (t.priority, t.created, t.task_id),
        )
        taken: set[str] = set()
        for name in idle:  # each crew member takes the most urgent task of their crew
            a = self.associates[name]
            task = next(
                (
                    t
                    for t in open_tasks
                    if t.task_id not in taken
                    and TASK_CREW.get(t.type, "inbound") == a["crew"]
                    and a.get("station") in (None, t.data.get("location"))
                ),
                None,
            )
            if task is None:
                continue
            taken.add(task.task_id)
            x, y = self._task_location(task)
            walk = (abs(a["x"] - x) + abs(a["y"] - y)) / self.cfg["walk_m_per_tick"]
            standard = self.labour.standard_ticks(task.type, walk, task.data.get("units", 1))
            task.data["_standard"] = standard  # booked as earned time when done
            a["task"], a["until"], a["x"], a["y"] = (
                task.task_id,
                self.inv.tick + self.labour.actual_ticks(name, standard),
                x,
                y,
            )
            task.status, task.assignee, task.started = "IN_PROGRESS", name, self.inv.tick
        for t in [
            t
            for t in self.tasks.values()
            if t.status in ("DONE", "CANCELLED") and self.inv.tick - (t.done_at or 0) > 4 * self.tph
        ]:
            del self.tasks[t.task_id]  # keep the task list short; the ledger keeps the history

    def _do_pack(self, task: Task, user: str) -> str:
        if self.out.orders.get(task.data["order"], None) is None:
            return "order gone"
        if self.out.orders[task.data["order"]].status != "AT_PACK":
            return f"order {self.out.orders[task.data['order']].status.lower()}"
        cartons = self.out.pack(task.data["order"], user)
        return f"{len(cartons)} carton(s)"

    def _do_audit(self, task: Task, user: str) -> str:
        carton = self.out.cartons.get(task.data["sscc"])
        if carton is None or carton.status == "CANCELLED":
            return "carton cancelled"
        self.out.audit(carton.sscc, user)
        return "corrected"

    def _do_load(self, task: Task, user: str) -> str:
        carton = self.out.cartons.get(task.data["sscc"])
        if carton is None or carton.status != "IN_LANE":
            return "not in the lane"
        return f"on {self.out.load(carton.sscc, user).trip}"

    def _do_putback(self, task: Task, user: str) -> str:
        units = self.out.put_back(task.data["plates"], task.data["order"], user)
        return f"{units} units back on the shelf"

    def _do_receive(self, task: Task, user: str) -> str:
        po = self.pos[task.data["po"]]
        plate = next(p for p in po.asn if p["sscc"] == task.data["sscc"])
        if plate["received"]:
            return "already received"
        damaged = 0
        if self.rng.random() < self.cfg["damage_on_receipt"]:
            damaged = self.rng.randint(1, max(1, plate["qty"] // 10))
        return self.receive_plate(
            po.po_id, plate["sscc"], plate["qty"], damaged, user=user, task=task
        )

    # ----- the hourly and per-tick cycle ----------------------------------------------------------
    def step(self, tick: int) -> None:
        self.inv.tick = tick
        if tick % self.tph == 0 and tick > 0:
            self._hourly()
        self._trucks()
        self.out.step()
        if tick % 10 == 0:
            rf.expire_claims(self)  # handheld claims left unconfirmed go back to the queue
        self._labour()

    def _hourly(self) -> None:
        alpha = 0.2  # exponential smoothing of units picked per hour, per SKU
        for sku in self.inv.items:
            self.demand[sku] = (1 - alpha) * self.demand[sku] + alpha * self._hour_units.get(sku, 0)
        self._hour_units.clear()
        if (self.inv.tick // self.tph) % 24 == 0:
            self._classify_abc()
        self._plan_purchases()
        self._schedule_counts()
        self._shrinkage()
        self._expiry_check()
        self._returns_arriving()
        for sku in sorted(self.inv.items):
            self._check_pick_face(sku)

    # ----- reporting -------------------------------------------------------------------------
    def kpis(self) -> dict:
        inv = self.inv
        on_hand_units = value = 0
        for k, q in inv.rows():
            loc = inv.locations[k.location]
            if loc.type != LocationType.ROBOT:
                on_hand_units += q
                value += q * inv.items[k.sku].unit_cost
        stockouts = sum(1 for s in inv.items if inv.atp(s) <= 0)
        m = self.metrics
        done = m["counts_done"]
        open_tasks = Counter(
            t.type for t in self.tasks.values() if t.status in ("OPEN", "IN_PROGRESS")
        )
        return {
            "skus": len(inv.items),
            "locations": sum(1 for loc in inv.locations.values() if loc.type != LocationType.ROBOT),
            "units_on_hand": on_hand_units,
            "inventory_value": round(value, 2),
            "stockouts": stockouts,
            "orders_waiting_stock": len(self.waiting),
            "fill_rate": round(  # units picked / units the robots were sent for
                m["units_picked"] / max(1, m["units_picked"] + m["units_short"]), 4
            ),
            "units_short": m["units_short"],
            "inventory_record_accuracy": round(m["counts_accurate"] / done, 4) if done else None,
            "counts_done": done,
            "counts_pending_approval": sum(
                1 for c in self.counts.values() if c.status == "PENDING_APPROVAL"
            ),
            "open_purchase_orders": sum(1 for p in self.pos.values() if p.status != "CLOSED"),
            "trucks_at_dock": sum(
                1 for p in self.pos.values() if p.status in ("AT_DOCK", "RECEIVING")
            ),
            "dock_to_stock_ticks": round(sum(self.dock_to_stock) / len(self.dock_to_stock))
            if self.dock_to_stock
            else None,
            "open_tasks": dict(open_tasks),
            "on_hold_units": sum(q for k, q in inv.rows() if k.status != AVAILABLE),
            "outbound": self.out.kpis(),
        }

"""Outbound: from an allocated customer order to a carton on a carrier's truck.

    order ─► customer, ship-to, carrier service, planned departure (the truck it must catch)
          ─► WAITING_STOCK / ON_HOLD / READY ─► RELEASED to the robots (continuously, or in waves)
          ─► PICKING ─► AT_PACK: the robot drops the order's tote at a packing station
          ─► PACK: cartons chosen by volume and weight, weighed (check), SSCC + shipping label,
                   sorted to the carrier's lane
          ─► LOAD onto the carrier's trailer at its shipping door
          ─► the truck leaves at its scheduled hour: SHIPPED, manifest, ship confirmation

Exceptions: hold and release (credit check, operator), cancel (picked units are put back),
partial release with a backorder when a customer accepts it, short picks backordered, and orders
that miss their truck roll over to the next one (the late shipment is counted).

The robot's own deadline (pick-by, from the order priority) is unchanged, so the trained
prediction models keep seeing the deadlines they learnt on; the planned departure is chosen
after it (pick-by + packing time), and the shipping KPIs are measured against that departure.
"""

from __future__ import annotations

import random
import zlib
from collections import Counter, deque
from dataclasses import asdict, dataclass, field

from wms.master import Carrier, Customer, carriers, customers
from wms.model import TxnType

# Carton types: (code, inside volume in litres, tare kg, max gross kg). Filled to 80 % at most.
CARTONS = [("S", 6.0, 0.15, 5.0), ("M", 18.0, 0.3, 12.0), ("L", 40.0, 0.55, 20.0)]
FILL = 0.8
SERVICE_OF_PRIORITY = {"HIGH": "EXP", "MEDIUM": "STD", "LOW": "ECO"}
PRIORITY_RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
OPEN = ("WAITING_STOCK", "READY", "ON_HOLD", "RELEASED", "PICKING", "AT_PACK", "PACKED", "LOADED")
FINAL = ("SHIPPED", "CANCELLED")


class OutboundError(ValueError):
    """A request the order's current state does not allow."""


@dataclass
class OrderLine:
    line: int
    sku: str
    ordered: int
    allocated: int = 0
    picked: int = 0
    short: int = 0  # missing at the shelf when picked
    backordered: int = 0
    shipped: int = 0


@dataclass
class CustomerOrder:
    order_id: str
    customer_id: str
    carrier: str
    priority: str
    source: str
    created: int
    pick_by: int  # the robot's deadline
    promised: int  # departure tick promised to the customer (on-time shipping is measured here)
    departure: int  # departure it is planned on now (moves on when a truck is missed)
    lines: list[OrderLine]
    status: str = "READY"
    parent: str | None = None  # backorder: the order it completes
    hold_reason: str | None = None
    hold_until: int | None = None  # automatic release (simulated credit check)
    released: int | None = None
    wave: str | None = None
    station: str | None = None
    at_pack: int | None = None
    packed: int | None = None
    loaded: int | None = None
    shipped: int | None = None
    cartons: list[str] = field(default_factory=list)
    partial: bool = False
    missed: int = 0  # trucks missed
    cancel_reason: str | None = None
    history: list[dict] = field(default_factory=list)

    def log(self, tick: int, event: str, user: str = "system", note: str | None = None) -> None:
        self.history.append({"tick": tick, "event": event, "user": user, "note": note})

    @property
    def done(self) -> int | None:
        return self.shipped if self.status == "SHIPPED" else self.history[-1]["tick"]


@dataclass
class Carton:
    sscc: str
    order_id: str
    carrier: str
    size: str
    seq: int  # carton n of `of`
    of: int
    contents: list[dict]  # {sku, lot, qty}
    weight_kg: float  # expected gross weight
    scale_kg: float  # weighed
    check: str  # PASS | FAIL | AUDITED
    tracking: str
    location: str
    status: str = "PACKED"  # PACKED | IN_LANE | LOADED | SHIPPED | CANCELLED
    packed_by: str | None = None
    packed_at: int | None = None
    loaded_at: int | None = None
    trip: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Trip:
    trip_id: str
    carrier: str
    door: str
    departs: int
    cutoff: int
    status: str = "SCHEDULED"  # SCHEDULED | DEPARTED
    cartons: list[str] = field(default_factory=list)
    shipped_units: int = 0
    weight_kg: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Backorder:
    bo_id: str
    order_id: str
    customer_id: str
    priority: str
    sku: str
    qty: int
    created: int
    status: str = "OPEN"  # OPEN | RELEASED | CANCELLED
    child: str | None = None  # the follow-up order that ships it

    def to_dict(self) -> dict:
        return asdict(self)


class Outbound:
    def __init__(self, warehouse, rng: random.Random) -> None:
        self.wh = warehouse
        self.inv = warehouse.inv
        self.cfg = warehouse.cfg
        self.rng = rng
        self.tph = warehouse.tph
        self.customers: dict[str, Customer] = customers()
        self.carriers: dict[str, Carrier] = carriers()
        self.orders: dict[str, CustomerOrder] = {}
        self.cartons: dict[str, Carton] = {}
        self.trips: dict[str, Trip] = {}
        self.waves: deque = deque(maxlen=200)
        self.backorders: dict[str, Backorder] = {}
        self.confirmations: deque = deque(maxlen=500)  # ship confirmations for an ERP
        self._children: deque = deque()  # backorder groups waiting for the simulator's order
        self._new_orders: list[dict] = []
        self._next_wave = 0
        self._due = 0  # earliest departure not yet processed (no scan of trips before then)
        self._held: set[str] = set()  # orders on hold with an automatic release
        self._waiting_alerted: set[str] = set()
        self._order_to_ship: deque = deque(maxlen=500)  # ticks from order to truck
        self.metrics = warehouse.metrics

    # ----- time --------------------------------------------------------------------------------
    def ticks(self, minutes: float) -> int:
        return max(1, round(minutes * self.tph / 60))

    def clock(self, tick: int | None) -> str | None:
        if tick is None:
            return None
        minutes = (tick % (24 * self.tph)) * 60 // self.tph
        return f"{self.inv.date(tick):%a %d %b} {minutes // 60:02d}:{minutes % 60:02d}"

    def next_departure(self, carrier: str, ready_at: int) -> int:
        """The first departure of the carrier whose cut-off is not before `ready_at`."""
        day = 24 * self.tph
        cutoff = self.ticks(self.cfg["cutoff_minutes"])
        d = ready_at // day
        while True:
            for hour in self.carriers[carrier].departures:
                departs = d * day + hour * self.tph
                if departs - cutoff >= ready_at:
                    return departs
            d += 1

    def trip(self, carrier: str, departs: int) -> Trip:
        c = self.carriers[carrier]
        hour = departs % (24 * self.tph) // self.tph
        trip_id = f"{carrier}-{self.inv.date(departs):%m%d}-{hour:02d}00"
        if trip_id not in self.trips:
            self.trips[trip_id] = Trip(
                trip_id, carrier, c.door, departs, departs - self.ticks(self.cfg["cutoff_minutes"])
            )
            self._due = min(self._due, departs)
        return self.trips[trip_id]

    # ----- order intake --------------------------------------------------------------------------
    def register(self, order, waiting: bool) -> CustomerOrder:
        """A new simulator order (already allocated by the warehouse)."""
        priority = order.priority.value
        parent = None
        if order.source == "BACKORDER" and self._children:
            parent, customer_id, bo_ids = self._children.popleft()
            for bo in bo_ids:
                self.backorders[bo].child = order.order_id
        else:
            ids = sorted(self.customers)
            customer_id = ids[zlib.crc32(order.order_id.encode()) % len(ids)]
        carrier = SERVICE_OF_PRIORITY[priority]
        ready = order.deadline + self.ticks(self.cfg["pack_buffer_minutes"])
        departs = self.next_departure(carrier, max(ready, self.inv.tick))
        allocated = self.wh.ordered.get(order.order_id, {})
        rec = CustomerOrder(
            order.order_id,
            customer_id,
            carrier,
            priority,
            order.source,
            self.inv.tick,
            order.deadline,
            departs,
            departs,
            [
                OrderLine(i, it.product_id, it.quantity, allocated.get(i, [None, 0])[1])
                for i, it in enumerate(order.items)
            ],
            status="WAITING_STOCK" if waiting else "READY",
            parent=parent,
        )
        self.orders[rec.order_id] = rec
        self.trip(carrier, departs)
        rec.log(self.inv.tick, "CREATED", note=f"{order.source.lower()} order, {rec.status}")
        if order.source == "GENERATOR" and self.rng.random() < self.cfg["credit_hold_rate"]:
            lo, hi = self.cfg["hold_minutes"]
            self._hold(rec, "credit check", "system")
            rec.hold_until = self.inv.tick + self.ticks(self.rng.uniform(lo, hi))
            self._held.add(rec.order_id)
        elif rec.status == "READY":
            self._release_continuous(rec)
        return rec

    def stock_complete(self, order_id: str) -> None:
        """All lines of a waiting order are now allocated (stock arrived)."""
        rec = self.orders.get(order_id)
        if rec is None:
            return
        for i, (_, units) in self.wh.ordered.get(order_id, {}).items():
            rec.lines[i].allocated = units
        if rec.status == "WAITING_STOCK":
            rec.status = "READY"
            rec.log(self.inv.tick, "STOCK_ALLOCATED")
            self._release_continuous(rec)

    def releasable(self, order_id: str) -> bool:
        rec = self.orders.get(order_id)
        return rec is not None and rec.status == "RELEASED"

    # ----- release: continuous or in waves ------------------------------------------------------
    def _release(self, rec: CustomerOrder, how: str, user: str = "system") -> None:
        rec.status, rec.released = "RELEASED", self.inv.tick
        rec.log(self.inv.tick, "RELEASED", user, how)

    def _release_continuous(self, rec: CustomerOrder) -> None:
        if self.cfg["release_mode"] == "continuous":
            self._release(rec, "continuous release")

    def set_release_mode(self, mode: str) -> None:
        self.cfg["release_mode"] = mode
        self._next_wave = self.inv.tick
        if mode == "continuous":  # orders that were waiting for their wave go now
            for rec in self.orders.values():
                if rec.status == "READY":
                    self._release(rec, "continuous release")

    def _waves(self) -> None:
        """Wave mode: every `wave_minutes` release the ready orders, earliest truck first; hot
        orders (robot deadline before the next wave) are checked every simulated minute."""
        tick = self.inv.tick
        if self.cfg["release_mode"] == "continuous" or (
            tick < self._next_wave and tick % self.ticks(1)
        ):
            return
        interval = self.ticks(self.cfg["wave_minutes"])
        for rec in [r for r in self.orders.values() if r.status == "READY"]:
            if rec.pick_by - tick <= interval:
                self._release(rec, "hot order (deadline before the next wave)")
        if tick < self._next_wave:
            return
        self._next_wave = tick + interval
        ready = sorted(
            (r for r in self.orders.values() if r.status == "READY"),
            key=lambda r: (r.departure, PRIORITY_RANK[r.priority], r.created, r.order_id),
        )[: self.cfg["wave_max_orders"]]
        if not ready:
            return
        wave_id = self.wh._id("WAVE")
        for rec in ready:
            rec.wave = wave_id
            self._release(rec, f"wave {wave_id}")
        self.waves.appendleft(
            {
                "wave_id": wave_id,
                "tick": tick,
                "time": self.clock(tick),
                "orders": [r.order_id for r in ready],
                "units": sum(ln.ordered for r in ready for ln in r.lines),
                "departures": sorted({self.clock(r.departure) for r in ready}),
            }
        )
        self.metrics["waves"] += 1

    # ----- picking and packing -----------------------------------------------------------------
    def picked(self, order_id: str, line: int, picked: int, short: int) -> None:
        rec = self.orders.get(order_id)
        if rec is None:
            return
        if rec.status == "RELEASED":
            rec.status = "PICKING"
            rec.log(self.inv.tick, "PICKING")
        ln = rec.lines[line]
        ln.picked += picked
        if short:
            ln.short += short
            if self.customers[rec.customer_id].allow_partial:
                self._backorder(rec, ln, short, "short pick")
            else:
                rec.log(self.inv.tick, "SHORT_SHIPPED", note=f"{ln.sku}: {short} missing")

    def tote(self, order_id: str) -> str:
        return f"TOTE-{order_id}"

    def delivered(self, order_id: str, robot: str, station: str) -> int:
        """The robot reached the packing station: the tote waits for a packer."""
        units = self.inv.drop(order_id, robot, station, self.tote(order_id))
        rec = self.orders.get(order_id)
        if rec is None:
            return units
        rec.status, rec.station, rec.at_pack = "AT_PACK", station, self.inv.tick
        rec.log(self.inv.tick, "AT_PACK", robot, f"{units} units at {station}")
        if units:
            self.wh._task("PACK", order=order_id, location=station, units=units)
        else:  # everything was short: nothing to ship
            self._cancel_backorders(rec)
            rec.status = "CANCELLED"
            rec.cancel_reason = "nothing picked (all lines short)"
            rec.log(self.inv.tick, "CANCELLED", note=rec.cancel_reason)
        return units

    def cartonise(self, contents: list[dict]) -> list[tuple[str, list[dict]]]:
        """Split the tote into cartons: biggest units first into the largest carton until full,
        then each carton gets the smallest size its contents fit."""
        units = []
        for row in contents:
            item = self.inv.items[row["sku"]]
            units += [(item.volume_l, item.weight_kg, row["sku"], row["lot"])] * row["qty"]
        units.sort(key=lambda u: (-u[0], u[2], u[3]))
        _, big_l, big_tare, big_max = CARTONS[-1]
        boxes: list[list] = []
        for u in units:
            for box in boxes:
                vol = sum(x[0] for x in box) + u[0]
                kg = sum(x[1] for x in box) + u[1] + big_tare
                if vol <= big_l * FILL and kg <= big_max:
                    box.append(u)
                    break
            else:
                boxes.append([u])
        out = []
        for box in boxes:
            vol, kg = sum(x[0] for x in box), sum(x[1] for x in box)
            size = next(
                (c for c, litres, tare, mx in CARTONS if vol <= litres * FILL and kg + tare <= mx),
                CARTONS[-1][0],  # a single unit too big for every carton ships in the largest
            )
            rows = Counter((x[2], x[3]) for x in box)
            out.append(
                (size, [{"sku": s, "lot": lot, "qty": q} for (s, lot), q in sorted(rows.items())])
            )
        return out

    def pack(self, order_id: str, user: str) -> list[Carton]:
        """Pack the order's tote: cartons, weight check, labels, sort to the carrier's lane."""
        rec = self.orders[order_id]
        if rec.status != "AT_PACK":
            raise OutboundError(f"{order_id} is {rec.status}, not waiting at a packing station")
        tote = self.tote(order_id)
        contents = [
            {"sku": k.sku, "lot": k.lot, "qty": q}
            for k, q in self.inv.rows(location=rec.station, lpn=tote)
        ]
        if not contents:
            raise OutboundError(f"tote of {order_id} is empty")
        boxes = self.cartonise(contents)
        carrier = self.carriers[rec.carrier]
        made = []
        for n, (size, rows) in enumerate(boxes, start=1):
            sscc = self.inv.new_lpn()
            for r in rows:
                self.inv.move(
                    r["sku"],
                    r["qty"],
                    rec.station,
                    rec.station,
                    r["lot"],
                    TxnType.PACK,
                    from_lpn=tote,
                    to_lpn=sscc,
                    ref=order_id,
                    user=user,
                    order=order_id,
                )
            tare = next(t for c, _, t, _ in CARTONS if c == size)
            expected = round(
                tare + sum(self.inv.items[r["sku"]].weight_kg * r["qty"] for r in rows), 2
            )
            scale = expected * (1 + self.rng.gauss(0, 0.008))
            if self.rng.random() < self.cfg["mispack_rate"]:  # wrong or missing unit in the box
                any_unit = self.inv.items[rows[0]["sku"]].weight_kg
                scale += any_unit * self.rng.choice([-1, 1])
            scale = round(max(0.05, scale), 2)
            ok = abs(scale - expected) <= max(0.05, 0.03 * expected)
            self.wh.seq["tracking"] += 1
            carton = Carton(
                sscc,
                order_id,
                rec.carrier,
                size,
                n,
                len(boxes),
                rows,
                expected,
                scale,
                "PASS" if ok else "FAIL",
                f"{carrier.tracking_prefix}{self.wh.seq['tracking']:010d}",
                rec.station,
                packed_by=user,
                packed_at=self.inv.tick,
            )
            self.cartons[sscc] = carton
            rec.cartons.append(sscc)
            made.append(carton)
            self.metrics["cartons_packed"] += 1
            if ok:
                self._to_lane(carton, user)
            else:
                self.metrics["weight_check_failures"] += 1
                self.wh._task("AUDIT", order=order_id, sscc=sscc, location=rec.station)
                self.wh._alert(
                    "warning",
                    f"Weight check failed: carton {sscc} weighs {scale} kg, expected {expected}",
                    order_id,
                )
        rec.status, rec.packed = "PACKED", self.inv.tick
        rec.log(self.inv.tick, "PACKED", user, f"{len(boxes)} carton(s)")
        return made

    def audit(self, sscc: str, user: str) -> Carton:
        """Re-open a carton that failed the weight check, correct it, weigh again."""
        carton = self.cartons[sscc]
        if carton.check != "FAIL":
            raise OutboundError(f"carton {sscc} does not need an audit")
        carton.check, carton.scale_kg = "AUDITED", carton.weight_kg
        self.orders[carton.order_id].log(self.inv.tick, "AUDITED", user, sscc)
        self._to_lane(carton, user)
        return carton

    def _to_lane(self, carton: Carton, user: str) -> None:
        lane = f"LANE-{carton.carrier}"
        for r in carton.contents:
            self.inv.move(
                r["sku"],
                r["qty"],
                carton.location,
                lane,
                r["lot"],
                TxnType.MOVE,
                from_lpn=carton.sscc,
                to_lpn=carton.sscc,
                ref=carton.order_id,
                user=user,
                order=carton.order_id,
            )
        carton.location, carton.status = lane, "IN_LANE"
        self.wh._task("LOAD", order=carton.order_id, sscc=carton.sscc, location=lane)

    def load(self, sscc: str, user: str) -> Carton:
        carton = self.cartons.get(sscc)
        if carton is None:
            raise OutboundError(f"unknown carton {sscc}")
        if carton.status != "IN_LANE":
            raise OutboundError(f"carton {sscc} is {carton.status}, not waiting in a lane")
        c = self.carriers[carton.carrier]
        day = 24 * self.tph
        now = self.inv.tick
        departs = min(
            d * day + h * self.tph
            for d in (now // day, now // day + 1)
            for h in c.departures
            if d * day + h * self.tph > now
        )
        trip = self.trip(carton.carrier, departs)
        for r in carton.contents:
            self.inv.move(
                r["sku"],
                r["qty"],
                carton.location,
                c.door,
                r["lot"],
                TxnType.LOAD,
                from_lpn=sscc,
                to_lpn=sscc,
                ref=trip.trip_id,
                user=user,
                order=carton.order_id,
            )
        carton.location, carton.status = c.door, "LOADED"
        carton.loaded_at, carton.trip = now, trip.trip_id
        trip.cartons.append(sscc)
        rec = self.orders[carton.order_id]
        if all(self.cartons[s].status == "LOADED" for s in rec.cartons):
            rec.status, rec.loaded = "LOADED", now
            rec.log(now, "LOADED", user, f"trip {trip.trip_id}")
        return carton

    # ----- departures --------------------------------------------------------------------------
    def _departures(self) -> None:
        now = self.inv.tick
        if now < self._due:
            return
        for trip in sorted(self.trips.values(), key=lambda t: (t.departs, t.trip_id)):
            if trip.status != "DEPARTED" and trip.departs <= now:
                self._depart(trip)
        for carrier in self.carriers:
            self.trip(carrier, self.next_departure(carrier, now + 1))  # always show the next truck
        self._due = min(t.departs for t in self.trips.values() if t.status != "DEPARTED")

    def _depart(self, trip: Trip) -> None:
        now = self.inv.tick
        trip.status = "DEPARTED"
        orders = set()
        for sscc in trip.cartons:
            carton = self.cartons[sscc]
            trip.shipped_units += self.inv.ship_lpn(sscc, trip.door, carton.order_id, trip.trip_id)
            trip.weight_kg = round(trip.weight_kg + carton.scale_kg, 2)
            carton.status = "SHIPPED"
            orders.add(carton.order_id)
        for order_id in sorted(orders):
            rec = self.orders[order_id]
            if rec.status == "SHIPPED" or any(
                self.cartons[s].status != "SHIPPED" for s in rec.cartons
            ):
                continue
            rec.status, rec.shipped = "SHIPPED", now
            for ln in rec.lines:
                ln.shipped = sum(
                    r["qty"]
                    for s in rec.cartons
                    for r in self.cartons[s].contents
                    if r["sku"] == ln.sku
                )
            rec.log(now, "SHIPPED", "system", f"trip {trip.trip_id}")
            units = sum(ln.shipped for ln in rec.lines)
            self.metrics["orders_shipped"] += 1
            self.metrics["units_shipped"] += units
            self.metrics["orders_on_time"] += now <= rec.promised
            self._order_to_ship.append(now - rec.created)
            self.confirmations.appendleft(
                {
                    "order_id": order_id,
                    "customer_id": rec.customer_id,
                    "trip": trip.trip_id,
                    "carrier": rec.carrier,
                    "tracking": [self.cartons[s].tracking for s in rec.cartons],
                    "lines": [{"sku": ln.sku, "shipped": ln.shipped} for ln in rec.lines],
                    "tick": now,
                }
            )
            self.wh._maybe_return(order_id, [(ln.sku, ln.shipped) for ln in rec.lines])
        missed = 0
        for rec in self.orders.values():
            if rec.carrier == trip.carrier and rec.departure == trip.departs and rec.status in OPEN:
                missed += 1
                rec.missed += 1
                rec.departure = self.next_departure(rec.carrier, now + 1)
                self.trip(rec.carrier, rec.departure)
                rec.log(
                    now, "MISSED_TRUCK", note=f"{trip.trip_id}; now {self.clock(rec.departure)}"
                )
        self.metrics["missed_trucks"] += missed
        carrier = self.carriers[trip.carrier]
        self.wh._alert(
            "warning" if missed else "info",
            f"{carrier.name} {self.clock(trip.departs)} left with {len(trip.cartons)} cartons"
            + (f"; {missed} orders missed it" if missed else ""),
            trip.trip_id,
        )

    # ----- exceptions: hold, cancel, partial release, backorders ------------------------------
    def _hold(self, rec: CustomerOrder, reason: str, user: str) -> None:
        rec.status, rec.hold_reason = "ON_HOLD", reason
        self.metrics["holds"] += 1
        rec.log(self.inv.tick, "ON_HOLD", user, reason)

    def hold(self, order_id: str, reason: str, user: str) -> CustomerOrder:
        rec = self._get(order_id)
        if rec.status not in ("WAITING_STOCK", "READY", "RELEASED"):
            raise OutboundError(
                f"{order_id} is {rec.status}; only orders not yet picked can be held"
            )
        self._hold(rec, reason, user)
        return rec

    def release_hold(self, order_id: str, user: str) -> CustomerOrder:
        rec = self._get(order_id)
        if rec.status != "ON_HOLD":
            raise OutboundError(f"{order_id} is not on hold")
        rec.hold_reason = rec.hold_until = None
        self._held.discard(order_id)
        rec.status = "WAITING_STOCK" if order_id in self.wh.waiting else "READY"
        rec.log(self.inv.tick, "HOLD_RELEASED", user)
        if rec.status == "READY":
            self._release_continuous(rec)
        return rec

    def release_now(self, order_id: str, user: str) -> CustomerOrder:
        """Release a ready order to the robots ahead of its wave."""
        rec = self._get(order_id)
        if rec.status != "READY":
            raise OutboundError(f"{order_id} is {rec.status}, not ready for release")
        self._release(rec, "released by hand", user)
        return rec

    def ship_partial(self, order_id: str, user: str) -> CustomerOrder:
        """Release what is allocated now; the rest goes on backorder."""
        rec = self._get(order_id)
        if rec.status != "WAITING_STOCK":
            raise OutboundError(f"{order_id} is not waiting for stock")
        if not self.customers[rec.customer_id].allow_partial:
            raise OutboundError(f"{rec.customer_id} does not accept partial shipments")
        if not any(ln.allocated for ln in rec.lines):
            raise OutboundError("nothing is allocated yet; there is nothing to ship")
        for line, _, missing in self.wh.waiting.pop(order_id, []):
            self._backorder(rec, rec.lines[line], missing, "partial release")
        rec.partial = True
        rec.status = "READY"
        rec.log(self.inv.tick, "PARTIAL_RELEASE", user)
        if self.cfg["release_mode"] == "continuous" or user != "system":
            self._release(rec, "partial release", user)
        return rec

    def _backorder(self, rec: CustomerOrder, ln: OrderLine, qty: int, why: str) -> None:
        bo = Backorder(
            self.wh._id("BO"),
            rec.order_id,
            rec.customer_id,
            rec.priority,
            ln.sku,
            qty,
            self.inv.tick,
        )
        self.backorders[bo.bo_id] = bo
        ln.backordered += qty
        self.metrics["units_backordered"] += qty
        rec.log(self.inv.tick, "BACKORDER", note=f"{ln.sku} x{qty} ({why}) {bo.bo_id}")

    def _cancel_backorders(self, rec: CustomerOrder) -> None:
        for bo in self.backorders.values():
            if bo.order_id == rec.order_id and bo.status == "OPEN":
                bo.status = "CANCELLED"

    def cancel(self, order_id: str, reason: str, user: str) -> CustomerOrder:
        rec = self._get(order_id)
        if rec.status in ("PICKING",):
            raise OutboundError(f"{order_id} is on a robot; cancel it when it reaches packing")
        if rec.status in ("LOADED", "SHIPPED", "CANCELLED"):
            raise OutboundError(f"{order_id} is {rec.status}; it can no longer be cancelled")
        self.wh.cancel_order(order_id)
        plates = []
        if rec.status in ("AT_PACK", "PACKED"):
            tote = self.tote(order_id)
            plates = (
                [(rec.station, tote)] if any(self.inv.rows(location=rec.station, lpn=tote)) else []
            )
            for sscc in rec.cartons:
                carton = self.cartons[sscc]
                plates.append((carton.location, sscc))
                carton.status = "CANCELLED"
            for t in self.wh.tasks.values():
                if t.status == "OPEN" and t.data.get("order") == order_id:
                    t.status, t.result, t.done_at = "CANCELLED", "order cancelled", self.inv.tick
            if plates:
                self.wh._task("PUTBACK", order=order_id, location=plates[0][0], plates=plates)
        self._cancel_backorders(rec)
        self._held.discard(order_id)
        rec.status, rec.cancel_reason = "CANCELLED", reason
        self.metrics["orders_cancelled"] += 1
        rec.log(
            self.inv.tick,
            "CANCELLED",
            user,
            reason + (" (picked units put back)" if plates else ""),
        )
        return rec

    def put_back(self, plates: list, order_id: str, user: str) -> int:
        moved = 0
        for location, lpn in plates:
            for key, q in list(self.inv.rows(location=location, lpn=lpn)):
                home = self.inv.items[key.sku].home
                self.inv.move(
                    key.sku,
                    q,
                    location,
                    home,
                    key.lot,
                    TxnType.MOVE,
                    from_lpn=lpn,
                    ref=order_id,
                    user=user,
                )
                moved += q
                self.wh._retry_waiting(key.sku)
        return moved

    def take_new_orders(self) -> list[dict]:
        out, self._new_orders = self._new_orders, []
        return out

    def _backorders_due(self) -> None:
        """Open backorders whose stock is now available become a follow-up order."""
        by_parent: dict[str, list[Backorder]] = {}
        for bo in self.backorders.values():
            if bo.status == "OPEN":
                by_parent.setdefault(bo.order_id, []).append(bo)
        for parent, bos in sorted(by_parent.items()):
            ready = [b for b in bos if self.inv.atp(b.sku) >= b.qty]
            if not ready:
                continue
            for b in ready:
                b.status = "RELEASED"
            self._new_orders.append(
                {"priority": ready[0].priority, "items": [(b.sku, b.qty) for b in ready]}
            )
            self._children.append((parent, ready[0].customer_id, [b.bo_id for b in ready]))

    def _waiting_too_long(self) -> None:
        limit = self.ticks(self.cfg["backorder_after_minutes"])
        for order_id in sorted(self.wh.waiting):
            rec = self.orders.get(order_id)
            if rec is None or rec.status != "WAITING_STOCK" or self.inv.tick - rec.created < limit:
                continue
            if self.customers[rec.customer_id].allow_partial and any(
                ln.allocated for ln in rec.lines
            ):
                self.ship_partial(order_id, "system")
            elif order_id not in self._waiting_alerted:
                self._waiting_alerted.add(order_id)
                self.wh._alert(
                    "warning",
                    f"{order_id} has waited {self.cfg['backorder_after_minutes']} min for stock; "
                    "the customer takes complete orders only",
                    order_id,
                )

    # ----- the cycle ---------------------------------------------------------------------------
    def step(self) -> None:
        now = self.inv.tick
        for order_id in sorted(self._held):
            rec = self.orders[order_id]
            if rec.status == "ON_HOLD" and now >= rec.hold_until:
                self.release_hold(order_id, "system")
        if now % self.ticks(10) == 0:
            self._waiting_too_long()
            self._backorders_due()
        self._waves()
        self._departures()
        if now % self.tph == 0:
            self._prune()

    def _prune(self) -> None:
        """Keep a day of finished orders and two days of trips (the ledger keeps everything)."""
        now, day = self.inv.tick, 24 * self.tph
        for order_id in [
            k for k, r in self.orders.items() if r.status in FINAL and now - (r.done or now) > day
        ]:
            for sscc in self.orders[order_id].cartons:
                self.cartons.pop(sscc, None)
            del self.orders[order_id]
            self._waiting_alerted.discard(order_id)
        for trip_id in [
            k for k, t in self.trips.items() if t.status == "DEPARTED" and now - t.departs > 2 * day
        ]:
            del self.trips[trip_id]
        for bo_id in [
            k for k, b in self.backorders.items() if b.status != "OPEN" and now - b.created > day
        ]:
            del self.backorders[bo_id]

    # ----- views -------------------------------------------------------------------------------
    def _get(self, order_id: str) -> CustomerOrder:
        if order_id not in self.orders:
            raise OutboundError(f"unknown order {order_id}")
        return self.orders[order_id]

    def order_row(self, rec: CustomerOrder) -> dict:
        customer = self.customers[rec.customer_id]
        return {
            "order_id": rec.order_id,
            "status": rec.status,
            "priority": rec.priority,
            "source": rec.source,
            "customer_id": rec.customer_id,
            "customer": customer.name,
            "city": customer.city,
            "carrier": rec.carrier,
            "service": self.carriers[rec.carrier].service,
            "created": rec.created,
            "created_at": self.clock(rec.created),
            "pick_by_at": self.clock(rec.pick_by),
            "departure": rec.departure,
            "departure_at": self.clock(rec.departure),
            "promised_at": self.clock(rec.promised),
            "minutes_to_cutoff": round(
                (rec.departure - self.ticks(self.cfg["cutoff_minutes"]) - self.inv.tick)
                * 60
                / self.tph
            ),
            "units": sum(ln.ordered for ln in rec.lines),
            "lines": len(rec.lines),
            "cartons": len(rec.cartons),
            "hold_reason": rec.hold_reason,
            "partial": rec.partial,
            "backordered": sum(ln.backordered for ln in rec.lines),
            "missed": rec.missed,
            "parent": rec.parent,
            "wave": rec.wave,
            "station": rec.station,
            "shipped_at": self.clock(rec.shipped),
            "on_time": None if rec.shipped is None else rec.shipped <= rec.promised,
        }

    def order_detail(self, order_id: str) -> dict:
        rec = self._get(order_id)
        return {
            **self.order_row(rec),
            "customer_detail": self.customers[rec.customer_id].to_dict(),
            "carrier_detail": self.carriers[rec.carrier].to_dict(),
            "order_lines": [asdict(ln) for ln in rec.lines],
            "carton_detail": [
                self.carton_row(self.cartons[s]) for s in rec.cartons if s in self.cartons
            ],
            "backorders": [b.to_dict() for b in self.backorders.values() if b.order_id == order_id],
            "cancel_reason": rec.cancel_reason,
            "history": [{**h, "time": self.clock(h["tick"])} for h in rec.history],
        }

    def carton_row(self, carton: Carton) -> dict:
        return {
            **carton.to_dict(),
            "packed_at_time": self.clock(carton.packed_at),
            "loaded_at_time": self.clock(carton.loaded_at),
        }

    def trip_row(self, trip: Trip) -> dict:
        """orders_on_board: orders with cartons on this truck (some caught it before their
        planned one); waiting: orders planned on it that are not on board yet."""
        on_board = {self.cartons[s].order_id for s in trip.cartons if s in self.cartons}
        waiting = sum(
            1
            for r in self.orders.values()
            if r.carrier == trip.carrier
            and r.departure == trip.departs
            and r.status in OPEN
            and r.order_id not in on_board
        )
        late = sum(
            1 for o in on_board if o in self.orders and self.orders[o].promised < trip.departs
        )
        return {
            **trip.to_dict(),
            "carrier_name": self.carriers[trip.carrier].name,
            "service": self.carriers[trip.carrier].service,
            "departs_at": self.clock(trip.departs),
            "cutoff_at": self.clock(trip.cutoff),
            "minutes_to_departure": round((trip.departs - self.inv.tick) * 60 / self.tph),
            "cartons_loaded": len(trip.cartons),
            "orders_on_board": len(on_board),
            "orders_late": late,
            "orders_waiting": 0 if trip.status == "DEPARTED" else waiting,
        }

    def kpis(self) -> dict:
        m = self.metrics
        status = Counter(r.status for r in self.orders.values())
        shipped = m["orders_shipped"]
        o2s = self._order_to_ship
        return {
            "release_mode": self.cfg["release_mode"],
            "orders_by_status": dict(status),
            "orders_on_hold": status.get("ON_HOLD", 0),
            "pack_queue": status.get("AT_PACK", 0),
            "cartons_in_lanes": sum(1 for c in self.cartons.values() if c.status == "IN_LANE"),
            "cartons_loaded": sum(1 for c in self.cartons.values() if c.status == "LOADED"),
            "orders_shipped": shipped,
            "units_shipped": m["units_shipped"],
            "on_time_ship_rate": round(m["orders_on_time"] / shipped, 4) if shipped else None,
            "missed_trucks": m["missed_trucks"],
            "cartons_packed": m["cartons_packed"],
            "weight_check_failures": m["weight_check_failures"],
            "backorders_open": sum(1 for b in self.backorders.values() if b.status == "OPEN"),
            "units_backordered": m["units_backordered"],
            "orders_cancelled": m["orders_cancelled"],
            "order_to_ship_minutes": round(sum(o2s) / len(o2s) * 60 / self.tph) if o2s else None,
            "waves": m["waves"],
        }

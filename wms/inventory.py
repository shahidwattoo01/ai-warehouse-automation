"""Stock and its ledger: every unit is somewhere (location), in a lot, in a status, maybe on a
license plate; every change is a ledger transaction with who, when, why and a reference.

Two books are kept, as in reality:
* the **system stock** (what the WMS believes), changed only through transactions;
* the **physical stock** (what is really on the shelf), equal to it except where the simulation
  injects shrinkage or misplacement. Picks take physical units; when there are fewer than the
  system says, the pick is short and a count is triggered. Cycle counts compare both books.

Allocation reserves system stock for an order line (FEFO for expiry-controlled items, otherwise
FIFO by receipt), so the same unit is never promised twice.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

from wms.model import (
    STORAGE,
    Allocation,
    Item,
    Location,
    LocationType,
    Lot,
    StockKey,
    StockStatus,
    Txn,
    TxnType,
)

AVAILABLE = StockStatus.AVAILABLE


def _order(key: StockKey) -> tuple:
    """A stable order for iterating stock rows, so runs are reproducible."""
    return (key.sku, key.location, key.lot, key.status.value, key.lpn or "")


START_DATE = dt.date(
    2026, 9, 7
)  # day 1 of the simulated calendar (simulation/environment/calendar.py)


class InventoryError(ValueError):
    """An operation the stock does not allow (not enough stock, unknown location ...)."""


class Inventory:
    def __init__(self, ticks_per_day: int = 14_400, start_date: dt.date = START_DATE) -> None:
        self.ticks_per_day = ticks_per_day
        self.start_date = start_date
        self.tick = 0
        self.items: dict[str, Item] = {}
        self.by_gtin: dict[str, str] = {}  # GTIN-14 (unit or case) -> sku
        self.locations: dict[str, Location] = {}
        self.lots: dict[tuple[str, str], Lot] = {}
        self.stock: dict[StockKey, int] = defaultdict(int)  # system book
        self.physical: dict[StockKey, int] = defaultdict(int)  # real shelves
        self.allocations: dict[str, list[Allocation]] = {}  # order id -> lines
        self._allocated: dict[tuple[str, str, str], int] = defaultdict(int)  # sku, loc, lot
        self._alloc_sku: dict[str, int] = defaultdict(int)  # running totals of _allocated
        self._alloc_loc: dict[tuple[str, str], int] = defaultdict(int)
        self.serials: dict[str, dict] = {}  # serial -> sku, location, lot, state, order
        self._by_sku: dict[str, set[StockKey]] = defaultdict(set)  # indexes over both books
        self._by_loc: dict[str, set[StockKey]] = defaultdict(set)
        self.ledger: list[Txn] = []
        self._new_txns: list[Txn] = []  # not yet handed to the database writer
        self._lpn_seq = 0

    # ----- master data -----------------------------------------------------------------------
    def add_item(self, item: Item) -> None:
        from wms.barcodes import as_gtin14

        self.items[item.sku] = item
        self.by_gtin[as_gtin14(item.gtin)] = item.sku
        self.by_gtin[item.case_gtin] = item.sku

    def add_location(self, location: Location) -> None:
        self.locations[location.code] = location

    def date(self, tick: int | None = None) -> dt.date:
        return self.start_date + dt.timedelta(
            days=(self.tick if tick is None else tick) // self.ticks_per_day
        )

    def new_lpn(self) -> str:
        from wms.barcodes import sscc

        self._lpn_seq += 1
        return sscc(self._lpn_seq)

    def lot(self, sku: str, lot: str, expiry: dt.date | None = None) -> Lot:
        key = (sku, lot)
        if key not in self.lots:
            self.lots[key] = Lot(sku, lot, expiry, self.tick)
        return self.lots[key]

    # ----- queries -----------------------------------------------------------------------------
    def rows(self, sku=None, location=None, status=None, lot=None, lpn=None, physical=False):
        book = self.physical if physical else self.stock
        if sku:
            keys = sorted(self._by_sku.get(sku, ()), key=_order)
        elif location:
            keys = sorted(self._by_loc.get(location, ()), key=_order)
        else:
            keys = list(book)
        for key in keys:
            qty = book.get(key, 0)
            if qty == 0:
                continue
            if sku and key.sku != sku or location and key.location != location:
                continue
            if status and key.status != status or lot and key.lot != lot or lpn and key.lpn != lpn:
                continue
            yield key, qty

    def qty(self, sku: str, location: str | None = None, status=AVAILABLE, types=None) -> int:
        return sum(
            q
            for k, q in self.rows(sku=sku, location=location, status=status)
            if types is None or self.locations[k.location].type in types
        )

    def allocated(self, sku: str, location: str | None = None) -> int:
        if location is None:
            return self._alloc_sku.get(sku, 0)
        return self._alloc_loc.get((sku, location), 0)

    def _reserve(self, sku: str, location: str, lot: str, delta: int) -> None:
        """The only place allocations change (keeps the per-item totals right)."""
        key = (sku, location, lot)
        self._allocated[key] += delta
        self._alloc_sku[sku] += delta
        self._alloc_loc[(sku, location)] += delta
        if self._allocated[key] == 0:
            del self._allocated[key]

    def atp(self, sku: str) -> int:
        """Available to promise: available units in storage (pick + reserve, not blocked) minus
        what is already allocated to orders."""
        free = sum(
            q
            for k, q in self.rows(sku=sku, status=AVAILABLE)
            if self.locations[k.location].type in STORAGE and not self.locations[k.location].blocked
        )
        return free - self.allocated(sku)

    def free_at(self, sku: str, location: str, lot: str) -> int:
        """Available and not yet allocated, loose at a location (not on a license plate)."""
        key = StockKey(sku, location, lot, AVAILABLE)
        return self.stock.get(key, 0) - self._allocated.get((sku, location, lot), 0)

    def summary(self, sku: str) -> dict:
        by_status: dict[str, int] = defaultdict(int)
        for k, q in self.rows(sku=sku):
            if self.locations[k.location].type != LocationType.ROBOT:
                by_status[k.status.value] += q
        item = self.items[sku]
        return {
            "on_hand": sum(by_status.values()),
            "available": by_status.get("AVAILABLE", 0),
            "allocated": self.allocated(sku),
            "atp": self.atp(sku),
            "pick_face": self.qty(sku, location=item.home),
            "reserve": self.qty(sku, types=(LocationType.RESERVE,)),
            "by_status": dict(by_status),
        }

    # ----- the ledger --------------------------------------------------------------------------
    def _record(self, type_: TxnType, sku: str, qty: int, **kw) -> Txn:
        txn = Txn(len(self.ledger) + 1, self.tick, type_, sku, qty, **kw)
        self.ledger.append(txn)
        self._new_txns.append(txn)
        return txn

    def take_new_transactions(self) -> list[Txn]:
        out, self._new_txns = self._new_txns, []
        return out

    def _index(self, key: StockKey) -> None:
        self._by_sku[key.sku].add(key)
        self._by_loc[key.location].add(key)

    def _book(self, key: StockKey, delta: int, physical: bool = True) -> None:
        """The only place the system book changes (and the physical one with it, unless the
        shelf already has the difference, e.g. a count result)."""
        if self.stock.get(key, 0) + delta < 0:
            raise InventoryError(f"not enough {key.sku} at {key.location} (lot {key.lot})")
        self._index(key)
        self.stock[key] += delta
        if physical:
            self.physical[key] = max(0, self.physical[key] + delta)

    def shelf_change(self, key: StockKey, delta: int) -> None:
        """Change the physical book only: the shelf differs from the system (simulated
        shrinkage or found units). The system learns about it from picks and counts."""
        self._index(key)
        self.physical[key] = max(0, self.physical[key] + delta)

    def _location(self, code: str) -> Location:
        if code not in self.locations:
            raise InventoryError(f"unknown location {code}")
        return self.locations[code]

    def _check(self, sku: str, *locations: str) -> None:
        """Every movement names a known item and known locations (no stray rows in the books)."""
        if sku not in self.items:
            raise InventoryError(f"unknown item {sku}")
        for code in locations:
            self._location(code)

    def _move_serials(
        self,
        sku: str,
        qty: int,
        from_loc: str | None,
        to_loc: str,
        lot: str,
        state="IN_STOCK",
        order=None,
    ):
        if not self.items[sku].serial_controlled:
            return []
        moved = sorted(
            s
            for s, v in self.serials.items()
            if v["sku"] == sku
            and v["location"] == from_loc
            and v["lot"] == lot
            and v["state"] == "IN_STOCK"
            and (order is None or v["order"] in (None, order))
        )[:qty]
        for s in moved:
            self.serials[s].update(location=to_loc, state=state, order=order)
        return moved

    # ----- movements ---------------------------------------------------------------------------
    def receive(
        self,
        sku: str,
        qty: int,
        lot: str,
        expiry: dt.date | None,
        location: str,
        lpn: str | None,
        ref: str | None = None,
        user: str = "system",
        status=AVAILABLE,
        serials=None,
    ) -> Txn:
        if qty <= 0:
            raise InventoryError("quantity must be positive")
        self._check(sku, location)
        self.lot(sku, lot, expiry)
        self._book(StockKey(sku, location, lot, status, lpn), qty)
        for s in serials or []:
            self.serials[s] = {
                "sku": sku,
                "location": location,
                "lot": lot,
                "state": "IN_STOCK",
                "order": None,
            }
        return self._record(
            TxnType.RECEIVE,
            sku,
            qty,
            to_loc=location,
            lot=lot,
            lpn=lpn,
            status=status.value,
            ref=ref,
            user=user,
            serials=list(serials or []),
        )

    def move(
        self,
        sku: str,
        qty: int,
        from_loc: str,
        to_loc: str,
        lot: str,
        type_: TxnType = TxnType.MOVE,
        from_lpn: str | None = None,
        to_lpn: str | None = None,
        status=AVAILABLE,
        ref: str | None = None,
        user: str = "system",
        order: str | None = None,
    ) -> Txn:
        self._check(sku, from_loc, to_loc)
        if qty <= 0:
            raise InventoryError("quantity must be positive")
        dest = self._location(to_loc)
        if dest.blocked and dest.type in STORAGE:
            raise InventoryError(f"{to_loc} is blocked")
        src = StockKey(sku, from_loc, lot, status, from_lpn)
        if (
            self.stock.get(src, 0)
            - (self._allocated.get((sku, from_loc, lot), 0) if from_lpn is None else 0)
            < qty
        ):
            raise InventoryError(
                f"only {self.stock.get(src, 0)} free of {sku} lot {lot} at {from_loc}"
            )
        self._book(src, -qty)
        self._book(StockKey(sku, to_loc, lot, status, to_lpn), qty)
        serials = self._move_serials(sku, qty, from_loc, to_loc, lot, order=order)
        return self._record(
            type_,
            sku,
            qty,
            from_loc=from_loc,
            to_loc=to_loc,
            lot=lot,
            lpn=from_lpn or to_lpn,
            status=status.value,
            ref=ref,
            user=user,
            serials=serials,
        )

    def adjust(
        self,
        sku: str,
        location: str,
        lot: str,
        delta: int,
        reason: str,
        ref: str | None = None,
        user: str = "system",
        status=AVAILABLE,
        lpn: str | None = None,
        physical: bool = True,
    ) -> Txn:
        """Change stock without a movement (count difference, damage, found ...): reason required.
        physical=False books a difference the shelf already has (a count result)."""
        from wms.model import REASONS

        self._check(sku, location)
        if reason not in REASONS:
            raise InventoryError(f"unknown reason code {reason}")
        if delta == 0:
            raise InventoryError("an adjustment needs a non-zero quantity")
        self.lot(sku, lot)
        self._book(StockKey(sku, location, lot, status, lpn), delta, physical=physical)
        return self._record(
            TxnType.ADJUST,
            sku,
            delta,
            to_loc=location,
            lot=lot,
            lpn=lpn,
            status=status.value,
            reason=reason,
            ref=ref,
            user=user,
        )

    def set_status(
        self,
        sku: str,
        location: str,
        lot: str,
        qty: int,
        new: StockStatus,
        old=AVAILABLE,
        reason: str | None = None,
        ref: str | None = None,
        user: str = "system",
        lpn: str | None = None,
    ) -> Txn:
        """Hold, release, quarantine or expire units in place."""
        self._check(sku, location)
        if old == AVAILABLE and self.free_at(sku, location, lot) < qty and lpn is None:
            raise InventoryError("those units are allocated to orders")
        self._book(StockKey(sku, location, lot, old, lpn), -qty)
        self._book(StockKey(sku, location, lot, new, lpn), qty)
        return self._record(
            TxnType.STATUS,
            sku,
            qty,
            from_loc=location,
            to_loc=location,
            lot=lot,
            lpn=lpn,
            status=f"{old.value}->{new.value}",
            reason=reason,
            ref=ref,
            user=user,
        )

    # ----- orders ------------------------------------------------------------------------------
    def candidates(self, sku: str) -> list[tuple[str, str, int]]:
        """(location, lot, free units) at pick faces, best first: earliest expiry, then oldest."""
        out = []
        for k, _ in self.rows(sku=sku, status=AVAILABLE):
            loc = self.locations[k.location]
            if loc.type != LocationType.PICK or loc.blocked or k.lpn:
                continue
            free = self.free_at(sku, k.location, k.lot)
            if free > 0:
                lot = self.lots.get((sku, k.lot))
                expiry = lot.expiry if lot and lot.expiry else dt.date.max
                received = lot.received_tick if lot else 0
                out.append((expiry, received, k.location, k.lot, free))
        return [(loc, lot, free) for _, _, loc, lot, free in sorted(out)]

    def allocate(self, order_id: str, line: int, sku: str, qty: int) -> int:
        """Reserve up to qty units at pick faces; returns how many were allocated."""
        left = qty
        for location, lot, free in self.candidates(sku):
            take = min(free, left)
            self.allocations.setdefault(order_id, []).append(
                Allocation(order_id, line, sku, location, lot, take)
            )
            self._reserve(sku, location, lot, take)
            self._record(TxnType.ALLOCATE, sku, take, from_loc=location, lot=lot, ref=order_id)
            left -= take
            if left == 0:
                break
        return qty - left

    def deallocate(self, order_id: str, reason: str = "cancelled") -> None:
        for a in self.allocations.pop(order_id, []):
            open_qty = a.qty - a.picked
            if open_qty > 0:
                self._reserve(a.sku, a.location, a.lot, -open_qty)
                self._record(
                    TxnType.DEALLOCATE,
                    a.sku,
                    open_qty,
                    from_loc=a.location,
                    lot=a.lot,
                    ref=order_id,
                    reason=reason,
                )

    def robot_location(self, robot: str) -> str:
        """The transient location of the units a robot carries (ROBOT:R7)."""
        code = f"ROBOT:{robot}"
        if code not in self.locations:
            self.add_location(Location(code, LocationType.ROBOT, None, 0, 0))
        return code

    def pick(self, order_id: str, line: int, robot: str) -> tuple[int, int]:
        """The robot takes the line's allocated units from the shelf. Returns (picked, short):
        short > 0 when the shelf physically holds fewer units than the system said."""
        picked_total = short_total = 0
        on_robot = self.robot_location(robot)
        for a in self.allocations.get(order_id, []):
            if a.line != line or a.picked >= a.qty:
                continue
            want = a.qty - a.picked
            key = StockKey(a.sku, a.location, a.lot, AVAILABLE)
            got = min(want, self.physical.get(key, 0), self.stock.get(key, 0))
            if got:
                self._reserve(a.sku, a.location, a.lot, -got)
                a.picked += got
                self._book(key, -got)
                self._book(StockKey(a.sku, on_robot, a.lot), got)
                serials = self._move_serials(
                    a.sku, got, a.location, on_robot, a.lot, order=order_id
                )
                self._record(
                    TxnType.PICK,
                    a.sku,
                    got,
                    from_loc=a.location,
                    to_loc=on_robot,
                    lot=a.lot,
                    ref=order_id,
                    user=robot,
                    serials=serials,
                )
            if got < want:
                missing = want - got
                self._reserve(a.sku, a.location, a.lot, -missing)
                a.qty -= missing  # the line ships short
                self._record(
                    TxnType.SHORT_PICK,
                    a.sku,
                    missing,
                    from_loc=a.location,
                    lot=a.lot,
                    ref=order_id,
                    user=robot,
                    reason="shelf held fewer units than the system",
                )
                short_total += missing
            picked_total += got
        return picked_total, short_total

    def drop(self, order_id: str, robot: str, station: str, tote: str) -> int:
        """The robot drops the order's units at a packing station, in the order's tote (a
        license plate), so orders waiting at the same station never mix."""
        dropped = 0
        on_robot = self.robot_location(robot)
        for key, q in list(self.rows(location=on_robot)):
            self.move(
                key.sku,
                q,
                on_robot,
                station,
                key.lot,
                TxnType.MOVE,
                to_lpn=tote,
                ref=order_id,
                user=robot,
                order=order_id,
            )
            dropped += q
        self.allocations.pop(order_id, None)
        return dropped

    def ship_lpn(self, lpn: str, location: str, ref: str | None, user: str) -> int:
        """A carton leaves the building on a truck: its units leave the stock."""
        shipped = 0
        for key, q in list(self.rows(location=location, lpn=lpn)):
            self._book(key, -q)
            serials = self._move_serials(
                key.sku, q, location, "SHIPPED", key.lot, state="SHIPPED", order=ref
            )
            self._record(
                TxnType.SHIP,
                key.sku,
                q,
                from_loc=location,
                lot=key.lot,
                lpn=lpn,
                ref=ref,
                user=user,
                serials=serials,
            )
            shipped += q
        return shipped

    def ship(self, order_id: str, robot: str, station: str) -> int:
        """Ship straight from the robot at the station (no packing step; the warehouse uses
        drop -> pack -> load -> ship_lpn)."""
        shipped = 0
        on_robot = self.robot_location(robot)
        for key, q in list(self.rows(location=on_robot)):
            self._book(key, -q)
            serials = self._move_serials(
                key.sku, q, on_robot, station, key.lot, state="SHIPPED", order=order_id
            )
            self._record(
                TxnType.SHIP,
                key.sku,
                q,
                from_loc=on_robot,
                to_loc=station,
                lot=key.lot,
                ref=order_id,
                user=robot,
                serials=serials,
            )
            shipped += q
        self.allocations.pop(order_id, None)
        return shipped

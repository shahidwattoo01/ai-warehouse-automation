"""Outbound: cartonisation, packing with a weight check, sort lanes, loading, carrier departures,
holds, cancellations with put-back, partial shipments with backorders, waves and GS1 labels."""

import pytest

from simulation.environment.engine import SimulationEngine
from simulation.warehouse.entities import OrderItem, OrderStatus, Priority
from wms import barcodes as bc
from wms import labels
from wms.model import LocationType, TxnType
from wms.outbound import CARTONS, OutboundError

WMS = {"layout": "default", "inventory_model": "wms", "wms": {"opening_cover_days": 0.3}}


def engine(**wms) -> SimulationEngine:
    e = SimulationEngine(seed=11, overrides={**WMS, "wms": {**WMS["wms"], **wms}})
    e.start()
    return e


def run(e: SimulationEngine, ticks: int) -> None:
    for _ in range(ticks):
        e.tick()


def add_order(e: SimulationEngine, items: list[tuple[str, int]], priority="MEDIUM"):
    order = e.generator.operator_order(
        e.next_order_id(),
        e.time,
        Priority(priority),
        [OrderItem(s, q) for s, q in items],
        e.inventory,
    )
    e._add_order(order)
    return order, e.inventory.wms.out.orders[order.order_id]


@pytest.fixture(scope="module")
def day():
    """Eight simulated hours: the first trucks (06:00 and 07:00) have left."""
    e = engine()
    run(e, e.config["ticks_per_hour"] * 8)
    return e, e.inventory.wms


# ----- packing ----------------------------------------------------------------------------------
def test_cartons_fit_volume_and_weight(day):
    _, wms = day
    out = wms.out
    sku = max(wms.inv.items, key=lambda s: wms.inv.items[s].volume_l)  # the bulkiest item
    item = wms.inv.items[sku]
    boxes = out.cartonise([{"sku": sku, "lot": "L1", "qty": 12}])
    assert sum(r["qty"] for _, rows in boxes for r in rows) == 12
    limits = {c: (litres, tare, mx) for c, litres, tare, mx in CARTONS}
    for size, rows in boxes:
        litres, tare, mx = limits[size]
        units = sum(r["qty"] for r in rows)
        assert units * item.volume_l <= litres * 0.8 or units == 1
        assert units * item.weight_kg + tare <= mx or units == 1
    small = min(wms.inv.items, key=lambda s: wms.inv.items[s].volume_l)
    assert out.cartonise([{"sku": small, "lot": "L1", "qty": 1}])[0][0] == "S"


def test_orders_are_packed_loaded_and_leave_on_their_truck(day):
    _, wms = day
    out = wms.out
    shipped = [r for r in out.orders.values() if r.status == "SHIPPED"]
    assert len(shipped) > 30
    ledger = wms.inv.ledger
    for rec in shipped:
        assert rec.cartons and rec.packed and rec.loaded and rec.shipped
        for sscc in rec.cartons:
            carton = out.cartons[sscc]
            assert bc.valid(sscc) and carton.status == "SHIPPED"
            assert carton.tracking.startswith(out.carriers[rec.carrier].tracking_prefix)
            trip = out.trips[carton.trip]
            assert trip.status == "DEPARTED" and trip.departs == rec.shipped
            assert trip.departs % wms.tph == 0  # trucks leave on the hour of their schedule
        assert sum(ln.shipped for ln in rec.lines) == sum(ln.picked for ln in rec.lines)
        types = {t.type for t in ledger if t.ref == rec.order_id}
        assert {TxnType.PICK, TxnType.PACK, TxnType.SHIP} <= types
    k = wms.kpis()["outbound"]
    assert k["orders_shipped"] == len(shipped) and k["on_time_ship_rate"] > 0.9
    assert out.confirmations and out.confirmations[0]["tracking"]


def test_cartons_wait_in_lanes_and_trailers_by_carrier(day):
    _, wms = day
    for carton in wms.out.cartons.values():
        loc = wms.inv.locations[carton.location]
        if carton.status == "IN_LANE":
            assert loc.type == LocationType.LANE and loc.code == f"LANE-{carton.carrier}"
        if carton.status == "LOADED":
            assert loc.type == LocationType.SHIP_DOCK
            assert loc.code == wms.out.carriers[carton.carrier].door
            rows = list(wms.inv.rows(location=loc.code, lpn=carton.sscc))
            assert sum(q for _, q in rows) == sum(r["qty"] for r in carton.contents)


def test_packers_and_loaders_do_only_their_own_work(day):
    _, wms = day
    for task in wms.tasks.values():
        if task.assignee and task.assignee in wms.associates:
            crew = wms.associates[task.assignee]["crew"]
            if task.type in ("PACK", "AUDIT"):
                assert crew == "pack"
                assert wms.associates[task.assignee]["station"] == task.data["location"]
            elif task.type in ("LOAD", "PUTBACK"):
                assert crew == "dock"
            else:
                assert crew == "inbound"


# ----- exceptions ------------------------------------------------------------------------------
def test_hold_blocks_release_until_released():
    e = engine(credit_hold_rate=0.0)
    run(e, 5)
    sku = e.inventory.wms.orderable()[0]
    order, rec = add_order(e, [(sku, 1)])
    out = e.inventory.wms.out
    assert rec.status == "RELEASED"
    out.hold(order.order_id, "address check", "sara")
    assert not e.inventory.releasable(order.order_id)
    run(e, 30)
    assert order.status == OrderStatus.PENDING  # no robot was sent
    out.release_hold(order.order_id, "sara")
    assert rec.status == "RELEASED" and e.inventory.releasable(order.order_id)
    assert [h["event"] for h in rec.history][-3:] == ["ON_HOLD", "HOLD_RELEASED", "RELEASED"]
    with pytest.raises(OutboundError):
        out.release_hold(order.order_id, "sara")


def test_cancel_after_packing_puts_the_units_back():
    e = engine(credit_hold_rate=0.0, auto_tasks={"PACK": False})
    wms = e.inventory.wms
    run(e, 5)
    sku = wms.orderable()[0]
    home = wms.inv.items[sku].home
    order, rec = add_order(e, [(sku, 2)], "HIGH")
    for _ in range(3000):
        e.tick()
        if rec.status == "AT_PACK":
            break
    assert rec.status == "AT_PACK"  # packing waits for a person (auto PACK off)
    wms.out.pack(order.order_id, "sara")
    assert rec.status == "PACKED"
    wms.out.cancel(order.order_id, "customer called", "sara")
    assert rec.status == "CANCELLED"
    assert all(wms.out.cartons[s].status == "CANCELLED" for s in rec.cartons)
    run(e, 200)  # a loader puts the cartons' units back on the pick face
    back = sum(
        t.qty
        for t in wms.inv.ledger
        if t.type == TxnType.MOVE and t.ref == order.order_id and t.to_loc == home
    )
    assert back == rec.lines[0].picked > 0
    assert not any(True for c in rec.cartons for _ in wms.inv.rows(lpn=c))  # cartons are empty
    with pytest.raises(OutboundError):
        wms.out.cancel(order.order_id, "again", "sara")


def test_partial_release_backorders_the_rest_and_ships_it_later():
    e = engine(credit_hold_rate=0.0)
    wms = e.inventory.wms
    run(e, 5)
    out = wms.out
    sku = wms.orderable()[0]
    atp = wms.atp(sku)
    order, rec = add_order(e, [(sku, atp + 4)])
    assert rec.status == "WAITING_STOCK"
    rec.customer_id = next(c for c, v in out.customers.items() if v.allow_partial)
    out.ship_partial(order.order_id, "sara")
    assert rec.status == "RELEASED" and rec.partial
    bo = next(b for b in out.backorders.values() if b.order_id == order.order_id)
    assert bo.qty == rec.lines[0].ordered - rec.lines[0].allocated and bo.status == "OPEN"
    for _ in range(600 * 12):  # until the stock arrives and a follow-up order is created
        e.tick()
        if bo.child:
            break
    assert bo.status == "RELEASED" and bo.child
    child = out.orders[bo.child]
    assert child.parent == order.order_id and child.customer_id == rec.customer_id
    assert child.source == "BACKORDER"


def test_customers_who_refuse_partial_shipments_keep_waiting():
    e = engine(credit_hold_rate=0.0)
    wms = e.inventory.wms
    run(e, 5)
    sku = wms.orderable()[0]
    order, rec = add_order(e, [(sku, wms.atp(sku) + 4)])
    rec.customer_id = next(c for c, v in wms.out.customers.items() if not v.allow_partial)
    with pytest.raises(OutboundError):
        wms.out.ship_partial(order.order_id, "sara")


def test_wave_release_groups_orders_and_releases_hot_ones_at_once():
    e = engine(credit_hold_rate=0.0, release_mode="wave", wave_minutes=30)
    run(e, e.config["ticks_per_hour"] * 2)
    out = e.inventory.wms.out
    assert out.waves
    wave = out.waves[0]
    assert wave["orders"] and all(out.orders[o].wave == wave["wave_id"] for o in wave["orders"])
    hot = [r for r in out.orders.values() if r.history and "hot order" in str(r.history)]
    assert hot  # HIGH orders have a deadline shorter than the 30-minute wave
    out.set_release_mode("continuous")
    assert not any(r.status == "READY" for r in out.orders.values())


# ----- labels and scans ------------------------------------------------------------------------
def test_shipping_label_and_its_gs1_data(day):
    _, wms = day
    out = wms.out
    carton = next(iter(out.cartons.values()))
    rec = out.orders[carton.order_id]
    customer = out.customers[rec.customer_id]
    pdf = labels.shipping_label(
        carton.to_dict(), customer.to_dict(), out.carriers[rec.carrier].to_dict()
    )
    assert pdf.startswith(b"%PDF")
    raw = bc.element_string({"00": carton.sscc, "3301": "000123", "420": customer.postal_code})
    scan = bc.parse_scan(raw)
    assert scan.kind == "gs1" and not scan.errors
    assert scan.sscc == carton.sscc and scan.ship_to_postal == customer.postal_code
    human = bc.parse_scan(f"(00){carton.sscc}(420){customer.postal_code}")
    assert human.sscc == carton.sscc and human.ship_to_postal == customer.postal_code
    assert bc.parse_scan("LANE-EXP").kind == "location"
    assert bc.parse_scan("SHIP-02").kind == "location"


def test_an_order_that_misses_its_truck_ships_on_the_next_one_and_counts_late():
    e = engine(credit_hold_rate=0.0)
    wms = e.inventory.wms
    run(e, 5)
    out = wms.out
    order, rec = add_order(e, [(wms.orderable()[0], 1)])
    promised = rec.promised
    out.hold(order.order_id, "address check", "sara")
    while e.time <= promised:  # the truck leaves without it
        e.tick()
    assert rec.missed == 1 and rec.departure > promised
    out.release_hold(order.order_id, "sara")
    while rec.status != "SHIPPED" and e.time < promised + 24 * wms.tph:
        e.tick()
    assert rec.status == "SHIPPED" and rec.shipped == rec.departure > promised
    assert out.kpis()["on_time_ship_rate"] < 1.0 and out.metrics["missed_trucks"] >= 1

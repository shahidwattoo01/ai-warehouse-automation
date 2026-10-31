"""WMS inventory core: GS1 barcodes, the stock ledger (allocation, FEFO, picks, short picks,
shipping, adjustments), blind cycle counts, and a simulated day that conserves every unit."""

import datetime as dt
import random

import pytest

from simulation.environment.engine import SimulationEngine
from wms import barcodes as bc
from wms.inventory import Inventory, InventoryError
from wms.model import Item, Location, LocationType, StockKey, StockStatus, TxnType

# ----- GS1 barcodes --------------------------------------------------------------------------


def test_check_digits_match_real_barcodes():
    assert bc.valid("4006381333931")  # a real EAN-13 from a retail product
    assert not bc.valid("4006381333932")  # one digit wrong
    assert bc.valid(bc.gtin13(42)) and bc.valid(bc.gtin14(bc.gtin13(42)))
    assert bc.valid(bc.sscc(123)) and len(bc.sscc(123)) == 18


def test_gs1_128_round_trip_raw_and_human_readable():
    fields = bc.gs1_item_label(bc.gtin13(7), lot="L2610A", expiry=dt.date(2027, 3, 31), quantity=12)
    raw = bc.element_string(fields)
    assert bc.GS in raw  # the variable-length lot is terminated before the next field
    for text in (raw, bc.element_string(fields, human=True), "]C1" + raw):
        scan = bc.parse_scan(text)
        assert scan.kind == "gs1" and not scan.errors
        assert scan.gtin == bc.as_gtin14(bc.gtin13(7))
        assert (scan.lot, scan.expiry, scan.quantity) == ("L2610A", dt.date(2027, 3, 31), 12)


def test_scans_of_locations_plates_and_rubbish():
    assert bc.parse_scan("A-05-12-1").kind == "location"
    plate = bc.parse_scan("LPN" + bc.sscc(5))
    assert plate.kind == "lpn" and not plate.errors
    assert bc.parse_scan("4006381333932").errors  # bad check digit is reported
    assert bc.parse_scan("hello").kind == "unknown"
    assert bc.from_yymmdd("270200") == dt.date(2027, 2, 28)  # day 00 = last day of the month


# ----- the ledger ------------------------------------------------------------------------------


@pytest.fixture()
def inv():
    inv = Inventory(ticks_per_day=100)
    item = Item(
        "P-1",
        bc.gtin13(1),
        bc.gtin14(bc.gtin13(1)),
        "Tea",
        "Grocery",
        "SUP-01",
        2.0,
        0.5,
        case_qty=6,
        pallet_cases=4,
        home="A-01-01-1",
        pick_min=4,
        pick_max=18,
        shelf_life_days=90,
    )
    inv.add_item(item)
    inv.add_location(Location("A-01-01-1", LocationType.PICK, "A", 1, 1, 1, capacity=18, sku="P-1"))
    inv.add_location(Location("A-01-01-3", LocationType.RESERVE, "A", 1, 1, 3, capacity=1))
    inv.add_location(Location("PACK_1", LocationType.PACK, None, 5, 9))
    return inv


def test_allocation_is_fefo_and_never_promises_a_unit_twice(inv):
    inv.receive("P-1", 5, "LATE", dt.date(2027, 6, 1), "A-01-01-1", None)
    inv.receive("P-1", 5, "SOON", dt.date(2027, 1, 1), "A-01-01-1", None)
    assert inv.atp("P-1") == 10
    assert inv.allocate("O1", 0, "P-1", 6) == 6
    lots = [(a.lot, a.qty) for a in inv.allocations["O1"]]
    assert lots == [("SOON", 5), ("LATE", 1)]  # first expiry first
    assert inv.atp("P-1") == 4 and inv.allocate("O2", 0, "P-1", 9) == 4
    with pytest.raises(InventoryError):  # allocated units cannot be moved away
        inv.move("P-1", 6, "A-01-01-1", "A-01-01-3", "LATE")


def test_pick_ship_and_short_pick(inv):
    inv.receive("P-1", 6, "L1", None, "A-01-01-1", None)
    inv.allocate("O1", 0, "P-1", 6)
    inv.shelf_change(StockKey("P-1", "A-01-01-1", "L1"), -2)  # 2 units vanished from the shelf
    picked, short = inv.pick("O1", 0, "R1")
    assert (picked, short) == (4, 2)
    assert inv.ship("O1", "R1", "PACK_1") == 4
    types = [t.type for t in inv.ledger]
    assert TxnType.SHORT_PICK in types and types[-1] == TxnType.SHIP
    assert inv.qty("P-1", location="A-01-01-1") == 2  # the system still believes 2 are there


def test_adjustments_need_a_reason_and_cannot_go_negative(inv):
    inv.receive("P-1", 3, "L1", None, "A-01-01-1", None)
    with pytest.raises(InventoryError):
        inv.adjust("P-1", "A-01-01-1", "L1", -1, "OOPS")
    with pytest.raises(InventoryError):
        inv.adjust("P-1", "A-01-01-1", "L1", -4, "LOST")
    inv.adjust("P-1", "A-01-01-1", "L1", -1, "DAMAGED", user="sara")
    assert inv.ledger[-1].reason == "DAMAGED" and inv.ledger[-1].user == "sara"
    inv.set_status("P-1", "A-01-01-1", "L1", 2, StockStatus.HOLD, reason="recall")
    assert inv.atp("P-1") == 0  # held units cannot be promised


# ----- the simulated warehouse -----------------------------------------------------------------


@pytest.fixture(scope="module")
def day():
    """Eight simulated hours on the small layout with the WMS."""
    overrides = {"layout": "default", "inventory_model": "wms", "wms": {"opening_cover_days": 0.3}}
    engine = SimulationEngine(seed=5, overrides=overrides)
    wms = engine.inventory.wms
    opening = sum(q for k, q in wms.inv.stock.items())
    engine.start()
    for _ in range(engine.config["ticks_per_hour"] * 8):
        engine.tick()
    return engine, wms, opening


def test_every_unit_is_accounted_for(day):
    _, wms, opening = day
    ledger = wms.inv.ledger
    received = sum(t.qty for t in ledger if t.type == TxnType.RECEIVE)
    adjusted = sum(t.qty for t in ledger if t.type == TxnType.ADJUST)
    shipped = sum(t.qty for t in ledger if t.type == TxnType.SHIP)
    now = sum(q for q in wms.inv.stock.values())
    assert now == opening + received + adjusted - shipped
    assert all(q >= 0 for q in wms.inv.stock.values())


def test_the_warehouse_receives_replenishes_counts_and_ships(day):
    engine, wms, _ = day
    k = wms.kpis()
    assert wms.metrics["orders_shipped"] > 50 and k["fill_rate"] > 0.95
    assert wms.metrics["purchase_orders"] > 0 and wms.metrics["tasks_replenish"] > 0
    assert k["counts_done"] > 0 and 0.5 < k["inventory_record_accuracy"] <= 1.0
    shipped = {t.ref for t in wms.inv.ledger if t.type == TxnType.SHIP}
    packed = {t.ref for t in wms.inv.ledger if t.type == TxnType.PACK}
    for rec in wms.out.orders.values():  # shipped orders were packed and left on a truck
        if rec.status == "SHIPPED":
            assert rec.order_id in shipped and rec.order_id in packed and rec.cartons


def test_blind_count_finds_shrinkage_and_needs_approval_above_the_value_limit(day):
    _, wms, _ = day
    item = max(wms.inv.items.values(), key=lambda i: i.unit_cost)
    key = next(k for k, _ in wms.inv.rows(sku=item.sku, location=item.home))
    wms.inv.shelf_change(key, -wms.inv.physical[key])  # the whole shelf is gone
    system = wms.inv.qty(item.sku, location=item.home)
    first = wms.create_count(item.home, item.sku)
    wms.submit_count(first.count_id, 0, "counter-1")
    assert first.variance == -system and first.status == "COUNTED"  # a recount is ordered
    recount = next(c for c in wms.counts.values() if c.recount_of == first.count_id)
    wms.submit_count(recount.count_id, 0, "counter-2")
    if abs(recount.value) >= wms.cfg["auto_approve_value"]:
        assert recount.status == "PENDING_APPROVAL"
        wms.decide_count(recount.count_id, approve=True, user="supervisor")
    assert recount.status == "ADJUSTED"
    assert wms.inv.qty(item.sku, location=item.home) == wms.inv.allocated(item.sku, item.home)


def test_simple_model_is_unchanged_by_default():
    engine = SimulationEngine(seed=5, overrides={"layout": "default"})
    assert not hasattr(engine.inventory, "wms") and engine.inventory.releasable("x")
    random.Random(0)  # (the golden master test checks the full run)


# ----- returns inspection -----------------------------------------------------------------------
def _received_return(reason="changed mind"):
    from wms.operations import Return

    e = SimulationEngine(seed=5, overrides={"layout": "default", "inventory_model": "wms"})
    wms = e.inventory.wms
    wms.cfg["auto_tasks"]["RETURN"] = False  # inspected by a person in the app
    sku = next(iter(wms.inv.items))
    rma = Return("RMA-T1", "000001", sku, 1, 0, reason)
    wms.returns[rma.rma_id] = rma
    wms._returns_arriving()
    return wms, rma


def test_inspecting_a_return_as_new_restocks_it():
    wms, rma = _received_return()
    home = wms.inv.items[rma.sku].home
    before = wms.inv.qty(rma.sku, location=home)
    assert rma.status == "RECEIVED" and rma.received_at is not None
    wms.inspect_return(rma.rma_id, "OPENED", "box opened, all parts there", "sara")
    assert rma.status == "RESTOCKED" and rma.condition == "OPENED" and rma.inspected_by == "sara"
    assert wms.inv.qty(rma.sku, location=home) == before + 1
    with pytest.raises(InventoryError):
        wms.inspect_return(rma.rma_id, "NEW", None, "sara")  # already done


def test_inspecting_a_damaged_return_scraps_it_with_a_reason():
    wms, rma = _received_return()
    wms.inspect_return(rma.rma_id, "DEFECTIVE", "does not switch on", "sara")
    assert rma.status == "SCRAPPED"
    scrap = [t for t in wms.inv.ledger if t.ref == rma.rma_id and t.type == TxnType.ADJUST]
    assert scrap and scrap[-1].reason == "RETURN_SCRAP" and scrap[-1].user == "sara"
    with pytest.raises(InventoryError):
        wms.inspect_return("RMA-NOPE", "NEW", None, "sara")


def test_associates_grade_returns_by_what_they_find():
    wms, rma = _received_return("damaged in transit")
    task = next(t for t in wms.tasks.values() if t.data.get("rma") == rma.rma_id)
    wms._do_return(task, "AS01")
    assert rma.condition == "DAMAGED" and rma.status == "SCRAPPED" and rma.inspected_by == "AS01"

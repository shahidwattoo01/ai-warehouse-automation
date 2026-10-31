"""WMS API: scanning, receiving and putaway by scan, adjustments with reason codes, holds, blind
counts, labels, and the refusal when the simple inventory model is configured."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.simulator import simulator
from simulation.environment.engine import SimulationEngine
from wms.operations import POLine

API = "/api/v1/wms"


@pytest.fixture()
def client():
    original = simulator.engine
    simulator.engine = SimulationEngine(
        seed=11,
        overrides={
            "layout": "default",
            "inventory_model": "wms",
            "wms": {"opening_cover_days": 0.5},
        },
    )
    simulator.engine.start()
    for _ in range(300):
        simulator.engine.tick()
    yield TestClient(app)  # no context manager: the background tick loop stays off
    simulator.engine = original


@pytest.fixture()
def wms(client):
    return simulator.engine.inventory.wms


def test_overview_items_and_item_detail(client, wms):
    k = client.get(f"{API}/kpis").json()
    assert k["skus"] == len(wms.inv.items) and k["units_on_hand"] > 0
    page = client.get(f"{API}/items", params={"limit": 5}).json()
    assert page["total"] == len(wms.inv.items) and len(page["items"]) == 5
    sku = page["items"][0]["sku"]
    detail = client.get(f"{API}/items/{sku}").json()
    assert detail["stock"] and detail["home"].endswith("-1") and detail["reorder_point"] >= 0
    assert client.get(f"{API}/items/NOPE").status_code == 404


def test_scanning_items_locations_and_bad_codes(client, wms):
    item = next(iter(wms.inv.items.values()))
    assert client.post(f"{API}/scan", json={"code": item.gtin}).json()["item"]["sku"] == item.sku
    case = client.post(f"{API}/scan", json={"code": item.case_gtin}).json()
    assert case["item"]["sku"] == item.sku and case["unit"].startswith("case of")
    loc = client.post(f"{API}/scan", json={"code": item.home}).json()
    assert loc["location"]["code"] == item.home
    bad = client.post(
        f"{API}/scan", json={"code": item.gtin[:-1] + str((int(item.gtin[-1]) + 1) % 10)}
    ).json()
    assert bad["scan"]["errors"]


def test_receive_and_put_away_by_scanning(client, wms):
    client.put(f"{API}/settings", json={"auto_tasks": {"RECEIVE": False, "PUTAWAY": False}})
    item = next(iter(wms.inv.items.values()))
    po = wms.create_po(item.supplier_id, [POLine(item.sku, item.case_qty * 2)])
    po.eta = wms.inv.tick  # the truck is here now
    wms._trucks()
    assert po.status == "AT_DOCK"
    plate = po.asn[0]

    scanned = client.post(f"{API}/scan", json={"code": "LPN" + plate["sscc"]}).json()
    assert scanned["plate"]["asn"]["po_id"] == po.po_id
    r = client.post(f"{API}/receive", json={"po_id": po.po_id, "sscc": plate["sscc"]})
    assert r.status_code == 200 and r.json()["putaway_suggestion"]
    again = client.post(f"{API}/receive", json={"po_id": po.po_id, "sscc": plate["sscc"]})
    assert again.status_code == 422  # a plate is received once

    before = wms.inv.qty(item.sku, location=item.home)
    room = item.pick_max - before
    put = client.post(f"{API}/putaway", json={"sscc": plate["sscc"], "location": item.home})
    assert put.status_code == 200 and put.json()["moved"] == min(room, plate["qty"])
    ledger = client.get(f"{API}/transactions", params={"sku": item.sku}).json()
    assert [t["type"] for t in ledger][-1] == "RECEIVE" and all(
        t["ref"] == po.po_id for t in ledger
    )
    wrong = client.post(f"{API}/putaway", json={"sscc": plate["sscc"], "location": "QA-01"})
    assert put.json()["left_on_plate"] == 0 or wrong.status_code == 422


def test_adjustments_need_a_known_reason(client, wms):
    item = next(iter(wms.inv.items.values()))
    row = next(r for r in client.get(f"{API}/locations/{item.home}").json()["stock"])
    body = {"sku": item.sku, "location": item.home, "lot": row["lot"], "delta": -1}
    assert client.post(f"{API}/adjustments", json={**body, "reason": "BECAUSE"}).status_code == 422
    ok = client.post(f"{API}/adjustments", json={**body, "reason": "DAMAGED"})
    assert (
        ok.status_code == 200
        and ok.json()["reason"] == "DAMAGED"
        and ok.json()["user"] == "test-admin"
    )


def test_hold_and_release(client, wms):
    item = next(iter(wms.inv.items.values()))
    held = client.post(f"{API}/holds", json={"sku": item.sku, "reason": "supplier recall"}).json()
    assert held["units"] > 0 and wms.inv.atp(item.sku) <= 0
    released = client.post(
        f"{API}/holds",
        json={"sku": item.sku, "reason": "recall closed", "release": True},
    ).json()
    assert released["units"] == held["units"]


def test_blind_count_hides_the_system_quantity(client, wms):
    client.put(f"{API}/settings", json={"auto_tasks": {"COUNT": False}})
    item = next(iter(wms.inv.items.values()))
    count = client.post(f"{API}/counts", json={"location": item.home}).json()
    listed = next(
        c
        for c in client.get(f"{API}/counts", params={"status": "OPEN"}).json()
        if c["count_id"] == count["count_id"]
    )
    assert listed["expected"] is None  # the counter must not see it
    system = wms.inv.qty(item.sku, location=item.home)
    done = client.post(f"{API}/counts/{count['count_id']}/submit", json={"counted": system}).json()
    assert done["status"] == "MATCHED" and done["variance"] == 0


def test_labels_and_barcodes(client, wms):
    item = next(iter(wms.inv.items.values()))
    pdf = client.get(f"{API}/labels/items/{item.sku}")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert client.get(
        f"{API}/labels/locations", params={"prefix": item.home[:4]}
    ).content.startswith(b"%PDF")
    svg = client.get(f"{API}/barcode.svg", params={"kind": "ean13", "value": item.gtin})
    assert svg.status_code == 200 and "<svg" in svg.text


def test_simple_model_answers_409():
    original = simulator.engine
    simulator.engine = SimulationEngine(seed=11, overrides={"layout": "default"})
    try:
        assert TestClient(app).get(f"{API}/kpis").status_code == 409
    finally:
        simulator.engine = original


# ----- outbound --------------------------------------------------------------------------------
def _new_order(qty: int = 1):
    from simulation.warehouse.entities import OrderItem, Priority

    eng = simulator.engine
    wms = eng.inventory.wms
    sku = wms.orderable()[0]
    order = eng.generator.operator_order(
        eng.next_order_id(), eng.time, Priority.MEDIUM, [OrderItem(sku, qty)], eng.inventory
    )
    eng._add_order(order)
    return order


def test_outbound_orders_hold_release_and_cancel(client, wms):
    order = _new_order()
    page = client.get(f"{API}/outbound/orders", params={"status": "open"}).json()
    assert any(r["order_id"] == order.order_id for r in page["orders"])
    detail = client.get(f"{API}/outbound/orders/{order.order_id}").json()
    assert detail["customer_detail"]["postal_code"] and detail["departure_at"]
    held = client.post(
        f"{API}/outbound/orders/{order.order_id}/hold", json={"reason": "address check"}
    ).json()
    assert held["status"] == "ON_HOLD" and held["hold_reason"] == "address check"
    released = client.post(f"{API}/outbound/orders/{order.order_id}/release-hold").json()
    assert released["status"] == "RELEASED"
    gone = client.post(
        f"{API}/outbound/orders/{order.order_id}/cancel", json={"reason": "customer called"}
    ).json()
    assert gone["status"] == "CANCELLED"
    assert simulator.engine.orders[order.order_id].status.value == "CANCELLED"
    again = client.post(
        f"{API}/outbound/orders/{order.order_id}/cancel", json={"reason": "customer called"}
    )
    assert again.status_code == 409
    history = client.get(f"{API}/outbound/orders/{order.order_id}").json()["history"]
    assert [h["user"] for h in history if h["event"] in ("ON_HOLD", "CANCELLED")] == [
        "test-admin"
    ] * 2


def test_manual_packing_loading_and_the_shipping_label(client, wms):
    client.put(f"{API}/settings", json={"auto_tasks": {"PACK": False, "LOAD": False}})
    order = _new_order(2)
    rec = wms.out.orders[order.order_id]
    for _ in range(3000):
        simulator.engine.tick()
        if rec.status == "AT_PACK":
            break
    assert rec.status == "AT_PACK"
    packed = client.post(f"{API}/outbound/pack", json={"order_id": order.order_id}).json()
    carton = packed["cartons"][0]
    assert carton["tracking"] and carton["size"] in ("S", "M", "L")
    if carton["check"] == "FAIL":
        client.post(f"{API}/outbound/audit", json={"sscc": carton["sscc"]})
    label = client.get(f"{API}/labels/shipping/{carton['sscc']}")
    assert label.status_code == 200 and label.content.startswith(b"%PDF")
    loaded = client.post(f"{API}/outbound/load", json={"sscc": "LPN" + carton["sscc"]}).json()
    assert loaded["status"] == "LOADED" and loaded["trip"]
    manifest = client.get(f"{API}/outbound/trips/{loaded['trip']}").json()
    assert any(m["sscc"] == carton["sscc"] for m in manifest["manifest"])
    assert client.post(f"{API}/outbound/load", json={"sscc": carton["sscc"]}).status_code == 409


def test_outbound_settings_and_lists(client, wms):
    s = client.put(f"{API}/settings", json={"release_mode": "wave", "wave_minutes": 20}).json()
    assert s["release_mode"] == "wave" and s["wave_minutes"] == 20
    assert client.put(f"{API}/settings", json={"release_mode": "batch"}).status_code == 422
    client.put(f"{API}/settings", json={"release_mode": "continuous"})
    trips = client.get(f"{API}/outbound/trips").json()
    assert {t["carrier"] for t in trips} == {"EXP", "STD", "ECO"}
    assert len(client.get(f"{API}/outbound/customers").json()) == 60
    assert client.get(f"{API}/outbound/carriers").json()[0]["departures"]
    assert "outbound" in client.get(f"{API}/kpis").json()


def test_returns_list_and_inspection(client, wms):
    from wms.operations import Return

    wms.cfg["auto_tasks"]["RETURN"] = False
    sku = next(iter(wms.inv.items))
    wms.returns["RMA-API1"] = Return("RMA-API1", "000001", sku, 1, 0, "wrong size")
    wms._returns_arriving()
    page = client.get(f"{API}/returns", params={"status": "RECEIVED"}).json()
    assert any(r["rma_id"] == "RMA-API1" for r in page["returns"])
    assert page["conditions"]["NEW"]["restock"] and not page["conditions"]["DAMAGED"]["restock"]
    done = client.post(f"{API}/returns/RMA-API1/inspect", json={"condition": "NEW"}).json()
    assert done["status"] == "RESTOCKED" and done["inspected_by"] == "test-admin"
    again = client.post(f"{API}/returns/RMA-API1/inspect", json={"condition": "NEW"})
    assert again.status_code == 422
    bad = client.post(f"{API}/returns/RMA-API1/inspect", json={"condition": "SHINY"})
    assert bad.status_code == 422

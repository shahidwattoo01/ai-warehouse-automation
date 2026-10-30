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

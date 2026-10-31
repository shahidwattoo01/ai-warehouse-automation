"""ERP connection: order import (pull, checks, duplicates), the outbox (retries, idempotency),
ship confirmations and stock levels, webhook signatures, and the REST client against the mock."""

import socket
import threading
import time

import pytest

from integration.erp.connector import ErpConnector, HttpErp, InProcessErp, sign, verify
from integration.erp.mock_erp import MockErp, make_app
from simulation.environment.engine import SimulationEngine


@pytest.fixture()
def world():
    e = SimulationEngine(seed=5, overrides={"layout": "default", "inventory_model": "wms"})
    e.start()
    mock = MockErp()
    conn = ErpConnector(e, InProcessErp(mock), poll_minutes=1, start_worker=False)

    def run(ticks):
        for _ in range(ticks):
            e.tick()
            conn.after_tick()
            conn.work_once()

    return e, mock, conn, run


def test_pulled_orders_are_checked_imported_and_acknowledged(world):
    e, mock, conn, run = world
    wms = e.inventory.wms
    sku = wms.orderable()[0]
    good = mock.create_order("C-0007", [{"sku": sku, "qty": 2}], "EXPRESS")
    bad_sku = mock.create_order("C-0007", [{"sku": "P-NOPE", "qty": 1}])
    bad_customer = mock.create_order("C-9999", [{"sku": sku, "qty": 1}])
    run(25)  # a pull every simulated minute (10 ticks)
    assert good["status"] == "ACCEPTED" and good["wms_order_id"] in e.orders
    order = e.orders[good["wms_order_id"]]
    assert order.source == "ERP" and order.priority.value == "HIGH"
    rec = wms.out.orders[order.order_id]
    assert rec.customer_id == "C-0007" and rec.external_ref == good["number"]
    assert bad_sku["status"] == "REJECTED" and "unknown SKU" in bad_sku["reason"]
    assert bad_customer["status"] == "REJECTED" and "unknown customer" in bad_customer["reason"]


def test_the_same_erp_order_is_imported_once(world):
    e, mock, conn, run = world
    sku = e.inventory.wms.orderable()[0]
    order = {"number": "SO-X1", "customer_id": "C-0001", "lines": [{"sku": sku, "qty": 1}]}
    first = conn.receive(order, "webhook")
    before = len(e.orders)
    assert conn.receive(order, "webhook") == first and len(e.orders) == before


def test_outbox_retries_while_the_erp_is_down(world):
    e, mock, conn, run = world
    sku = e.inventory.wms.orderable()[0]
    so = mock.create_order("C-0002", [{"sku": sku, "qty": 1}])
    run(10)  # pulled (the ERP is still up)
    mock.down = True
    run(1)  # the order is created; its acknowledgement cannot be delivered
    ack = next(m for m in conn.outbox if m.kind == "ack")
    assert ack.status == "PENDING" and ack.attempts >= 1 and ack.error
    assert so["status"] == "RELEASED"
    mock.down = False
    ack.next_try = 0
    conn.work_once()
    assert ack.status == "SENT" and so["status"] == "ACCEPTED"
    mock.down = True
    for _ in range(10):  # every attempt fails: FAILED after the last one, then retried by hand
        msg = conn.outbox[-1]
        msg.status, msg.next_try = ("PENDING", 0) if msg.status != "FAILED" else (msg.status, 0)
        conn.work_once()
    conn._queue("stock", "stock-test", {"levels": {}})
    for _ in range(9):
        conn.outbox[-1].next_try = 0
        conn.work_once()
    assert conn.outbox[-1].status == "FAILED"
    mock.down = False
    assert conn.retry_failed() >= 1
    conn.work_once()
    assert conn.outbox[-1].status == "SENT"


def test_ship_confirmations_and_stock_levels_reach_the_erp(world):
    e, mock, conn, run = world
    wms = e.inventory.wms
    sku = wms.orderable()[0]
    so = mock.create_order("C-0003", [{"sku": sku, "qty": 1}])
    run(12)
    oid = so["wms_order_id"]
    confirmation = {"order_id": oid, "trip": "EXP-0907-0700", "tracking": ["SWX1"]}
    confirmation |= {"lines": [{"sku": sku, "shipped": 1}], "tick": e.time}
    wms.out.confirmations.appendleft(confirmation)
    run(1)
    assert so["status"] == "SHIPPED" and so["shipped"]["erp_number"] == so["number"]
    assert mock.received["shipments"] == 1
    conn._shipped.discard(oid)  # deliver the same confirmation again: the ERP ignores it
    run(1)
    assert mock.received["shipments"] == 1 and mock.received["duplicates"] == 1
    run(conn.stock_ticks)  # an hour later: stock levels
    assert mock.received["stock"] >= 1 and len(mock.stock) == len(wms.inv.items)


def test_webhook_signatures():
    body, ts = b'{"number":"SO-1"}', str(int(time.time()))
    good = sign("s3cret", ts, body)
    assert verify("s3cret", ts, body, good) is None
    assert verify("s3cret", ts, body + b" ", good) == "bad signature"  # body changed
    assert verify("other", ts, body, good) == "bad signature"
    old = str(int(time.time()) - 600)
    assert "too old" in verify("s3cret", old, body, sign("s3cret", old, body))
    assert "not configured" in verify("", ts, body, good)


def test_rest_client_against_the_mock_erp_server():
    import uvicorn

    mock = MockErp()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(make_app(mock, "k1"), port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    try:
        so = mock.create_order("C-0001", [{"sku": "P-1", "qty": 1}])
        client = HttpErp(f"http://127.0.0.1:{port}", "k1")
        assert [o["number"] for o in client.released()] == [so["number"]]
        client.ack(so["number"], True, "000042", None)
        assert so["status"] == "ACCEPTED" and so["wms_order_id"] == "000042"
        client.post("shipment", "ship-000042", {"order_id": "000042"})
        client.post("shipment", "ship-000042", {"order_id": "000042"})  # retried: stored once
        assert mock.received["shipments"] == 1 and mock.received["duplicates"] == 1
        with pytest.raises(Exception, match="401"):
            HttpErp(f"http://127.0.0.1:{port}", "wrong").released()
    finally:
        server.should_exit = True
        thread.join(timeout=5)

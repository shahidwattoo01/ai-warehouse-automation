"""The WMS side of the ERP connection (backlog PR-13).

    ERP ──► sales orders: pulled every few simulated minutes, or pushed to the signed webhook
         ──► checked (customer, SKUs, quantities) ──► a WMS order (source ERP, the ERP number
             kept as external reference) ──► acknowledged with the WMS order id, or rejected
    WMS ──► outbox ──► ERP: ship confirmations of ERP orders when their truck leaves, and
             stock levels every simulated hour

The outbox is the safety net: every message has an idempotency key, is retried with growing
waits (1 s, 2 s, 4 s ... up to 5 min, 8 attempts) and is never lost while the ERP is down; the
ERP ignores a key it has already stored. Network calls run on a worker thread; orders are created
on the simulator's loop, so the simulator is never touched from two threads.
"""

from __future__ import annotations

import hashlib
import hmac
import itertools
import json
import logging
import threading
import time
import urllib.request
from collections import deque
from dataclasses import asdict, dataclass

from simulation.warehouse.entities import OrderItem, Priority

log = logging.getLogger(__name__)
SERVICE_PRIORITY = {"EXPRESS": Priority.HIGH, "STANDARD": Priority.MEDIUM, "ECONOMY": Priority.LOW}
MAX_ATTEMPTS = 8
SIGNATURE_WINDOW_S = 300


# ----- ERP clients -------------------------------------------------------------------------------
class InProcessErp:
    """The mock ERP in the same process (no network)."""

    kind = "in-process mock"

    def __init__(self, erp) -> None:
        self.erp = erp

    def released(self) -> list[dict]:
        return [dict(o) for o in self.erp.released()]

    def ack(self, number: str, accepted: bool, wms_id: str | None, reason: str | None) -> None:
        self.erp.ack(number, accepted, wms_id, reason)

    def post(self, kind: str, key: str, payload: dict) -> None:
        if kind == "shipment":
            self.erp.shipment(key, payload)
        else:
            self.erp.stock_levels(key, payload["levels"])


class HttpErp:
    """An ERP reached over REST (the mock ERP server, or a real system with the same API)."""

    kind = "REST"

    def __init__(self, base_url: str, api_key: str, timeout: float = 10.0) -> None:
        self.base, self.key, self.timeout = base_url.rstrip("/"), api_key, timeout

    def _call(self, method: str, path: str, body: dict | None = None, headers=None) -> object:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            f"{self.base}{path}",
            data=data,
            method=method,
            headers={"X-API-Key": self.key, "Content-Type": "application/json", **(headers or {})},
        )
        # The ERP address comes from configuration (ERP_URL), never from a request.
        with urllib.request.urlopen(req, timeout=self.timeout) as res:  # noqa: S310
            return json.loads(res.read() or b"null")

    def released(self) -> list[dict]:
        return self._call("GET", "/api/sales-orders?status=RELEASED")

    def ack(self, number: str, accepted: bool, wms_id: str | None, reason: str | None) -> None:
        body = {"accepted": accepted, "wms_order_id": wms_id, "reason": reason}
        self._call("POST", f"/api/sales-orders/{number}/ack", body)

    def post(self, kind: str, key: str, payload: dict) -> None:
        path = "/api/shipments" if kind == "shipment" else "/api/stock"
        self._call("POST", path, payload, {"Idempotency-Key": key})


# ----- signed webhooks ---------------------------------------------------------------------------
def sign(secret: str, timestamp: str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def verify(
    secret: str, timestamp: str, body: bytes, signature: str, now: float | None = None
) -> str | None:
    """None if valid, else why not. The timestamp limits replays to a 5-minute window."""
    if not secret:
        return "webhook not configured (ERP_WEBHOOK_SECRET)"
    try:
        age = abs((now or time.time()) - float(timestamp))
    except ValueError:
        return "bad timestamp"
    if age > SIGNATURE_WINDOW_S:
        return "timestamp too old or in the future"
    if not hmac.compare_digest(sign(secret, timestamp, body), signature or ""):
        return "bad signature"
    return None


# ----- the connector -----------------------------------------------------------------------------
@dataclass
class OutMessage:
    key: str  # idempotency key: the same message is stored once by the ERP
    kind: str  # ack | shipment | stock
    payload: dict
    status: str = "PENDING"  # PENDING | SENT | FAILED
    attempts: int = 0
    next_try: float = 0.0
    error: str | None = None
    created: float = 0.0


class ErpConnector:
    def __init__(
        self,
        engine,
        client,
        poll_minutes: int = 5,
        stock_minutes: int = 60,
        start_worker: bool = True,  # tests call work_once() instead
    ) -> None:
        self.engine = engine
        self.client = client
        tph = engine.config.get("ticks_per_hour", 600)
        self.poll_ticks = max(1, poll_minutes * tph // 60)
        self.stock_ticks = max(1, stock_minutes * tph // 60)
        self.imported: dict[str, str] = {}  # ERP number -> WMS order id
        self.rejected: dict[str, str] = {}  # ERP number -> reason
        self.outbox: deque[OutMessage] = deque(maxlen=2000)
        self.log: deque = deque(maxlen=300)
        self._inbox: deque = deque()  # pulled ERP orders, created on the loop
        self._shipped: set[str] = set()
        self._seq = itertools.count(1)
        self._pull_due = False
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.last_pull: str | None = None
        self.last_error: str | None = None
        if start_worker:
            threading.Thread(target=self._work, name="erp-connector", daemon=True).start()

    @property
    def wms(self):
        return self.engine.inventory.wms

    # ----- on the simulator loop -------------------------------------------------------------
    def after_tick(self) -> None:
        t = self.engine.time
        if t % self.poll_ticks == 0:
            self._pull_due = True
        while self._inbox:
            order = self._inbox.popleft()
            ok, ref = self.receive(order, "pull")
            self._queue("ack", f"ack-{order['number']}", {
                "number": order["number"], "accepted": ok,
                "wms_order_id": ref if ok else None, "reason": None if ok else ref,
            })  # fmt: skip
        for conf in list(self.wms.out.confirmations):
            oid = conf["order_id"]
            rec = self.wms.out.orders.get(oid)
            if oid in self._shipped or rec is None or not rec.external_ref:
                continue
            self._shipped.add(oid)
            self._queue("shipment", f"ship-{oid}", {**conf, "erp_number": rec.external_ref})
        if t % self.stock_ticks == 0 and t > 0:
            levels = {sku: max(0, self.wms.atp(sku)) for sku in sorted(self.wms.inv.items)}
            self._queue("stock", f"stock-{t}", {"tick": t, "levels": levels})

    def receive(self, order: dict, via: str) -> tuple[bool, str]:
        """Turn one ERP sales order into a WMS order. Returns (accepted, WMS id or reason).
        The same ERP number is imported once (a repeated delivery gets the same answer)."""
        number = str(order.get("number", ""))
        if number in self.imported:
            return True, self.imported[number]
        if number in self.rejected:
            return False, self.rejected[number]
        reason = self._check(order)
        if reason:
            self.rejected[number] = reason
            self._note(f"{number} rejected ({via}): {reason}")
            return False, reason
        eng = self.engine
        items = [OrderItem(ln["sku"], int(ln["qty"])) for ln in order["lines"]]
        priority = SERVICE_PRIORITY.get(
            str(order.get("service", "STANDARD")).upper(), Priority.MEDIUM
        )
        sim_order = eng.generator.operator_order(
            eng.next_order_id(), eng.time, priority, items, eng.inventory
        )
        sim_order.source = "ERP"
        self.wms.out.preset[sim_order.order_id] = (order["customer_id"], number)
        eng._add_order(sim_order)
        self.imported[number] = sim_order.order_id
        self._note(f"{number} imported ({via}) as {sim_order.order_id}")
        return True, sim_order.order_id

    def _check(self, order: dict) -> str | None:
        if not order.get("number"):
            return "no order number"
        if order.get("customer_id") not in self.wms.out.customers:
            return f"unknown customer {order.get('customer_id')}"
        lines = order.get("lines") or []
        if not lines:
            return "no order lines"
        for ln in lines:
            if ln.get("sku") not in self.wms.inv.items:
                return f"unknown SKU {ln.get('sku')}"
            if not isinstance(ln.get("qty"), int) or not 1 <= ln["qty"] <= 1000:
                return f"bad quantity for {ln.get('sku')}"
        return None

    def _queue(self, kind: str, key: str, payload: dict) -> None:
        with self._lock:
            self.outbox.append(OutMessage(key, kind, payload, created=time.time()))

    def _note(self, text: str) -> None:
        self.log.appendleft({"at": time.strftime("%H:%M:%S"), "text": text})

    # ----- the worker thread (network) ----------------------------------------------------------
    def _work(self) -> None:
        while not self._stop.wait(0.5):
            self.work_once()

    def work_once(self) -> None:
        """One round of network work: a due pull, then the due outbox messages."""
        if self._pull_due:
            self._pull_due = False
            try:
                orders = self.client.released()
                self.last_pull = time.strftime("%H:%M:%S")
                known = self.imported.keys() | self.rejected.keys()
                self._inbox.extend(o for o in orders if o["number"] not in known)
                self.last_error = None
            except Exception as err:  # noqa: BLE001 - the ERP may be down; try again later
                self.last_error = f"pull: {err}"
        self.deliver()

    def deliver(self) -> None:
        """Send what is due in the outbox, oldest first."""
        now = time.time()
        with self._lock:
            due = [m for m in self.outbox if m.status == "PENDING" and m.next_try <= now]
        for msg in due:
            msg.attempts += 1
            try:
                if msg.kind == "ack":
                    p = msg.payload
                    self.client.ack(p["number"], p["accepted"], p["wms_order_id"], p["reason"])
                else:
                    self.client.post(msg.kind, msg.key, msg.payload)
                msg.status, msg.error = "SENT", None
            except Exception as err:  # noqa: BLE001 - kept and retried
                msg.error = str(err)[:200]
                if msg.attempts >= MAX_ATTEMPTS:
                    msg.status = "FAILED"
                    self._note(f"{msg.key} failed after {msg.attempts} attempts: {msg.error}")
                else:
                    msg.next_try = time.time() + min(300, 2 ** (msg.attempts - 1))

    def retry_failed(self) -> int:
        with self._lock:
            failed = [m for m in self.outbox if m.status == "FAILED"]
            for m in failed:
                m.status, m.attempts, m.next_try = "PENDING", 0, 0.0
        return len(failed)

    def pull_now(self) -> None:
        self._pull_due = True

    def stop(self) -> None:
        self._stop.set()

    def status(self) -> dict:
        with self._lock:
            box = list(self.outbox)
        counts: dict[str, int] = {}
        for m in box:
            counts[m.status] = counts.get(m.status, 0) + 1
        return {
            "client": self.client.kind,
            "imported": len(self.imported),
            "rejected": len(self.rejected),
            "outbox": counts,
            "last_pull": self.last_pull,
            "last_error": self.last_error,
            "poll_minutes": self.poll_ticks * 60 // self.engine.config.get("ticks_per_hour", 600),
            "recent_imports": [
                {"erp_number": k, "wms_order_id": v}
                for k, v in list(self.imported.items())[-15:][::-1]
            ],
            "rejections": [
                {"erp_number": k, "reason": v} for k, v in list(self.rejected.items())[-15:][::-1]
            ],
            "log": list(self.log)[:30],
        }

    def outbox_rows(self, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = list(self.outbox)[-limit:][::-1]
        return [
            {k: v for k, v in asdict(m).items() if k != "payload"} | {"summary": _summary(m)}
            for m in rows
        ]


def _summary(m: OutMessage) -> str:
    p = m.payload
    if m.kind == "ack":
        result = f"accepted as {p['wms_order_id']}" if p["accepted"] else f"rejected: {p['reason']}"
        return f"{p['number']}: {result}"
    if m.kind == "shipment":
        return f"{p.get('erp_number')} / {p.get('order_id')} on {p.get('trip')}"
    return f"stock levels of {len(p.get('levels', {}))} items"

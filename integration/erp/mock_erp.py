"""A small mock ERP for the WMS to talk to (backlog PR-13).

It holds sales orders (RELEASED → ACCEPTED or REJECTED by the warehouse → SHIPPED), and records
what the warehouse sends back: shipment confirmations and stock levels. Use it in-process (the
backend's default) or as its own server:

    python -m integration.erp.mock_erp            # http://127.0.0.1:8100, API key from ERP_API_KEY

API (header X-API-Key):
    GET  /api/sales-orders?status=RELEASED     orders for the warehouse
    POST /api/sales-orders                     create one (for demos and tests)
    POST /api/sales-orders/{number}/ack        {"accepted": true, "wms_order_id": ...} or a reason
    POST /api/shipments                        ship confirmation (idempotent by Idempotency-Key)
    POST /api/stock                            stock levels per SKU (idempotent likewise)
    GET  /api/summary                          what the ERP knows
"""

from __future__ import annotations

import datetime as dt
import hmac
import itertools
import os
import threading

from pydantic import BaseModel, Field


def now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


class MockErp:
    def __init__(self) -> None:
        self.orders: dict[str, dict] = {}
        self.shipments: dict[str, dict] = {}  # idempotency key -> confirmation
        self.stock: dict[str, int] = {}
        self.stock_updated: str | None = None
        self._stock_keys: set[str] = set()
        self.received: dict[str, int] = {"shipments": 0, "stock": 0, "duplicates": 0}
        self._numbers = itertools.count(1001)
        self._lock = threading.Lock()
        self.down = False  # tests: simulate an outage

    def create_order(self, customer_id: str, lines: list[dict], service: str = "STANDARD") -> dict:
        with self._lock:
            number = f"SO-{next(self._numbers)}"
            self.orders[number] = {
                "number": number,
                "customer_id": customer_id,
                "service": service,  # EXPRESS | STANDARD | ECONOMY
                "lines": [{"sku": ln["sku"], "qty": int(ln["qty"])} for ln in lines],
                "status": "RELEASED",
                "created": now(),
                "wms_order_id": None,
                "reason": None,
                "shipped": None,
            }
            return self.orders[number]

    def released(self) -> list[dict]:
        self._check()
        return [o for o in self.orders.values() if o["status"] == "RELEASED"]

    def ack(
        self, number: str, accepted: bool, wms_order_id: str | None, reason: str | None
    ) -> dict:
        self._check()
        order = self.orders[number]
        if order["status"] == "RELEASED":
            order["status"] = "ACCEPTED" if accepted else "REJECTED"
            order["wms_order_id"], order["reason"] = wms_order_id, reason
        return order

    def shipment(self, key: str, confirmation: dict) -> bool:
        """Record a ship confirmation; False for a duplicate (already received with this key)."""
        self._check()
        with self._lock:
            if key in self.shipments:
                self.received["duplicates"] += 1
                return False
            self.shipments[key] = confirmation
            self.received["shipments"] += 1
            for order in self.orders.values():
                if order["wms_order_id"] == confirmation.get("order_id"):
                    order["status"], order["shipped"] = "SHIPPED", confirmation
            return True

    def stock_levels(self, key: str, levels: dict[str, int]) -> bool:
        self._check()
        with self._lock:
            if key in self._stock_keys:
                self.received["duplicates"] += 1
                return False
            self._stock_keys.add(key)
            self.stock, self.stock_updated = dict(levels), now()
            self.received["stock"] += 1
            return True

    def summary(self) -> dict:
        by_status: dict[str, int] = {}
        for o in self.orders.values():
            by_status[o["status"]] = by_status.get(o["status"], 0) + 1
        return {
            "orders": by_status,
            "received": dict(self.received),
            "stock_items": len(self.stock),
            "stock_updated": self.stock_updated,
            "latest_orders": sorted(self.orders.values(), key=lambda o: o["number"])[-20:][::-1],
        }

    def _check(self) -> None:
        if self.down:
            raise ConnectionError("ERP is not reachable")


# Request models at module level: FastAPI must resolve them for the routes below.
class Line(BaseModel):
    sku: str = Field(min_length=1, max_length=30)
    qty: int = Field(ge=1, le=1000)


class OrderIn(BaseModel):
    customer_id: str
    service: str = "STANDARD"
    lines: list[Line] = Field(min_length=1, max_length=20)


class AckIn(BaseModel):
    accepted: bool
    wms_order_id: str | None = None
    reason: str | None = None


def make_app(erp: MockErp, api_key: str):
    """The mock ERP as an HTTP service (FastAPI)."""
    from fastapi import Depends, FastAPI, Header, HTTPException

    def key(x_api_key: str = Header("")) -> None:
        if not hmac.compare_digest(x_api_key.encode(), api_key.encode()):
            raise HTTPException(401, "bad API key")

    app = FastAPI(title="Mock ERP", dependencies=[Depends(key)])

    @app.get("/api/sales-orders")
    def sales_orders(status: str = "RELEASED") -> list[dict]:
        return (
            erp.released()
            if status == "RELEASED"
            else [o for o in erp.orders.values() if o["status"] == status]
        )

    @app.post("/api/sales-orders", status_code=201)
    def create(body: OrderIn) -> dict:
        return erp.create_order(
            body.customer_id, [ln.model_dump() for ln in body.lines], body.service
        )

    @app.post("/api/sales-orders/{number}/ack")
    def ack(number: str, body: AckIn) -> dict:
        if number not in erp.orders:
            raise HTTPException(404, f"no order {number}")
        return erp.ack(number, body.accepted, body.wms_order_id, body.reason)

    @app.post("/api/shipments")
    def shipments(body: dict, idempotency_key: str = Header(...)) -> dict:
        return {"stored": erp.shipment(idempotency_key, body)}

    @app.post("/api/stock")
    def stock(body: dict, idempotency_key: str = Header(...)) -> dict:
        return {"stored": erp.stock_levels(idempotency_key, body.get("levels", {}))}

    @app.get("/api/summary")
    def summary() -> dict:
        return erp.summary()

    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(make_app(MockErp(), os.environ.get("ERP_API_KEY", "dev-erp-key")), port=8100)

"""ERP connection: status, outbox, manual pull, the signed order webhook and the mock ERP
(backlog PR-13)."""

from __future__ import annotations

import json
import random
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.core.auth import Principal, need, require
from app.core.config import get_settings
from app.services.erp import erp
from integration.erp.connector import HttpErp, verify

router = APIRouter(prefix="/erp", tags=["erp"])


def _connector():
    if erp.connector is None:
        raise HTTPException(
            409,
            detail={"code": "off", "message": "The ERP connection needs the WMS (and ERP_ENABLED)"},
        )
    return erp.connector


@router.get("/status", dependencies=[need("dashboard:view")])
async def status() -> dict:
    c = _connector()
    out = c.status()
    out["mock"] = None if isinstance(c.client, HttpErp) else erp.mock.summary()
    out["webhook"] = bool(get_settings().erp_webhook_secret)
    return out


@router.get("/outbox", dependencies=[need("dashboard:view")])
async def outbox(limit: int = Query(100, le=500)) -> list[dict]:
    """Messages to the ERP: acknowledgements, ship confirmations, stock levels, with their state."""
    return _connector().outbox_rows(limit)


@router.post("/pull", dependencies=[need("wms:settings")])
async def pull() -> dict:
    """Fetch released sales orders from the ERP now (normally every few simulated minutes)."""
    _connector().pull_now()
    return {"pull": "requested"}


@router.post("/outbox/retry", dependencies=[need("wms:settings")])
async def retry() -> dict:
    """Send failed messages again (after the ERP is back)."""
    return {"requeued": _connector().retry_failed()}


@router.post("/webhooks/orders")
async def order_webhook(
    request: Request,
    x_erp_timestamp: Annotated[str, Header()] = "",
    x_erp_signature: Annotated[str, Header()] = "",
) -> dict:
    """The ERP pushes a sales order. No user login: the request must carry an HMAC-SHA256
    signature of '{timestamp}.{body}' with ERP_WEBHOOK_SECRET (X-ERP-Signature: sha256=...),
    and a timestamp less than 5 minutes old. The same order number is imported once."""
    body = await request.body()
    problem = verify(get_settings().erp_webhook_secret, x_erp_timestamp, body, x_erp_signature)
    if problem:
        raise HTTPException(401, detail={"code": "signature", "message": problem})
    try:
        order = json.loads(body)
    except ValueError as err:
        raise HTTPException(422, detail="body is not JSON") from err
    accepted, ref = _connector().receive(order, "webhook")
    if not accepted:
        raise HTTPException(422, detail={"code": "rejected", "message": ref})
    return {"accepted": True, "wms_order_id": ref, "erp_number": order.get("number")}


class MockOrderIn(BaseModel):
    customer_id: str | None = None
    service: Literal["EXPRESS", "STANDARD", "ECONOMY"] = "STANDARD"
    lines: list[dict] | None = Field(None, max_length=20)  # [{sku, qty}]; none: two in stock


@router.post("/mock/orders", status_code=201)
async def mock_order(
    body: MockOrderIn, who: Annotated[Principal, Depends(require("orders:create"))]
) -> dict:
    """Demo: a sales order released in the in-process mock ERP (picked up at the next pull)."""
    c = _connector()
    if isinstance(c.client, HttpErp):
        raise HTTPException(
            409, detail={"code": "real_erp", "message": "ERP_URL is set: create orders in that ERP"}
        )
    wms = c.wms
    rng = random.Random()
    customer = body.customer_id or rng.choice(sorted(wms.out.customers))
    lines = body.lines or [
        {"sku": sku, "qty": rng.randint(1, 3)} for sku in rng.sample(wms.orderable(), 2)
    ]
    return erp.mock.create_order(customer, lines, body.service)

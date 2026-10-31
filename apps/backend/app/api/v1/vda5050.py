"""VDA 5050 interface: vehicles, the message log and instant actions (backlog PR-12)."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.auth import Principal, need, require
from app.services.vda5050 import vda
from integration.vda5050 import messages as m
from integration.vda5050.transport import MqttTransport

router = APIRouter(prefix="/vda5050", tags=["vda5050"])


def _ready():
    if vda.master is None:
        raise HTTPException(
            409, detail={"code": "off", "message": "VDA 5050 is off (VDA5050_ENABLED)"}
        )
    return vda


@router.get("/status", dependencies=[need("dashboard:view")])
async def status() -> dict:
    """Transport, message counts and every vehicle's latest state as master control sees it."""
    v = _ready()
    mqtt = isinstance(v.bus, MqttTransport)
    return {
        "transport": v.bus.kind,
        "broker_connected": v.bus.connected if mqtt else None,
        "counts": v.bus.counts,
        "invalid": v.master.invalid[-10:],
        "topic_example": m.topic("R1", "state"),
        "version": m.VERSION,
        "vehicles": v.master.summary(),
    }


@router.get("/messages", dependencies=[need("dashboard:view")])
async def messages(
    serial: str | None = Query(None, max_length=20),
    topic: Literal["order", "instantActions", "state", "connection", "factsheet"] | None = None,
    limit: int = Query(50, le=500),
) -> list[dict]:
    """The latest messages on the bus (newest first), optionally for one vehicle or topic."""
    v = _ready()
    out = []
    for entry in v.bus.log:
        parsed = m.parse_topic(entry["topic"])
        if not parsed or (serial and parsed[1] != serial) or (topic and parsed[2] != topic):
            continue
        out.append(entry)
        if len(out) >= limit:
            break
    return out


class InstantIn(BaseModel):
    serials: list[str] = Field(min_length=1, max_length=100)  # robot ids, or ["all"]
    action: Literal["startPause", "stopPause", "stateRequest", "factsheetRequest", "cancelOrder"]


@router.post("/instant-actions")
async def instant_actions(
    body: InstantIn, who: Annotated[Principal, Depends(require("robots:command"))]
) -> dict:
    """Send an instant action from master control (pause, resume, state or factsheet request)."""
    v = _ready()
    serials = list(v.fleet.vehicles) if body.serials == ["all"] else body.serials
    unknown = [s for s in serials if s not in v.fleet.vehicles]
    if unknown:
        raise HTTPException(404, detail=f"Unknown vehicles: {', '.join(unknown)}")
    ids = v.master.instant_action(serials, body.action)
    return {"action": body.action, "action_ids": ids, "sent_by": who.username}

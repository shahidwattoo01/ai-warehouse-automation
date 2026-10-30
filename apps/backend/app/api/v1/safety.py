"""Fleet safety: emergency stop, release, reset, zone stops, slow zones and the safety log.

Anyone logged in may press the emergency stop (like the red buttons on the floor). Releasing and
resetting it needs `safety:reset`: a release only clears the cause, robots move again only after a
deliberate reset, and the reset is refused while a person stands next to a held robot.
Everything is written to the safety log under the logged-in user.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.auth import Principal, need, require
from app.services.simulator import simulator
from simulation.environment.safety import SafetyError

router = APIRouter(prefix="/safety", tags=["safety"])
Anyone = Annotated[Principal, Depends(require("dashboard:view"))]
Resetter = Annotated[Principal, Depends(require("safety:reset"))]


def _refused(err: Exception) -> HTTPException:
    return HTTPException(409, detail={"code": "refused", "message": str(err)})


def _done(state: dict) -> dict:
    simulator.publish_state()  # every screen shows the stop now, even while paused
    return state


@router.get("/status", dependencies=[need("dashboard:view")])
async def status() -> dict:
    safety = simulator.engine.safety
    return {
        **safety.snapshot(),
        "near_miss_radius": safety.near_radius,
        "zones": [z.zone_id for z in simulator.engine.layout.zones],
        "metrics": dict(safety.metrics),
        "blockers": safety.blockers() if safety.state == "RELEASED" else [],
    }


class StopIn(BaseModel):
    reason: str = Field("Emergency stop button", min_length=3, max_length=120)
    zone: str | None = None  # None = the whole fleet


@router.post("/estop")
async def estop(body: StopIn, who: Anyone) -> dict:
    try:
        return _done(simulator.engine.safety.engage(who.username, body.reason, body.zone))
    except SafetyError as err:
        raise _refused(err) from err


class NoteIn(BaseModel):
    note: str | None = Field(None, max_length=120)


@router.post("/release")
async def release(body: NoteIn, who: Resetter) -> dict:
    try:
        return _done(simulator.engine.safety.release(who.username, body.note))
    except SafetyError as err:
        raise _refused(err) from err


class ResetIn(BaseModel):
    area_checked: bool = False  # confirm a restart although a person is next to a robot


@router.post("/reset")
async def reset(who: Resetter, body: ResetIn | None = None) -> dict:
    try:
        checked = body.area_checked if body else False
        return _done(simulator.engine.safety.reset(who.username, checked))
    except SafetyError as err:
        raise _refused(err) from err


class SettingsIn(BaseModel):
    slow_zones: bool | None = None
    slow_radius: int | None = Field(None, ge=1, le=10)


@router.put("/settings")
async def settings(body: SettingsIn, who: Resetter) -> dict:
    safety = simulator.engine.safety
    changes = body.model_dump(exclude_none=True)
    if "slow_zones" in changes:
        safety.slow_zones = changes["slow_zones"]
    if "slow_radius" in changes:
        safety.slow_radius = changes["slow_radius"]
    if changes:
        safety.record(
            "SETTINGS", "info", f"Safety settings changed: {changes}", user=who.username, **changes
        )
    return safety.snapshot()


@router.get("/events", dependencies=[need("dashboard:view")])
async def events(
    kind: str | None = None,
    severity: str | None = None,
    limit: int = Query(200, le=2000),
) -> list[dict]:
    """The safety log, newest first (this run; earlier runs are in the safety_events table)."""
    rows = [
        e
        for e in simulator.engine.safety.log
        if (kind is None or e["kind"] == kind) and (severity is None or e["severity"] == severity)
    ]
    return rows[:limit]

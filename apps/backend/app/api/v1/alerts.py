"""Alert centre: incidents, acknowledgement, rules and the notification log (backlog PR-32)."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.auth import Principal, need, require
from app.services.alerts import SEVERITY_RANK, AlertCentre, Incident
from app.services.alerts import centre as alert_centre
from app.services.simulator import simulator

router = APIRouter(prefix="/alerts", tags=["alerts"])
Handler = Annotated[Principal, Depends(require("alerts:handle"))]
Configurer = Annotated[Principal, Depends(require("alerts:configure"))]
CHANNELS = ("screen", "email", "webhook")


def _clock(tick: int | None) -> str | None:
    if tick is None:
        return None
    tph = simulator.engine.config.get("ticks_per_hour", 600)
    minutes = tick * 60 // tph
    return f"Day {minutes // 1440 + 1} {minutes // 60 % 24:02d}:{minutes % 60:02d}"


def _row(inc: Incident) -> dict:
    return {
        **inc.to_dict(),
        "name": alert_centre.rules[inc.rule]["name"],
        "opened_time": _clock(inc.opened_tick),
        "resolved_time": _clock(inc.resolved_tick),
        "minutes_open": round(
            ((inc.resolved_tick or simulator.engine.time) - inc.opened_tick)
            * 60
            / simulator.engine.config.get("ticks_per_hour", 600)
        ),
    }


@router.get("", dependencies=[need("dashboard:view")])
async def incidents(
    status: Literal["active", "OPEN", "ACKNOWLEDGED", "RESOLVED", "all"] = "active",
    limit: int = Query(200, le=2000),
) -> dict:
    """Incidents, most urgent first: open before acknowledged, critical before warning."""
    rows = [
        i
        for i in alert_centre.incidents.values()
        if status == "all" or (status == "active" and i.status != "RESOLVED") or i.status == status
    ]
    rows.sort(
        key=lambda i: (i.status == "RESOLVED", i.status == "ACKNOWLEDGED",
                       SEVERITY_RANK[i.severity], -i.opened_tick)
    )  # fmt: skip
    return {"incidents": [_row(i) for i in rows[:limit]], "summary": alert_centre.summary()}


class NoteIn(BaseModel):
    note: str | None = Field(None, max_length=200)


def _act(fn, alert_id: str, user: str, note: str | None) -> dict:
    try:
        return _row(fn(alert_id, user, note, simulator.engine.time))
    except KeyError as err:
        raise HTTPException(404, detail=f"No alert {alert_id}") from err
    except ValueError as err:
        raise HTTPException(409, detail={"code": "refused", "message": str(err)}) from err


@router.post("/{alert_id}/acknowledge")
async def acknowledge(alert_id: str, body: NoteIn, who: Handler) -> dict:
    """I have seen it and I am on it (stops the escalation)."""
    return _act(alert_centre.acknowledge, alert_id, who.username, body.note)


@router.post("/{alert_id}/resolve")
async def resolve(alert_id: str, body: NoteIn, who: Handler) -> dict:
    """Close it by hand; the rule stays quiet for this subject until the cause has cleared."""
    return _act(alert_centre.resolve, alert_id, who.username, body.note)


@router.get("/rules", dependencies=[need("dashboard:view")])
async def rules() -> dict:
    return {"rules": alert_centre.rules, "channels": CHANNELS}


class RuleIn(BaseModel):
    enabled: bool | None = None
    threshold: float | None = Field(None, ge=0, le=100_000)
    escalate_after_min: int | None = Field(None, ge=1, le=24 * 60)
    notify: list[Literal["screen", "email", "webhook"]] | None = None
    escalate_to: list[Literal["screen", "email", "webhook"]] | None = None


@router.put("/rules/{rule_id}")
async def update_rule(rule_id: str, body: RuleIn, who: Configurer) -> dict:
    """Change a rule until the backend restarts (configs/alert_rules.yaml keeps the defaults)."""
    rule = alert_centre.rules.get(rule_id)
    if rule is None:
        raise HTTPException(404, detail=f"No rule {rule_id}")
    changes = body.model_dump(exclude_none=True)
    if "threshold" in changes and rule["threshold"] is None:
        raise HTTPException(
            422, detail={"code": "no_threshold", "message": f"{rule_id} has no threshold"}
        )
    rule.update(changes)
    return {"rule": rule_id, **rule, "changed_by": who.username}


@router.get("/notifications", dependencies=[need("dashboard:view")])
async def notifications(limit: int = Query(100, le=300)) -> list[dict]:
    """Every notification attempt: SHOWN, SENT, FAILED or NOT_CONFIGURED."""
    return list(alert_centre.notifications)[:limit]


class TestIn(BaseModel):
    channel: Literal["email", "webhook"]


@router.post("/test-notification")
async def test_notification(body: TestIn, who: Configurer) -> dict:
    """Send a test message through a channel, to check the email or webhook settings."""
    import asyncio

    inc = Incident(
        "AL-TEST", "test", "test", "info", "Test notification", f"sent by {who.username}", 0, ""
    )
    entry = {"at": None, "alert_id": "AL-TEST", "channel": body.channel, "why": "test",
             "status": "PENDING", "detail": None}  # fmt: skip
    await asyncio.to_thread(AlertCentre._send, body.channel, inc, "test", entry)
    alert_centre.notifications.appendleft(entry)
    return entry

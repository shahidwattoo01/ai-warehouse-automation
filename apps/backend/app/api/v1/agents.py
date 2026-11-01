"""Agents endpoints (TRD Section 7; Phase 8, docs/phase8_agents.md)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.auth import Principal, need, require
from app.services.agents import agents

router = APIRouter(prefix="/agents", tags=["agents"])
User = Annotated[Principal, Depends(require("copilot:use"))]
Approver = Annotated[Principal, Depends(require("copilot:approve"))]


class RunRequest(BaseModel):
    request: str = Field(min_length=2, max_length=500)


@router.post("/run")
async def run(body: RunRequest, user: User) -> dict:
    """Run the operations agent on a request: its steps, answer, sources and the actions that
    wait for approval."""
    return await agents.run(body.request, user.username)


@router.get("/status", dependencies=[need("copilot:use")])
async def status() -> dict:
    """Planner in use, pending actions, scheduled aisle closures."""
    return agents.status()


@router.post("/actions/{action_id}/approve")
async def approve(action_id: str, user: Approver) -> dict:
    """Approve a pending agent action (also needs the action's own permission)."""
    try:
        return agents.approve(action_id, user.username, user.can)
    except PermissionError as err:
        raise HTTPException(403, {"code": "forbidden", "message": str(err)}) from err
    except KeyError as err:
        raise HTTPException(404, {"code": "not_found", "message": str(err)}) from err


@router.post("/actions/{action_id}/reject")
async def reject(action_id: str, user: Approver) -> dict:
    try:
        return agents.reject(action_id, user.username)
    except KeyError as err:
        raise HTTPException(404, {"code": "not_found", "message": str(err)}) from err

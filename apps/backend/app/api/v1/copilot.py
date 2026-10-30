"""Copilot endpoints (TRD Section 7): operator commands in plain language (Phase 6).

    POST /copilot/chat                      understand a message; answer it or propose an action
    POST /copilot/parse                     only the understanding (intent, entities, tool call)
    POST /copilot/actions/{id}/approve      run a proposed write action
    POST /copilot/actions/{id}/reject       discard it
    GET  /copilot/status                    which parser is loaded
    GET  /copilot/history                   audit trail of answered and executed commands

Endpoints are `async def`: they run on the event loop between simulator ticks (see simulation.py).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.auth import Principal, need, require
from app.services.copilot import copilot

router = APIRouter(prefix="/copilot", tags=["copilot"])


class Message(BaseModel):
    text: str = Field(min_length=1, max_length=500, description="The operator's message")


@router.get("/status", dependencies=[need("copilot:use")])
async def status() -> dict:
    """Which command parser is loaded (also starts loading it in the background)."""
    copilot.warm_up()
    return copilot.status()


@router.post("/parse", dependencies=[need("copilot:use")])
async def parse(body: Message) -> dict:
    """Intent, entities with canonical values, the tool call and whether it needs approval."""
    return await copilot.parse(body.text.strip())


# The permission each write tool needs, on top of copilot:approve: approving a copilot action
# never lets anyone do more than the buttons of the app would.
TOOL_PERMISSION = {
    "pause_robot": "robots:command",
    "resume_robot": "robots:command",
    "reroute_robot": "robots:command",
    "close_aisle": "robots:command",
    "open_aisle": "robots:command",
    "create_order": "orders:create",
    "assign_order": "orders:assign",
    "set_assignment_mode": "orders:assign",
}


@router.post("/chat")
async def chat(body: Message, user: Annotated[Principal, Depends(require("copilot:use"))]) -> dict:
    """Operator message -> an answer (read-only commands run at once) or an action to approve."""
    return await copilot.chat(body.text.strip(), user.username)


@router.post("/actions/{action_id}/approve")
async def approve(
    action_id: str, user: Annotated[Principal, Depends(require("copilot:approve"))]
) -> dict:
    """Run a proposed write action (checked again against the warehouse first)."""
    action = copilot.pending(action_id)
    if action:
        missing = sorted(
            {
                TOOL_PERMISSION[c["name"]]
                for c in action["tool_calls"]
                if c["name"] in TOOL_PERMISSION
            }
            - set(user.permissions)
        )
        if missing:
            raise HTTPException(
                403,
                detail={
                    "code": "forbidden",
                    "message": "Your role cannot do this action",
                    "missing": missing,
                },
            )
    return copilot.approve(action_id, user.username)


@router.post("/actions/{action_id}/reject")
async def reject(
    action_id: str, user: Annotated[Principal, Depends(require("copilot:approve"))]
) -> dict:
    return copilot.reject(action_id, user.username)


@router.get("/history", dependencies=[need("copilot:use")])
async def history() -> list[dict]:
    """The last 200 commands: what was asked, the tool calls, and what happened."""
    return list(copilot.history)

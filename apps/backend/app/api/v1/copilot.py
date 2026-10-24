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

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.copilot import copilot

router = APIRouter(prefix="/copilot", tags=["copilot"])


class Message(BaseModel):
    text: str = Field(min_length=1, max_length=500, description="The operator's message")


@router.get("/status")
async def status() -> dict:
    """Which command parser is loaded (also starts loading it in the background)."""
    copilot.warm_up()
    return copilot.status()


@router.post("/parse")
async def parse(body: Message) -> dict:
    """Intent, entities with canonical values, the tool call and whether it needs approval."""
    return await copilot.parse(body.text.strip())


@router.post("/chat")
async def chat(body: Message) -> dict:
    """Operator message -> an answer (read-only commands run at once) or an action to approve."""
    return await copilot.chat(body.text.strip())


@router.post("/actions/{action_id}/approve")
async def approve(action_id: str) -> dict:
    """Run a proposed write action (checked again against the warehouse first)."""
    return copilot.approve(action_id)


@router.post("/actions/{action_id}/reject")
async def reject(action_id: str) -> dict:
    return copilot.reject(action_id)


@router.get("/history")
async def history() -> list[dict]:
    """The last 200 commands: what was asked, the tool calls, and what happened."""
    return list(copilot.history)

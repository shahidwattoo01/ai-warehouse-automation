"""Agents endpoints (TRD Section 7)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1._phase import not_yet

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/run")
def post_agents_0() -> dict:
    """Run an agent task."""
    raise not_yet(8, "Run an agent task")


@router.post("/actions/{action_id}/approve")
def post_agents_1(action_id: str) -> dict:
    """Approve a pending agent action."""
    raise not_yet(8, "Approve a pending agent action")

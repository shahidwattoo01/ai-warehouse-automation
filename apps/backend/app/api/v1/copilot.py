"""Copilot endpoints (TRD Section 7)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1._phase import not_yet

router = APIRouter(prefix="/copilot", tags=["copilot"])


@router.post("/chat")
def post_copilot_0() -> dict:
    """Operator message -> routed answer or action."""
    raise not_yet(10, "Operator message -> routed answer or action")

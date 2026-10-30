"""Tools endpoints (TRD Section 7)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1._phase import not_yet
from app.core.auth import need

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("", dependencies=[need("copilot:use")])
def get_tools_0() -> dict:
    """Tool registry with JSON schemas."""
    raise not_yet(8, "Tool registry with JSON schemas")

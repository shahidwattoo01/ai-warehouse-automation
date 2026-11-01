"""Tools endpoints (TRD Section 7; Phase 8, docs/phase8_agents.md)."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.auth import need
from app.services.agents import agents

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("", dependencies=[need("copilot:use")])
async def get_tools() -> list[dict]:
    """The tool registry: name, description, JSON schema of the arguments, read/write, approval."""
    return agents.registry.schema()

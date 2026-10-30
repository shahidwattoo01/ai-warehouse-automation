"""Navigation endpoints (TRD Section 7)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1._phase import not_yet
from app.core.auth import need

router = APIRouter(prefix="/navigation", tags=["navigation"])


@router.post("/route", dependencies=[need("robots:command")])
def post_navigation_0() -> dict:
    """Route for a robot to a destination (dijkstra | astar | rl)."""
    raise not_yet(4, "Route for a robot to a destination (dijkstra | astar | rl)")


@router.post("/reroute", dependencies=[need("robots:command")])
def post_navigation_1() -> dict:
    """Replace a robot's active route."""
    raise not_yet(4, "Replace a robot's active route")

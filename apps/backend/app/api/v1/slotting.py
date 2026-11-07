"""Slotting optimisation endpoints (Phase 9, PR-10): heatmap and manual reslot trigger."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import Principal, need, require
from app.services.simulator import simulator

router = APIRouter(prefix="/slotting", tags=["slotting"])
Manager = Annotated[Principal, Depends(require("simulation:control"))]


@router.get("/heatmap", dependencies=[need("analytics:view")])
async def slotting_heatmap() -> dict:
    """Return per-cell pick-velocity matrix for the slotting heatmap visualisation."""
    eng = simulator.engine
    opt = getattr(eng, "slotting", None)
    if opt is None:
        return {"enabled": False, "cells": []}

    # Build (row, col, velocity) triples from the optimiser's velocity window.
    cells: list[dict] = []
    picks = getattr(opt, "_picks", {})   # {product_id: deque of ticks}
    layout = eng.layout_snapshot()
    # Map product → rack cell using the engine inventory index.
    inv = getattr(eng, "inventory", {})
    product_locations: dict[str, tuple[int, int]] = {}
    for cell_key, cell_data in inv.items():
        if isinstance(cell_data, dict) and "product_id" in cell_data:
            pid = cell_data["product_id"]
            if isinstance(cell_key, (tuple, list)) and len(cell_key) == 2:
                product_locations[pid] = (int(cell_key[0]), int(cell_key[1]))

    for pid, tick_deque in picks.items():
        velocity = len(tick_deque)   # picks in rolling window
        loc = product_locations.get(pid)
        if loc:
            cells.append({"product_id": pid, "row": loc[0], "col": loc[1], "velocity": velocity})

    # Also expose total swaps performed this run.
    swaps = getattr(opt, "_total_swaps", 0)
    return {"enabled": True, "cells": cells, "total_swaps": swaps}


@router.post("/reslot")
async def reslot(user: Manager) -> dict:
    """Manually trigger a re-slotting pass right now."""
    eng = simulator.engine
    opt = getattr(eng, "slotting", None)
    if opt is None:
        raise HTTPException(503, {"code": "slotting_unavailable", "message": "Slotting optimiser is not enabled on the running simulation"})

    swaps = opt._reslot(eng)
    return {"swaps": swaps}

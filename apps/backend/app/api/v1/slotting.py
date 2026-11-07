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
    # _pick_counts: {product_id: deque of ticks}; inv.face: {product_id: (col, row)}
    pick_counts = getattr(opt, "_pick_counts", {})
    inv = eng.inventory
    face: dict = getattr(inv, "face", {})   # product_id → (col, row) rack face

    t = eng.time
    for pid, tick_deque in pick_counts.items():
        velocity = opt._velocity(pid, t)
        loc = face.get(pid)
        if loc:
            cells.append({"product_id": pid, "row": loc[1], "col": loc[0], "velocity": velocity})

    # Swaps counter lives on the engine-level slotting attribute when present.
    swaps = getattr(opt, "_total_swaps", None)
    # Fall back: count how many _reslot calls happened via last-reslot tick proxy.
    if swaps is None:
        swaps = 0
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

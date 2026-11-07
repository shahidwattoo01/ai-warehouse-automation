"""Reinforcement-learning endpoints (Phase 9): training status, trigger training, history."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import Principal, need, require
from app.services.simulator import simulator

router = APIRouter(prefix="/rl", tags=["rl"])
Manager = Annotated[Principal, Depends(require("simulation:control"))]


@router.get("/status", dependencies=[need("analytics:view")])
async def rl_status() -> dict:
    """Return current MARL training history and config from the live simulator."""
    eng = simulator.engine
    marl_svc = getattr(eng, "_marl", None)
    history: list[dict] = []
    cfg: dict = {}

    if marl_svc is not None:
        history = getattr(marl_svc, "_training_history", [])
        raw_cfg = getattr(marl_svc, "cfg", None)
        if raw_cfg is not None:
            import dataclasses
            cfg = dataclasses.asdict(raw_cfg)

    return {
        "enabled": marl_svc is not None,
        "episodes_completed": cfg.get("episodes", 0) if history else 0,
        "config": cfg,
        "history": history,
    }


@router.post("/train")
async def rl_train(user: Manager) -> dict:
    """Trigger an asynchronous MARL training run (non-blocking; check /rl/status for progress)."""
    eng = simulator.engine
    marl_svc = getattr(eng, "_marl", None)
    if marl_svc is None:
        raise HTTPException(503, {"code": "marl_unavailable", "message": "MARL is not configured on the running simulation"})

    import asyncio
    from ai.reinforcement_learning.env import WarehouseEnv

    def _train():
        env_factory = lambda seed: WarehouseEnv(eng, seed=seed)
        return marl_svc.train(env_factory)

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _train)
    return {
        "version": result.version,
        "metrics": result.metrics,
        "artifact_path": str(result.artifact_path),
    }


@router.get("/history", dependencies=[need("analytics:view")])
async def rl_history() -> list[dict]:
    """Return per-episode training history (mean reward, eps, deliveries)."""
    eng = simulator.engine
    marl_svc = getattr(eng, "_marl", None)
    if marl_svc is None:
        return []
    return getattr(marl_svc, "_training_history", [])

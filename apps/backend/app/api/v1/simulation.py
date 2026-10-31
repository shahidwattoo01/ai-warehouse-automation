"""Simulator controls, state and live stream (TRD 7, FR-SIM-04).

Endpoints are `async def` so they run on the event loop between ticks, never concurrently with one.
"""

from __future__ import annotations

import asyncio
import contextlib

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from ai.optimization.optimizer import experiment_presets
from app.core.auth import need, principal_from_token
from app.schemas.simulation import AssignmentModeRequest, SpeedRequest, StrategyRequest
from app.services.simulator import simulator
from simulation.environment.engine import Command

router = APIRouter(prefix="/simulation", tags=["simulation"])


@router.get("/state", dependencies=[need("dashboard:view")])
async def get_state() -> dict:
    """Full warehouse_state, including inventory."""
    return simulator.engine.state()


@router.get("/layout", dependencies=[need("dashboard:view")])
async def get_layout() -> dict:
    """3D scene geometry: shelves, stations, zones, blocked cells, one-way aisles."""
    return simulator.engine.layout_snapshot()


@router.post("/start", dependencies=[need("simulation:control")])
async def start() -> dict:
    simulator.engine.start()
    simulator.publish_state()
    return {"running": True}


@router.post("/pause", dependencies=[need("simulation:control")])
async def pause() -> dict:
    simulator.engine.pause()
    simulator.publish_state()  # the loop stops broadcasting: tell clients the run is paused
    return {"running": False}


@router.put("/speed", dependencies=[need("simulation:control")])
async def set_speed(body: SpeedRequest) -> dict:
    simulator.engine.set_speed(body.multiplier)
    return {"speed": simulator.engine.speed}


@router.get("/assignment-mode", dependencies=[need("dashboard:view")])
async def get_assignment_mode() -> dict:
    """auto: the dispatcher assigns waiting orders; manual: orders wait for an operator."""
    return {"mode": "auto" if simulator.engine.dispatcher.auto else "manual"}


@router.put("/assignment-mode", status_code=202, dependencies=[need("orders:assign")])
async def set_assignment_mode(body: AssignmentModeRequest) -> dict:
    simulator.engine.submit(Command("set_assignment_mode", {"auto": body.mode == "auto"}))
    return {"queued": "set_assignment_mode", "mode": body.mode}


@router.get("/strategy", dependencies=[need("dashboard:view")])
async def get_strategy() -> dict:
    """Decision rules in use (Phase 4) and the experiment presets that can be switched to."""
    presets = experiment_presets()
    return {
        "preset": simulator.preset,
        "strategies": simulator.strategies,
        "presets": {
            k: {"name": v["name"], "description": v["description"]} for k, v in presets.items()
        },
    }


@router.put("/strategy", dependencies=[need("simulation:control")])
async def set_strategy(body: StrategyRequest) -> dict:
    """Switch to an experiment preset (e.g. E2 baseline, E5 fully optimised) or set strategies."""
    if body.preset:
        presets = experiment_presets()
        if body.preset not in presets:
            raise HTTPException(404, f"unknown preset {body.preset}")
        strategies = simulator.set_strategies(presets[body.preset]["strategies"], body.preset)
    else:
        changes = body.model_dump(exclude_none=True, exclude={"preset"})
        strategies = simulator.set_strategies({**simulator.strategies, **changes})
    return {"preset": simulator.preset, "strategies": strategies}


@router.get("/recovery", dependencies=[need("dashboard:view")])
async def recovery_status() -> dict:
    """Saved-state status: last snapshot, what start-up restored, this instance's role."""
    s = simulator.settings
    return {
        **simulator.recovery.status(),
        "role": simulator.role,
        "ha_mode": s.ha_mode,
        "every_seconds": s.snapshot_seconds,
    }


@router.post("/snapshot", dependencies=[need("simulation:control")])
async def snapshot_now() -> dict:
    """Save the warehouse state now (e.g. before maintenance)."""
    if not simulator.recovery.enabled:
        raise HTTPException(409, {"code": "recovery_off", "message": "Recovery needs JWT_SECRET"})
    return await simulator.save_state()


@router.post("/reset", dependencies=[need("simulation:control")])
async def reset() -> dict:
    await simulator.reset()
    return {"reset": True, "tick": simulator.engine.time}


@router.websocket("/stream")
async def stream(ws: WebSocket) -> None:
    """Layout once, then one state frame per tick. Origin is checked by OriginCheckMiddleware.

    Authentication: browsers cannot add headers to a WebSocket, and a token in the URL would end
    up in logs, so the first message must be {"type": "auth", "token": "<access token>"} within
    5 seconds. Without a valid token (permission dashboard:view) the socket closes with 4401.
    """
    await ws.accept()
    try:
        hello = await asyncio.wait_for(ws.receive_json(), timeout=5)
        user = await asyncio.to_thread(principal_from_token, hello.get("token"))
        if not user.can("dashboard:view"):
            raise HTTPException(403)
    except (TimeoutError, HTTPException, ValueError, KeyError, AttributeError, WebSocketDisconnect):
        with contextlib.suppress(RuntimeError, WebSocketDisconnect):
            await ws.close(code=4401, reason="authentication required")
        return
    queue = simulator.subscribe()
    try:
        await ws.send_text(simulator.layout_message())
        await ws.send_text(simulator.tick_message())
        while True:
            await ws.send_text(await queue.get())
    except (WebSocketDisconnect, RuntimeError):
        # The browser left (page change, closed tab). The stream never reads from the client, so
        # this is noticed on the next send: uvicorn raises RuntimeError for a send after close.
        pass
    finally:
        simulator.unsubscribe(queue)

"""Simulator controls, state and live stream (TRD 7, FR-SIM-04).

Endpoints are `async def` so they run on the event loop between ticks, never concurrently with one.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from ai.optimization.optimizer import experiment_presets
from app.schemas.simulation import AssignmentModeRequest, SpeedRequest, StrategyRequest
from app.services.simulator import simulator
from simulation.environment.engine import Command

router = APIRouter(prefix="/simulation", tags=["simulation"])


@router.get("/state")
async def get_state() -> dict:
    """Full warehouse_state, including inventory."""
    return simulator.engine.state()


@router.get("/layout")
async def get_layout() -> dict:
    """3D scene geometry: shelves, stations, zones, blocked cells, one-way aisles."""
    return simulator.engine.layout_snapshot()


@router.post("/start")
async def start() -> dict:
    simulator.engine.start()
    return {"running": True}


@router.post("/pause")
async def pause() -> dict:
    simulator.engine.pause()
    return {"running": False}


@router.put("/speed")
async def set_speed(body: SpeedRequest) -> dict:
    simulator.engine.set_speed(body.multiplier)
    return {"speed": simulator.engine.speed}


@router.get("/assignment-mode")
async def get_assignment_mode() -> dict:
    """auto: the dispatcher assigns waiting orders; manual: orders wait for an operator."""
    return {"mode": "auto" if simulator.engine.dispatcher.auto else "manual"}


@router.put("/assignment-mode", status_code=202)
async def set_assignment_mode(body: AssignmentModeRequest) -> dict:
    simulator.engine.submit(Command("set_assignment_mode", {"auto": body.mode == "auto"}))
    return {"queued": "set_assignment_mode", "mode": body.mode}


@router.get("/strategy")
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


@router.put("/strategy")
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


@router.post("/reset")
async def reset() -> dict:
    await simulator.reset()
    return {"reset": True, "tick": simulator.engine.time}


@router.websocket("/stream")
async def stream(ws: WebSocket) -> None:
    """Layout once, then one state frame per tick. Origin is checked by OriginCheckMiddleware."""
    await ws.accept()
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

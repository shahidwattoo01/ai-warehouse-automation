"""Fleet endpoints (TRD 7). Writes go through simulator commands, never direct mutation."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.services.simulator import simulator
from simulation.environment.engine import Command
from simulation.warehouse.entities import Robot

router = APIRouter(prefix="/robots", tags=["robots"])


def _robot(robot_id: str) -> Robot:
    robot = simulator.engine.robots.get(robot_id)
    if robot is None:
        raise HTTPException(
            404, detail={"code": "not_found", "message": f"Robot {robot_id} not found"}
        )
    return robot


def _describe(robot: Robot) -> dict:
    return {**robot.to_dict(), **simulator.engine.controller.activity(robot)}


@router.get("")
async def list_robots() -> list[dict]:
    return [_describe(r) for r in simulator.engine.robots.values()]


@router.get("/{robot_id}")
async def get_robot(robot_id: str) -> dict:
    return _describe(_robot(robot_id))


@router.post("/{robot_id}/pause", status_code=202)
async def pause_robot(robot_id: str) -> dict:
    _robot(robot_id)
    simulator.engine.submit(Command("pause_robot", {"robot_id": robot_id}))
    return {"queued": "pause_robot", "robot_id": robot_id}


@router.post("/{robot_id}/resume", status_code=202)
async def resume_robot(robot_id: str) -> dict:
    _robot(robot_id)
    simulator.engine.submit(Command("resume_robot", {"robot_id": robot_id}))
    return {"queued": "resume_robot", "robot_id": robot_id}

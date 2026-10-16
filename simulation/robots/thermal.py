"""Drive-motor temperature: a simple heat balance per robot, updated every tick.

    temperature += heat - cooling * (temperature - ambient)

Driving heats the motor (more with a load), lifting at a rack or packing bay heats it a little,
and charging warms the battery pack. An `overheating` fault (environment/faults.py) adds a large
heat source; above `throttle_at` the robot slows down to protect itself. Equilibrium values with
the default settings: idle 24 C, driving ~39 C, driving loaded ~44 C. An overheating fault pushes
the motor towards 74 C (parked) or 89 C (driving); during a 60-160 tick fault it typically reaches
45-80 C and often passes the 60 C throttle point.
No randomness is used, so adding temperatures does not change any other behaviour.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from simulation.environment.engine import SimulationEngine

DEFAULTS = {
    "ambient": 24.0,
    "heat_moving": 0.15,
    "heat_loaded": 0.05,
    "heat_working": 0.06,
    "heat_charging": 0.08,
    "heat_fault": 0.5,
    "cooling": 0.01,
    "throttle_at": 60.0,
}


def thermal_config(config: dict) -> dict:
    return {**DEFAULTS, **config.get("thermal", {})}


def update_temperatures(engine: SimulationEngine) -> None:
    """Call once per tick, after the robots have moved."""
    cfg = engine.thermal
    ctl = engine.controller
    for robot in engine.robots.values():
        rid = robot.robot_id
        moves = ctl.recent_moves.get(rid)
        task = ctl.tasks.get(rid)
        heat = 0.0
        if moves and moves[-1]:
            heat += cfg["heat_moving"] + (cfg["heat_loaded"] if robot.load else 0.0)
        if task and task.stage in ("PICKING", "DROPPING"):
            heat += cfg["heat_working"]
        if task and task.stage == "CHARGING":
            heat += cfg["heat_charging"]
        if engine.faults.heating(rid):
            heat += cfg["heat_fault"]
        robot.temperature += heat - cfg["cooling"] * (robot.temperature - cfg["ambient"])

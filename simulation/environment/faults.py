"""Fault injection: battery spikes, speed degradation, stop events, route deviation and
overheating — labelled (TR-SIM-07).

Every injected fault emits ROBOT_FAULT with is_injected_fault=True and stays "active" for a
window of ticks, so recorders can label telemetry for anomaly-detection training.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from simulation.events.events import Event, EventType
from simulation.warehouse.entities import RobotStatus

if TYPE_CHECKING:
    from simulation.environment.engine import SimulationEngine


@dataclass
class ActiveFault:
    type: str
    started: int
    until: int


class FaultInjector:
    def __init__(self, engine: SimulationEngine) -> None:
        self.engine = engine
        self.rng = engine.stream("faults")
        cfg = engine.config.get("faults", {})
        self.enabled: bool = cfg.get("enabled", False)
        self.types: list[str] = cfg.get("types", [])
        ticks_per_hour = engine.config.get("ticks_per_hour", 3600)
        # Per robot, per tick.
        self.p_tick: float = cfg.get("probability_per_hour", 0.0) / max(ticks_per_hour, 1)
        self.active: dict[str, ActiveFault] = {}

    def label(self, robot_id: str) -> str | None:
        """Ground-truth fault type affecting this robot right now (None = healthy)."""
        fault = self.active.get(robot_id)
        return fault.type if fault else None

    def slowed(self, robot_id: str) -> bool:
        """The robot only advances on every other tick: speed degradation, or thermal throttling
        while its motor is above the throttle temperature."""
        if not self.engine.time % 2:
            return False
        fault = self.active.get(robot_id)
        if fault and fault.type == "speed_degradation":
            return True
        return self.engine.robots[robot_id].temperature >= self.engine.thermal["throttle_at"]

    def heating(self, robot_id: str) -> bool:
        """An overheating fault is still adding heat (it stays labelled while cooling down)."""
        fault = self.active.get(robot_id)
        return bool(fault and fault.type == "overheating" and self.engine.time < fault.until)

    def speed_factor(self, robot_id: str) -> float:
        """Share of normal speed the robot can drive at right now (known from telemetry)."""
        fault = self.active.get(robot_id)
        hot = self.engine.robots[robot_id].temperature >= self.engine.thermal["throttle_at"]
        return 0.5 if (fault and fault.type == "speed_degradation") or hot else 1.0

    def step(self) -> None:
        eng = self.engine
        cooled = eng.thermal["throttle_at"] - 5
        for rid, fault in list(self.active.items()):
            if fault.type == "overheating" and eng.robots[rid].temperature >= cooled:
                continue  # labelled until the motor has cooled below the throttle zone
            if eng.time >= fault.until:
                del self.active[rid]
                robot = eng.robots[rid]
                if robot.status == RobotStatus.FAULT:
                    robot.status = eng.controller.status_for(robot)
                eng.events.emit(
                    Event(eng.time, EventType.FAULT_CLEARED, rid, {"fault": fault.type}, True)
                )

        if not self.enabled or not self.types or self.p_tick <= 0:
            return
        for robot in eng.robots.values():
            if robot.robot_id in self.active or robot.status == RobotStatus.PAUSED:
                continue
            if self.rng.random() < self.p_tick:
                self.inject(robot.robot_id, self.rng.choice(self.types))

    def inject(self, robot_id: str, fault_type: str) -> None:
        eng = self.engine
        robot = eng.robots[robot_id]
        payload: dict = {"fault": fault_type}
        if fault_type == "battery_spike":
            drop = round(self.rng.uniform(12, 30), 1)
            robot.battery = max(0.0, robot.battery - drop)
            payload["battery_drop"] = drop
            duration = 10  # label window around the spike
        elif fault_type == "speed_degradation":
            duration = self.rng.randint(40, 120)
        elif fault_type == "stop_event":
            duration = self.rng.randint(15, 60)
            robot.status = RobotStatus.FAULT
        elif fault_type == "route_deviation":
            duration = self.rng.randint(20, 50)
            eng.controller.detour(robot)
        elif fault_type == "overheating":
            duration = self.rng.randint(60, 160)  # heat source; the label lasts until cooled
        else:
            return
        self.active[robot_id] = ActiveFault(fault_type, eng.time, eng.time + duration)
        payload["duration"] = duration
        eng.events.emit(
            Event(eng.time, EventType.ROBOT_FAULT, robot_id, payload, is_injected_fault=True)
        )

"""Aisle closures and floor hazards: temporary blocked paths and obstacles (TR-SIM-07).

Two kinds of disruption, both random but reproducible (they draw from the engine's one RNG):

    aisle closure   a whole picking aisle is shut for maintenance, a spill or a rack inspection.
                    No route enters it; orders that need a rack in it wait until it reopens.
    floor hazard    a dropped parcel (PACKAGE) or a fallen pallet (DEBRIS) on a highway cell.
                    It is detected at once (fleet cameras) and robots plan around it until a
                    worker clears it.

Both mark cells in `grid.closed`, which every planner skips, and emit events, so the datasets,
the 3D view (barriers, parcels, pallets) and the camera dataset all see the same disruptions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from simulation.events.events import Event, EventType
from simulation.warehouse.entities import Obstacle
from simulation.warehouse.grid import CellType

if TYPE_CHECKING:
    from simulation.environment.engine import SimulationEngine

Cell = tuple[int, int]

CLOSURE_REASONS = ["maintenance", "spill cleanup", "rack inspection"]
STATION_CLEARANCE = 2  # no floor hazard this close (Manhattan metres) to a station


@dataclass
class Closure:
    hazard_id: str
    aisle_id: str
    name: str
    cells: list[Cell]
    reason: str
    started: int
    until: int


class Hazards:
    def __init__(self, engine: SimulationEngine) -> None:
        self.engine = engine
        self.rng = engine.stream("hazards")
        cfg = engine.config.get("hazards", {})
        self.enabled: bool = cfg.get("enabled", False)
        ticks_per_hour = max(engine.config.get("ticks_per_hour", 3600), 1)
        self.ticks_per_minute = ticks_per_hour / 60
        # Rates are warehouse-wide, per simulated hour; converted to a chance per tick.
        self.p_closure: float = cfg.get("closures_per_hour", 0.0) / ticks_per_hour
        self.closure_minutes: list[float] = cfg.get("closure_minutes", [10, 40])
        self.max_closures: int = cfg.get("max_closures", 2)
        self.p_floor: float = cfg.get("floor_hazards_per_hour", 0.0) / ticks_per_hour
        self.floor_minutes: list[float] = cfg.get("floor_hazard_minutes", [3, 12])
        self.max_floor: int = cfg.get("max_floor_hazards", 3)

        self.closures: dict[str, Closure] = {}  # aisle_id -> active closure
        self.floor: list[Obstacle] = []  # active parcels and pallets
        self._seq = 0

        layout = engine.layout
        grid = layout.grid
        stations = [(s.x, s.y) for s in layout.stations]
        # Open two-way floor where something can lie without trapping anyone: all four
        # neighbours walkable, not a one-way aisle, not a parking bay, clear of the stations.
        self.highway: list[Cell] = [
            (x, y)
            for y in range(grid.height)
            for x in range(grid.width)
            if grid.get(x, y) == CellType.FLOOR
            and (x, y) not in grid.one_way
            and (x, y) not in grid.destination_only
            and all(
                grid.is_walkable(x + dx, y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
            )
            and all(abs(x - sx) + abs(y - sy) > STATION_CLEARANCE for sx, sy in stations)
        ]

    # ----- per tick ------------------------------------------------------------------
    def step(self) -> None:
        eng = self.engine
        for closure in list(self.closures.values()):
            if eng.time >= closure.until:
                self._reopen(closure)
        for obstacle in list(self.floor):
            if obstacle.until is not None and eng.time >= obstacle.until:
                self._clear(obstacle)
        if not self.enabled:
            return
        if self.p_closure and len(self.closures) < self.max_closures:
            if self.rng.random() < self.p_closure:
                self.close_random_aisle()
        if self.p_floor and len(self.floor) < self.max_floor:
            if self.rng.random() < self.p_floor:
                self.drop_random_hazard()

    def _next_id(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}-{self._seq:04d}"

    def _minutes_to_ticks(self, lo_hi: list[float]) -> int:
        return max(1, round(self.rng.uniform(*lo_hi) * self.ticks_per_minute))

    # ----- aisle closures ------------------------------------------------------------
    def close_random_aisle(self) -> Closure | None:
        """Close an aisle nobody is in or needs: no robot, worker or remaining pick stop."""
        eng = self.engine
        ctl = eng.controller
        busy = {r.position for r in eng.robots.values()} | {o.position for o in eng.obstacles}
        needed = {c for t in ctl.tasks.values() for c in t.stops} | set(ctl.goal.values())
        candidates = [
            a
            for a in eng.layout.aisles
            if a.aisle_id not in self.closures and not (set(a.cells) & (busy | needed))
        ]
        if not candidates:
            return None
        aisle = self.rng.choice(candidates)
        return self.close_aisle(aisle.aisle_id, self.rng.choice(CLOSURE_REASONS))

    def close_aisle(self, aisle_id: str, reason: str, ticks: int | None = None) -> Closure | None:
        eng = self.engine
        aisle = next((a for a in eng.layout.aisles if a.aisle_id == aisle_id), None)
        if aisle is None or aisle_id in self.closures:
            return None
        duration = ticks or self._minutes_to_ticks(self.closure_minutes)
        closure = Closure(
            self._next_id("CLS"),
            aisle.aisle_id,
            aisle.name,
            aisle.cells,
            reason,
            eng.time,
            eng.time + duration,
        )
        self.closures[aisle_id] = closure
        self._block(set(aisle.cells))
        eng.events.emit(
            Event(
                eng.time,
                EventType.AISLE_CLOSED,
                aisle_id,
                {"hazard_id": closure.hazard_id, "reason": reason, "until": closure.until},
            )
        )
        return closure

    def _reopen(self, closure: Closure) -> None:
        eng = self.engine
        del self.closures[closure.aisle_id]
        eng.layout.grid.closed.difference_update(closure.cells)
        eng.events.emit(
            Event(
                eng.time, EventType.AISLE_OPENED, closure.aisle_id, {"hazard_id": closure.hazard_id}
            )
        )

    # ----- floor hazards -------------------------------------------------------------
    def drop_random_hazard(self) -> Obstacle | None:
        eng = self.engine
        taken = (
            {r.position for r in eng.robots.values()}
            | {o.position for o in eng.obstacles}
            | eng.layout.grid.closed
        )
        free = [c for c in self.highway if c not in taken]
        if not free:
            return None
        cell = self.rng.choice(free)
        kind = "PACKAGE" if self.rng.random() < 0.7 else "DEBRIS"
        return self.add_floor_hazard(cell, kind)

    def add_floor_hazard(self, cell: Cell, kind: str, ticks: int | None = None) -> Obstacle:
        eng = self.engine
        duration = ticks or self._minutes_to_ticks(self.floor_minutes)
        obstacle = Obstacle(cell, kind, eng.time + duration, self._next_id("HZD"))
        eng.obstacles.append(obstacle)  # after the workers, so their indices never shift
        self.floor.append(obstacle)
        self._block({cell})
        eng.events.emit(
            Event(
                eng.time,
                EventType.HAZARD_DETECTED,
                obstacle.obstacle_id,
                {"kind": kind, "cell": list(cell), "until": obstacle.until},
            )
        )
        return obstacle

    def _clear(self, obstacle: Obstacle) -> None:
        eng = self.engine
        self.floor.remove(obstacle)
        eng.obstacles.remove(obstacle)
        eng.layout.grid.closed.discard(obstacle.position)
        eng.events.emit(
            Event(eng.time, EventType.HAZARD_CLEARED, obstacle.obstacle_id, {"kind": obstacle.type})
        )

    # ----- shared --------------------------------------------------------------------
    def _block(self, cells: set[Cell]) -> None:
        """Close cells to routing and send everyone whose route crosses them another way."""
        eng = self.engine
        eng.layout.grid.closed |= cells
        for robot in eng.robots.values():
            if robot.route and cells.intersection(robot.route):
                eng.controller.reroute(robot)
        for i, route in enumerate(eng.workers.routes):
            if cells.intersection(route):
                eng.workers.routes[i] = []

    def snapshot(self) -> list[dict]:
        """Active closures for the live state (the 3D view draws barriers at both ends)."""
        return [
            {
                "hazard_id": c.hazard_id,
                "aisle_id": c.aisle_id,
                "name": c.name,
                "reason": c.reason,
                "cells": [list(cell) for cell in c.cells],
                "until": c.until,
            }
            for c in self.closures.values()
        ]

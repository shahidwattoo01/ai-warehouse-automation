"""Warehouse associates walking between waypoints: dynamic obstacles for the robots (TR-SIM-07)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from simulation.warehouse.entities import Obstacle

if TYPE_CHECKING:
    from simulation.environment.engine import SimulationEngine

Cell = tuple[int, int]

# Used when a layout does not list its own waypoints (the small default layout).
DEFAULT_WAYPOINTS: list[Cell] = [
    (20, 1),
    (20, 26),
    (2, 13),
    (37, 13),
    (10, 14),
    (30, 14),
    (20, 7),
    (20, 20),
    (5, 1),
    (35, 1),
    (12, 27),
    (28, 27),
]


class Workers:
    def __init__(self, engine: SimulationEngine) -> None:
        self.engine = engine
        spec = engine.layout.workers
        grid = engine.layout.grid
        waypoints = [tuple(w) for w in spec.get("waypoints", [])] or DEFAULT_WAYPOINTS
        self.waypoints: list[Cell] = [w for w in waypoints if grid.is_walkable(*w)]
        self.ticks_per_step: int = engine.config.get("workers", {}).get("ticks_per_step", 2)
        count = spec.get("count", engine.config.get("workers", {}).get("count", 0))

        # Workers are the first `count` entries of engine.obstacles, in order.
        self.positions: list[Cell] = []
        self.routes: list[list[Cell]] = []
        for i in range(count):
            start = self.waypoints[(i * 3) % len(self.waypoints)]
            self.positions.append(start)
            self.routes.append([])
            engine.obstacles.append(Obstacle(start, "WORKER"))

    def step(self) -> None:
        """Walk one cell every `ticks_per_step` ticks (about 1 m/s); give way to robots."""
        eng = self.engine
        if not self.positions or eng.time % self.ticks_per_step:
            return
        robot_cells = {r.position for r in eng.robots.values()}
        for i, pos in enumerate(self.positions):
            route = self.routes[i]
            if not route:
                self.routes[i] = eng.planner.plan(
                    eng.layout.grid, pos, eng.rng.choice(self.waypoints)
                )
                continue
            nxt = route[0]
            others = {p for j, p in enumerate(self.positions) if j != i}
            if nxt in robot_cells or nxt in others or nxt in eng.layout.grid.closed:
                if eng.rng.random() < 0.2:  # sometimes give up and pick a new destination
                    self.routes[i] = []
                continue
            route.pop(0)
            self.positions[i] = nxt
            eng.obstacles[i] = Obstacle(nxt, "WORKER")

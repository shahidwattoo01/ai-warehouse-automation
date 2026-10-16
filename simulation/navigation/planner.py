"""Shared planner interface (TRD TR-OPT-02). BFS (baseline), Dijkstra and A* (Phase 4,
ai/optimization/) and later the RL policy all implement it."""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from collections import deque

from simulation.warehouse.grid import Grid

Cell = tuple[int, int]


class Planner(ABC):
    name: str = "base"

    @abstractmethod
    def plan(
        self,
        grid: Grid,
        start: Cell,
        goal: Cell,
        blocked: set[Cell] | None = None,
        rng: random.Random | None = None,
    ) -> list[Cell]:
        """Return the cells from start (exclusive) to goal (inclusive); [] if unreachable.

        `rng` breaks ties between equally short paths at random, so robots heading the same way
        spread over parallel aisles instead of driving nose-to-tail in a convoy.
        """


class BFSPlanner(Planner):
    """Baseline: the route with the fewest cells (every step costs the same, traffic ignored)."""

    name = "bfs"

    def plan(
        self,
        grid: Grid,
        start: Cell,
        goal: Cell,
        blocked: set[Cell] | None = None,
        rng: random.Random | None = None,
    ) -> list[Cell]:
        blocked = blocked or set()
        turn = (
            rng.randrange(4) if rng else 0
        )  # one random direction preference per route (cheap tie-break)
        came_from: dict[Cell, Cell | None] = {start: None}
        queue = deque([start])
        while queue:
            current = queue.popleft()
            if current == goal:
                break
            options = grid.neighbors(*current)
            if turn:
                k = turn % len(options) if options else 0
                options = options[k:] + options[:k]
            for nxt in options:
                if nxt in grid.destination_only and nxt != goal:
                    continue  # parking bays are entered only as the destination
                if nxt in grid.closed:
                    continue  # closed aisle (maintenance, spill): no entry, not even as a goal
                if nxt not in came_from and nxt not in blocked:
                    came_from[nxt] = current
                    queue.append(nxt)
        if goal not in came_from:
            return []
        path, node = [], goal
        while node != start:
            path.append(node)
            node = came_from[node]  # type: ignore[assignment]
        return list(reversed(path))


PLANNERS = ("bfs", "dijkstra", "astar")


def get_planner(name: str, traffic=None) -> Planner:
    """Factory. `traffic` (ai.optimization.traffic.TrafficCosts) makes Dijkstra / A* avoid jams;
    without it they plan on distance only."""
    if name == "bfs":
        return BFSPlanner()
    if name == "dijkstra":
        from ai.optimization.dijkstra import DijkstraPlanner

        return DijkstraPlanner(traffic)
    if name == "astar":
        from ai.optimization.astar import AStarPlanner

        return AStarPlanner(traffic)
    raise ValueError(f"unknown planner {name!r}; choose one of {PLANNERS}")

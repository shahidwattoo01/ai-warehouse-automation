"""Dijkstra planner: cheapest route when steps can cost different amounts (Phase 4).

Implements simulation.navigation.planner.Planner, so the simulator can use it in place of BFS.
BFS finds the route with the fewest cells; Dijkstra finds the route with the lowest *total cost*,
where each step costs 1 plus the live traffic cost of the cell (ai/optimization/traffic.py).
With no traffic costs both return equally short routes.

It always expands the cheapest partial route first (a priority queue), so the first time it
reaches the goal, that route is the cheapest. Rules are the same as BFS: one-way aisles, parking
bays only as the destination, closed cells never.
"""

from __future__ import annotations

import heapq
import random
from typing import TYPE_CHECKING

from simulation.navigation.planner import Planner
from simulation.warehouse.grid import Grid

if TYPE_CHECKING:
    from ai.optimization.traffic import TrafficCosts

Cell = tuple[int, int]


def manhattan(a: Cell, b: Cell) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


class DijkstraPlanner(Planner):
    name = "dijkstra"
    heuristic_weight = 0.0  # A* sets this to 1: guide the search toward the goal

    def __init__(self, traffic: TrafficCosts | None = None) -> None:
        self.traffic = traffic  # None: every step costs 1 (pure distance)

    def plan(
        self,
        grid: Grid,
        start: Cell,
        goal: Cell,
        blocked: set[Cell] | None = None,
        rng: random.Random | None = None,
    ) -> list[Cell]:
        blocked = blocked or set()
        cost_of = self.traffic.cost if self.traffic else None
        # Random tie-break between equally cheap routes, as BFS does (spreads robots out).
        jitter = rng.random() * 1e-3 if rng else 0.0
        best: dict[Cell, float] = {start: 0.0}
        came_from: dict[Cell, Cell] = {}
        frontier: list[tuple[float, int, Cell]] = [(0.0, 0, start)]
        order = 0
        while frontier:
            _, _, current = heapq.heappop(frontier)
            if current == goal:
                break
            base = best[current]
            for nxt in grid.neighbors(*current):
                if nxt in blocked or nxt in grid.closed:
                    continue
                if nxt in grid.destination_only and nxt != goal:
                    continue
                step = 1.0
                if cost_of and nxt != goal:
                    step += cost_of(nxt)
                if jitter:
                    step += jitter * ((hash(nxt) % 7) / 7)
                cost = base + step
                if cost < best.get(nxt, float("inf")):
                    best[nxt] = cost
                    came_from[nxt] = current
                    order += 1
                    priority = cost + self.heuristic_weight * manhattan(nxt, goal)
                    heapq.heappush(frontier, (priority, order, nxt))
        if goal not in best:
            return []
        path, node = [], goal
        while node != start:
            path.append(node)
            node = came_from[node]
        return list(reversed(path))

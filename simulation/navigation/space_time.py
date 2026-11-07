"""Space-time A* path reservation (PR-04).

Extends the existing planner family so robots reserve (cell, tick) slots and avoid
head-on meetings.  Also provides deadlock detection via a waiting-for graph, and
intersection priority rules.

Public API
----------
SpaceTimeTable          reservation store shared by all robots in one engine tick
SpaceTimePlanner        Planner subclass that honours the table's reservations
detect_deadlock(table)  returns a cycle (list of robot_ids) or []
resolve_deadlock(engine, cycle)  makes the lowest-priority robot back off
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from simulation.navigation.planner import Planner
from simulation.warehouse.entities import Priority

if TYPE_CHECKING:
    from simulation.environment.engine import SimulationEngine
    from simulation.warehouse.grid import Grid

Cell = tuple[int, int]

# Right-of-way ranking for intersection priority: HIGH orders beat MEDIUM beat LOW beat no-order.
_PRIORITY_RANK: dict[str | None, int] = {
    Priority.HIGH.value: 0,
    Priority.MEDIUM.value: 1,
    Priority.LOW.value: 2,
    None: 3,
}


# ---------------------------------------------------------------------------
# Reservation table
# ---------------------------------------------------------------------------

@dataclass
class SpaceTimeTable:
    """Global reservation store: maps (tick, cell) → robot_id.

    Each robot claims the cell it will occupy at each future tick along its planned route.
    A planner queries `is_free(cell, tick)` before committing a step.
    """

    _table: dict[int, dict[Cell, str]] = field(default_factory=lambda: defaultdict(dict))
    horizon: int = 60  # ticks ahead to hold reservations

    def reserve(self, robot_id: str, path: list[Cell], start_tick: int) -> None:
        """Replace any existing reservations for `robot_id` with its new planned path."""
        self.release(robot_id)
        for offset, cell in enumerate(path):
            tick = start_tick + offset
            if tick - start_tick < self.horizon:
                self._table[tick][cell] = robot_id

    def release(self, robot_id: str) -> None:
        """Remove all reservations for `robot_id` (called on task completion or replanning)."""
        for tick_map in self._table.values():
            to_del = [c for c, rid in tick_map.items() if rid == robot_id]
            for c in to_del:
                del tick_map[c]

    def is_free(self, cell: Cell, tick: int, requesting: str) -> bool:
        """True when `cell` is not reserved at `tick` by any other robot."""
        occupant = self._table.get(tick, {}).get(cell)
        return occupant is None or occupant == requesting

    def sweep(self, current_tick: int) -> None:
        """Remove past ticks to bound memory."""
        stale = [t for t in self._table if t < current_tick]
        for t in stale:
            del self._table[t]

    def waiting_for(self, robot_id: str, current_tick: int) -> str | None:
        """Return the robot that holds the next cell this robot is waiting for, if any."""
        # The robot is 'waiting' when its very next step (current_tick+1) is reserved by another.
        occupant = None
        for cell, rid in self._table.get(current_tick + 1, {}).items():
            if rid != robot_id:
                occupant = rid
                break
        return occupant


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------

class SpaceTimePlanner(Planner):
    """Space-time A*: plans routes that avoid cells reserved by other robots.

    Falls back to the standard A* path when no reservation-aware route exists (safety net:
    the simulator's existing traffic-wait logic then handles any residual conflicts).
    """

    name = "space_time"

    def __init__(self, table: SpaceTimeTable) -> None:
        self.table = table

    def plan(
        self,
        grid: "Grid",
        start: Cell,
        goal: Cell,
        blocked: set[Cell] | None = None,
        rng=None,
        current_tick: int = 0,
        robot_id: str = "",
    ) -> list[Cell]:
        blocked = blocked or set()
        # State: (cell, tick) — standard A* over (space, time)
        from heapq import heappop, heappush

        def h(c: Cell) -> int:
            return abs(c[0] - goal[0]) + abs(c[1] - goal[1])

        open_heap: list[tuple[int, int, Cell, int]] = []
        # (f, g, cell, tick)
        heappush(open_heap, (h(start), 0, start, current_tick))
        came_from: dict[tuple[Cell, int], tuple[Cell, int] | None] = {(start, current_tick): None}
        g_score: dict[tuple[Cell, int], int] = {(start, current_tick): 0}

        max_ticks = current_tick + grid.width + grid.height + self.table.horizon

        while open_heap:
            _, g, cell, tick = heappop(open_heap)

            if cell == goal:
                # Reconstruct path
                path: list[Cell] = []
                state: tuple[Cell, int] | None = (cell, tick)
                while state is not None:
                    path.append(state[0])
                    state = came_from[state]
                path.reverse()
                return path[1:]  # exclude start

            if tick > max_ticks:
                break

            for nxt in grid.neighbors(*cell):
                if nxt in blocked:
                    continue
                if nxt in grid.destination_only and nxt != goal:
                    continue
                if nxt in grid.closed:
                    continue
                next_tick = tick + 1
                # Space-time constraint: cell must be free at next_tick
                if not self.table.is_free(nxt, next_tick, robot_id):
                    # Allow waiting in place for one tick then retry
                    wait_tick = tick + 1
                    wait_state = (cell, wait_tick)
                    tentative_g = g + 1
                    if tentative_g < g_score.get(wait_state, 10**9):
                        g_score[wait_state] = tentative_g
                        came_from[wait_state] = came_from.get((cell, tick), None) and (cell, tick)
                        heappush(open_heap, (tentative_g + h(cell), tentative_g, cell, wait_tick))
                    continue
                new_state = (nxt, next_tick)
                tentative_g = g + 1
                if tentative_g < g_score.get(new_state, 10**9):
                    g_score[new_state] = tentative_g
                    came_from[new_state] = (cell, tick)
                    heappush(open_heap, (tentative_g + h(nxt), tentative_g, nxt, next_tick))

        # Fallback: plain BFS ignoring reservations
        from simulation.navigation.planner import BFSPlanner
        return BFSPlanner().plan(grid, start, goal, blocked, rng)


# ---------------------------------------------------------------------------
# Deadlock detection and resolution
# ---------------------------------------------------------------------------

def _build_waiting_graph(
    engine: "SimulationEngine",
    table: SpaceTimeTable,
) -> dict[str, str]:
    """Return a dict {robot_id: blocked_by_robot_id} for currently blocked robots."""
    waiting: dict[str, str] = {}
    for rid, robot in engine.robots.items():
        if not robot.route:
            continue
        nxt = robot.route[0]
        # Check who holds the next cell at the next tick
        occupant = table._table.get(engine.time + 1, {}).get(nxt)
        if occupant and occupant != rid:
            waiting[rid] = occupant
    return waiting


def detect_deadlock(engine: "SimulationEngine", table: SpaceTimeTable) -> list[str]:
    """Return a cycle of robot_ids forming a deadlock, or [] if none."""
    waiting = _build_waiting_graph(engine, table)
    visited: set[str] = set()
    for start in waiting:
        if start in visited:
            continue
        path: list[str] = []
        seen: dict[str, int] = {}
        node = start
        while node in waiting and node not in seen:
            seen[node] = len(path)
            path.append(node)
            node = waiting[node]
            visited.add(node)
        if node in seen:
            return path[seen[node]:]  # the cycle
    return []


def resolve_deadlock(engine: "SimulationEngine", table: SpaceTimeTable, cycle: list[str]) -> None:
    """Break a deadlock: the lowest-priority robot in the cycle backs off one cell."""
    if not cycle:
        return
    ctl = engine.controller
    tasks = ctl.tasks

    def priority_rank(rid: str) -> int:
        t = tasks.get(rid)
        if t and t.kind == "order":
            order = engine.orders.get(t.order_id)
            if order:
                return _PRIORITY_RANK.get(order.priority.value, 3)
        return 3  # no order = lowest priority

    victim = max(cycle, key=priority_rank)
    robot = engine.robots.get(victim)
    if robot is None or not robot.route:
        return
    occupied = {r.position for r in engine.robots.values() if r.robot_id != victim}
    ctl._back_off(robot, occupied)
    table.release(victim)
    if robot.route:
        full_path = [robot.position, *robot.route]
        table.reserve(victim, full_path, engine.time)

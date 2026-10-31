"""Route distances to a goal from every cell, computed once and cached (Phase 4).

Choosing a robot for an order means comparing how far each candidate is from the order's first
rack. Planning a full route per candidate would repeat almost the same search many times, so
instead one search runs *backwards* from the goal over the reversed graph (respecting one-way
aisles, parking bays and closed cells). The result is the legal route length from every cell to
that goal. Fields are cached per goal and invalidated whenever the set of closed cells changes.
"""

from __future__ import annotations

from collections import OrderedDict, deque

from simulation.warehouse.grid import Grid

Cell = tuple[int, int]
UNREACHABLE = -1
# Each field holds every reachable cell (~4,000 on the large layout, ~0.4 MB); 2,048 of them could
# reach ~750 MB as orders visit new racks (found by the soak test, docs/load_testing.md). The
# least recently used go first; a miss costs one backwards search (~13 ms on the large layout).
MAX_CACHED = 256


class DistanceFields:
    def __init__(self, grid: Grid) -> None:
        self.grid = grid
        self._fields: OrderedDict[Cell, dict[Cell, int]] = OrderedDict()
        self._closed: set[Cell] = set(grid.closed)

    def __setstate__(self, state: dict) -> None:
        """Snapshots saved before the cache became least-recently-used hold a plain dict."""
        state["_fields"] = OrderedDict(state.get("_fields", {}))
        self.__dict__.update(state)

    def _fresh(self) -> None:
        if self.grid.closed != self._closed:  # an aisle opened/closed, a hazard appeared/cleared
            self._fields.clear()
            self._closed = set(self.grid.closed)

    def field(self, goal: Cell) -> dict[Cell, int]:
        """Legal route length from every reachable cell to `goal`."""
        self._fresh()
        cached = self._fields.get(goal)
        if cached is not None:
            self._fields.move_to_end(goal)
            return cached
        grid = self.grid
        dist = {goal: 0}
        queue = deque([goal])
        while queue:
            current = queue.popleft()
            x, y = current
            for prev in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if prev in dist or not grid.in_bounds(*prev) or prev in grid.closed:
                    continue
                if not grid.can_move(prev, current):  # one-way aisles: only legal moves count
                    continue
                if current in grid.destination_only and current != goal:
                    continue  # a route may not pass through a parking bay
                dist[prev] = dist[current] + 1
                queue.append(prev)
        while len(self._fields) >= MAX_CACHED:
            self._fields.popitem(last=False)
        self._fields[goal] = dist
        return dist

    def distance(self, start: Cell, goal: Cell) -> int:
        """Route length from start to goal, or UNREACHABLE."""
        return self.field(goal).get(start, UNREACHABLE)

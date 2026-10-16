"""Traffic costs for route planning (Phase 4).

The baseline planner counts cells: every step costs 1, so a route through a jammed aisle and a
route through an empty one look the same. Traffic-aware planners add an extra cost per cell from
the current situation, so a slightly longer but free route can win:

    step cost = 1 (the metre itself)
              + OCCUPIED  if a robot stands on the cell right now
              + AISLE     per robot currently inside the same one-way picking aisle
              + ZONE      x congestion of the cell's storage zone (robots / zone capacity)

The costs are rebuilt at most once per tick, from the live engine state. `weight` scales all three
(1.0 = the values above; 0.25 = a gentle preference for free cells).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from simulation.environment.congestion import zone_of

if TYPE_CHECKING:
    from simulation.environment.engine import SimulationEngine

Cell = tuple[int, int]

OCCUPIED = 4.0  # metres a robot will detour to avoid driving into another robot's cell
AISLE = 2.0  # per robot already in a one-robot-wide aisle (one-way: it can only queue)
ZONE = 1.0  # per unit of zone congestion


class TrafficCosts:
    def __init__(self, engine: SimulationEngine, weight: float = 1.0) -> None:
        self.engine = engine
        self.weight = weight
        layout = engine.layout
        self.aisle_of: dict[Cell, str] = {c: a.aisle_id for a in layout.aisles for c in a.cells}
        self.zone_at: dict[Cell, str | None] = {}
        self._tick = -1
        self._extra: dict[Cell, float] = {}

    def _rebuild(self) -> None:
        eng = self.engine
        positions = [r.position for r in eng.robots.values()]
        in_aisle: dict[str, int] = {}
        for pos in positions:
            aisle = self.aisle_of.get(pos)
            if aisle:
                in_aisle[aisle] = in_aisle.get(aisle, 0) + 1
        w = self.weight
        extra: dict[Cell, float] = {}
        for pos in positions:
            extra[pos] = extra.get(pos, 0.0) + w * OCCUPIED
        for cell, aisle in self.aisle_of.items():
            if aisle in in_aisle:
                extra[cell] = extra.get(cell, 0.0) + w * AISLE * in_aisle[aisle]
        self._zone_cost = {z: w * ZONE * c for z, c in eng.congestion.items() if c > 0}
        self._extra = extra
        self._tick = eng.time

    def cost(self, cell: Cell) -> float:
        """Extra cost (beyond 1) of stepping onto `cell`."""
        if self._tick != self.engine.time:
            self._rebuild()
        extra = self._extra.get(cell, 0.0)
        if self._zone_cost:
            zone = self.zone_at.get(cell, "?")
            if zone == "?":
                zone = self.zone_at[cell] = zone_of(self.engine.layout.zones, cell)
            if zone:
                extra += self._zone_cost.get(zone, 0.0)
        return extra

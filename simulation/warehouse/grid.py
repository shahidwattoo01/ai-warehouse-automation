"""Grid model of the warehouse floor (TRD 4.1). 1 cell = 1 m in the 3D view."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class CellType(str, Enum):
    FLOOR = "."
    SHELF = "S"
    BLOCKED = "#"
    PACKING = "P"
    CHARGING = "C"


WALKABLE = {CellType.FLOOR, CellType.PACKING, CellType.CHARGING}


@dataclass
class Grid:
    width: int
    height: int
    cells: list[list[CellType]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.cells:
            self.cells = [[CellType.FLOOR] * self.width for _ in range(self.height)]
        self._neighbors: dict[tuple[int, int], list[tuple[int, int]]] = {}
        # One-way cells: (x, y) -> +1 (travel east only) or -1 (west only) along the row.
        self.one_way: dict[tuple[int, int], int] = {}
        # Cells a route may end in but not pass through (parking bays).
        self.destination_only: set[tuple[int, int]] = set()
        # Temporarily closed cells (an aisle shut for maintenance or a spill): no route enters them.
        self.closed: set[tuple[int, int]] = set()

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def get(self, x: int, y: int) -> CellType:
        return self.cells[y][x]

    def set(self, x: int, y: int, cell: CellType) -> None:
        self.cells[y][x] = cell
        self._neighbors.clear()

    def set_one_way(self, x: int, y: int, dx: int) -> None:
        """Narrow aisle cell: horizontal travel only in direction dx (+1 east, -1 west)."""
        self.one_way[(x, y)] = dx
        self._neighbors.clear()

    def set_destination_only(self, x: int, y: int) -> None:
        self.destination_only.add((x, y))

    def is_walkable(self, x: int, y: int) -> bool:
        return self.in_bounds(x, y) and self.get(x, y) in WALKABLE

    def can_move(self, a: tuple[int, int], b: tuple[int, int]) -> bool:
        """Directed check: one-way aisles forbid travelling against their direction."""
        if not self.is_walkable(*b):
            return False
        dx = b[0] - a[0]
        if dx:
            for cell in (a, b):
                rule = self.one_way.get(cell)
                if rule is not None and rule != dx:
                    return False
        return True

    def neighbors(self, x: int, y: int) -> list[tuple[int, int]]:
        """4-connected cells reachable in one move (TRD TR-OPT-01); directed in one-way aisles."""
        hit = self._neighbors.get((x, y))
        if hit is None:
            candidates = [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
            hit = self._neighbors[(x, y)] = [c for c in candidates if self.can_move((x, y), c)]
        return list(hit)

    def to_ascii(self) -> str:
        arrows = {1: ">", -1: "<"}
        return "\n".join(
            "".join(
                arrows.get(self.one_way.get((x, y)), c.value) if c == CellType.FLOOR else c.value
                for x, c in enumerate(row)
            )
            for y, row in enumerate(self.cells)
        )

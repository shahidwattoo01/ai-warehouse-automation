"""Load a warehouse layout config (configs/layouts/*.yaml) into a grid and entities.

Racking and one-way entries accept either a single row (`y`, `x_start`, `x_end`) or many rows and
segments at once (`ys: [...]`, `x_ranges: [[x0, x1], ...]`), so dense layouts stay readable.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from simulation.warehouse.entities import Shelf, Station, Zone
from simulation.warehouse.grid import CellType, Grid

CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs"

Cell = tuple[int, int]


@dataclass
class ParkingArea:
    area_id: str
    name: str
    cells: list[Cell]


@dataclass
class Aisle:
    """A narrow one-way picking aisle between two rack rows ("Aisle 7")."""

    aisle_id: str  # AISLE_07
    name: str  # Aisle 7
    zone_id: str | None
    y: int
    x_start: int
    x_end: int
    direction: str  # east | west

    @property
    def cells(self) -> list[Cell]:
        return [(x, self.y) for x in range(self.x_start, self.x_end + 1)]


@dataclass
class Layout:
    name: str
    grid: Grid
    zones: list[Zone]
    shelves: list[Shelf]
    stations: list[Station]
    robot_config: dict
    parking: list[Cell] = field(default_factory=list)  # every parking bay
    parking_areas: list[ParkingArea] = field(default_factory=list)
    spawn: list[Cell] = field(default_factory=list)  # robot start cells, spread over the areas
    workers: dict = field(default_factory=dict)  # {count, waypoints}
    # One-way aisle segments [{y, x_start, x_end, dir}], drawn as floor arrows in 3D.
    one_way: list[dict] = field(default_factory=list)
    # The same segments as named aisles, numbered in reading order (north-west first).
    aisles: list[Aisle] = field(default_factory=list)


def _rows(entry: dict) -> Iterator[tuple[int, int, int]]:
    """Expand an entry into (y, x_start, x_end) triples."""
    ys = entry.get("ys", [entry.get("y")])
    ranges = entry.get("x_ranges", [[entry.get("x_start"), entry.get("x_end")]])
    for y in ys:
        for x0, x1 in ranges:
            yield y, x0, x1


def _spread(areas: list[ParkingArea], count: int) -> list[Cell]:
    """Start positions taken round-robin across parking areas, evenly spaced inside each."""
    queues = []
    for area in areas:
        share = -(-count // len(areas)) if areas else 0  # ceil(count / areas)
        n = min(share, len(area.cells))
        queues.append([area.cells[i * len(area.cells) // n] for i in range(n)] if n else [])
    spawn: list[Cell] = []
    while len(spawn) < count and any(queues):
        for q in queues:
            if q and len(spawn) < count:
                spawn.append(q.pop(0))
    return spawn


def load_layout(name: str = "default", config_dir: Path = CONFIG_DIR) -> Layout:
    raw = yaml.safe_load((config_dir / "layouts" / f"{name}.yaml").read_text())
    grid = Grid(raw["grid"]["width"], raw["grid"]["height"])

    zones = [Zone(z["zone_id"], z["name"], tuple(z["bounds"]), z["capacity"]) for z in raw["zones"]]

    shelves: list[Shelf] = []
    for entry in raw.get("racking", []):
        for y, x0, x1 in _rows(entry):
            for x in range(x0, x1 + 1):
                shelf_id = f"SH-{entry['zone'][-1]}-{y:02d}-{x:02d}"
                shelves.append(Shelf(shelf_id, entry["zone"], x, y, entry.get("levels", 4)))
                grid.set(x, y, CellType.SHELF)

    for b in raw.get("blocked", []):
        for dx in range(b["w"]):
            for dy in range(b["h"]):
                grid.set(b["x"] + dx, b["y"] + dy, CellType.BLOCKED)

    one_way: list[dict] = []
    for entry in raw.get("one_way", []):
        step = 1 if entry["dir"] == "east" else -1
        for y, x0, x1 in _rows(entry):
            for x in range(x0, x1 + 1):
                grid.set_one_way(x, y, step)
            one_way.append({"y": y, "x_start": x0, "x_end": x1, "dir": entry["dir"]})

    stations = []
    for s in raw.get("stations", []):
        stations.append(Station(s["station_id"], s["type"], s["x"], s["y"], s.get("capacity", 1)))
        grid.set(s["x"], s["y"], CellType.PACKING if s["type"] == "PACKING" else CellType.CHARGING)

    areas: list[ParkingArea] = []
    for a in raw.get("parking_areas", []):
        (x0, x1), (y0, y1) = a["x"], a["y"]
        cells = [
            (x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1) if grid.is_walkable(x, y)
        ]
        for cell in cells:
            grid.set_destination_only(*cell)  # parked robots never block through-traffic
        areas.append(ParkingArea(a["area_id"], a["name"], cells))
    parking = [c for area in areas for c in area.cells]
    spawn = _spread(areas, raw["robots"]["count"])

    def zone_at(x: int, y: int) -> str | None:
        return next((z.zone_id for z in zones if z.contains(x, y)), None)

    segments = sorted(one_way, key=lambda s: (s["y"], s["x_start"]))
    aisles = [
        Aisle(
            f"AISLE_{i:02d}",
            f"Aisle {i}",
            zone_at((s["x_start"] + s["x_end"]) // 2, s["y"]),
            s["y"],
            s["x_start"],
            s["x_end"],
            s["dir"],
        )
        for i, s in enumerate(segments, start=1)
    ]

    return Layout(
        raw["name"],
        grid,
        zones,
        shelves,
        stations,
        raw["robots"],
        parking=parking,
        parking_areas=areas,
        spawn=spawn,
        workers=raw.get("workers", {}),
        one_way=one_way,
        aisles=aisles,
    )

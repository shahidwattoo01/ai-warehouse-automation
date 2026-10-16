"""Congestion per zone/aisle = occupancy / capacity, every tick (TR-SIM-06)."""

from __future__ import annotations

from simulation.warehouse.entities import Zone

Cell = tuple[int, int]


def zone_of(zones: list[Zone], cell: Cell) -> str | None:
    """First zone containing the cell, or None for open floor (cross aisles, service lanes)."""
    for zone in zones:
        if zone.contains(*cell):
            return zone.zone_id
    return None


def zone_congestion(zones: list[Zone], positions: list[Cell]) -> dict[str, float]:
    """Robots in each zone divided by the zone's capacity (1.0 = at capacity, >1 = over)."""
    counts = {z.zone_id: 0 for z in zones}
    for pos in positions:
        zid = zone_of(zones, pos)
        if zid:
            counts[zid] += 1
    return {z.zone_id: round(counts[z.zone_id] / max(z.capacity, 1), 3) for z in zones}

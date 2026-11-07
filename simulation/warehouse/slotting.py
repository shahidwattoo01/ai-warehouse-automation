"""Slotting optimisation: assign fast-moving SKUs to rack faces nearest packing stations (PR-10).

Algorithm
---------
1. Count how many times each SKU was picked in the last `velocity_window_hours` of simulated time.
2. Rank SKUs by pick frequency (velocity) — the top N are "fast movers".
3. Rank rack locations by Manhattan distance to the nearest packing station — lowest = best.
4. Swap fast movers into the best available slots and slow movers into vacated slots.
5. Update `Inventory.face` so future routes use the new locations.

The re-slot is triggered by `SlottingOptimiser.maybe_reslot(engine)` once per simulated day
(configurable via `slotting.reoptimise_every_hours`).  It only runs when `slotting.enabled`
is true in the simulation config.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from simulation.environment.engine import SimulationEngine

Cell = tuple[int, int]


@dataclass
class SlottingOptimiser:
    """Tracks pick counts and re-slots the warehouse periodically."""

    enabled: bool = True
    reoptimise_every_ticks: int = 600 * 24   # once per simulated day
    velocity_window_ticks: int = 600 * 168   # 7-day rolling window
    _pick_counts: dict[str, deque] = field(default_factory=lambda: defaultdict(deque))
    _last_reslot_tick: int = -1

    @classmethod
    def from_config(cls, cfg: dict) -> "SlottingOptimiser":
        s = cfg.get("slotting", {})
        tph = cfg.get("ticks_per_hour", 600)
        return cls(
            enabled=s.get("enabled", False),
            reoptimise_every_ticks=round(s.get("reoptimise_every_hours", 24) * tph),
            velocity_window_ticks=round(s.get("velocity_window_hours", 168) * tph),
        )

    def record_pick(self, product_id: str, tick: int) -> None:
        """Record a pick event for velocity tracking."""
        self._pick_counts[product_id].append(tick)

    def _velocity(self, product_id: str, current_tick: int) -> int:
        """Pick count for `product_id` in the recent velocity window."""
        cutoff = current_tick - self.velocity_window_ticks
        counts = self._pick_counts[product_id]
        while counts and counts[0] < cutoff:
            counts.popleft()
        return len(counts)

    def maybe_reslot(self, engine: "SimulationEngine") -> int:
        """Re-slot if due; return number of swaps made (0 = nothing changed)."""
        if not self.enabled:
            return 0
        t = engine.time
        if t - self._last_reslot_tick < self.reoptimise_every_ticks:
            return 0
        self._last_reslot_tick = t
        return self._reslot(engine)

    def _reslot(self, engine: "SimulationEngine") -> int:
        """Execute the slotting swap; return number of product-to-slot reassignments."""
        inv = engine.inventory
        layout = engine.layout
        t = engine.time

        # All SKUs with a rack face
        products = list(inv.face.keys())
        if not products:
            return 0

        # Rank SKUs by velocity (descending)
        by_velocity = sorted(products, key=lambda p: self._velocity(p, t), reverse=True)

        # Rank all rack faces by distance to nearest packing station
        packers = [(s.x, s.y) for s in layout.stations if s.type == "PACKING"]
        if not packers:
            return 0

        def dist_to_pack(face: Cell) -> int:
            return min(abs(face[0] - px) + abs(face[1] - py) for px, py in packers)

        # Only consider faces that belong to rack shelves (not charging/packing bays)
        all_faces: list[Cell] = list(inv.face.values())
        faces_ranked = sorted(set(all_faces), key=dist_to_pack)

        # Build current face→product reverse map
        face_to_product: dict[Cell, str] = {v: k for k, v in inv.face.items()}

        # Assign top-velocity SKUs to best-ranked faces
        swaps = 0
        for rank, (product, target_face) in enumerate(zip(by_velocity, faces_ranked)):
            current_face = inv.face[product]
            if current_face == target_face:
                continue
            # Swap with whatever product currently sits at the target face
            displaced = face_to_product.get(target_face)
            if displaced and displaced == product:
                continue
            # Perform the swap
            inv.face[product] = target_face
            face_to_product[target_face] = product
            if displaced:
                inv.face[displaced] = current_face
                face_to_product[current_face] = displaced
            swaps += 1

        return swaps

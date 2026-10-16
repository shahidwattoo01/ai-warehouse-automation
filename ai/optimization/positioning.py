"""Demand-aware positioning and predictive charging (Phase 4).

Both use the Phase 3 demand forecasts produced by ai/classical_ml/live_predictor.py.

Positioning: when a robot finishes an order it parks. The baseline picks a close bay in a
not-too-full parking area. Here a bay also gets a bonus when its area is next to the storage zone
the demand-breakdown model expects to be busiest this hour, so idle robots wait where the next
orders will be:

    bonus(bay) = WEIGHT * (zone share of forecast order lines - 1/4) / (1/4)

Charging: the baseline tops up idle robots below 70 % whenever no order waits. Here the threshold
follows the total-demand forecast: quiet hour (forecast below QUIET x the recent average) -> top up
to a higher level now (85 %); busy hour (above BUSY x average) -> only top up below 50 %, so robots
stay on orders; otherwise the baseline 70 %.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from ai.classical_ml.live_predictor import Predictor
    from simulation.environment.engine import SimulationEngine

Cell = tuple[int, int]

WEIGHT = 30.0  # metres of parking cost removed for a zone with double its usual share
ZONE_TARGET = {
    "ZONE_A": "lines_zone_a",
    "ZONE_B": "lines_zone_b",
    "ZONE_C": "lines_zone_c",
    "ZONE_D": "lines_zone_d",
}
QUIET, BUSY = 0.8, 1.2
TOP_UP = {"quiet": 85.0, "normal": 70.0, "busy": 50.0}


class DemandPositioning:
    def __init__(self, engine: SimulationEngine, predictor: Predictor) -> None:
        self.engine = engine
        self.predictor = predictor
        zones = {z.zone_id: z for z in engine.layout.zones if z.zone_id in ZONE_TARGET}

        def nearest_zone(cells: list[Cell]) -> str:
            cx = sum(c[0] for c in cells) / len(cells)
            cy = sum(c[1] for c in cells) / len(cells)

            def gap(z) -> float:
                x0, y0, x1, y1 = z.bounds
                return max(x0 - cx, 0, cx - x1) + max(y0 - cy, 0, cy - y1)

            return min(zones, key=lambda zid: gap(zones[zid]))

        self.zone_of_bay: dict[Cell, str] = {
            cell: nearest_zone(area.cells)
            for area in engine.layout.parking_areas
            for cell in area.cells
        }
        self._hour = -1
        self._bonus: dict[str, float] = {}

    def _refresh(self) -> None:
        hour = self.engine.time // self.predictor.tph
        if hour == self._hour:
            return
        self._hour = hour
        forecasts = {
            z: self.predictor.forecasts.get(t, {}).get(hour) for z, t in ZONE_TARGET.items()
        }
        total = sum(v for v in forecasts.values() if v)
        self._bonus = (
            {z: WEIGHT * ((v or 0) / total - 0.25) / 0.25 for z, v in forecasts.items()}
            if total
            else {}
        )

    def bias(self, bay: Cell) -> float:
        """Metres of parking cost removed for `bay` this hour."""
        self._refresh()
        return self._bonus.get(self.zone_of_bay.get(bay, ""), 0.0)


class PredictiveCharging:
    def __init__(self, engine: SimulationEngine, predictor: Predictor) -> None:
        self.engine = engine
        self.predictor = predictor
        self.mode = "normal"

    def threshold(self) -> float:
        """Top-up threshold for this hour, from the demand forecast vs the recent level."""
        hour = self.engine.time // self.predictor.tph
        forecasts = self.predictor.forecasts.get("orders_total", {})
        now = forecasts.get(hour)
        recent = [forecasts[h] for h in range(max(0, hour - 24), hour) if h in forecasts]
        if now is None or len(recent) < 3:
            self.mode = "normal"
        else:
            level = float(np.mean(recent))
            self.mode = (
                "quiet" if now < QUIET * level else "busy" if now > BUSY * level else "normal"
            )
        return TOP_UP[self.mode]

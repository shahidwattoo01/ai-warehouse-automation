"""Predicted delivery time for every candidate robot of an order (Phase 4).

Phase 3's ETA model predicts, at assignment, how many ticks an order will take. Here it is asked
*before* assigning: "if robot R took this order now, how long would it take?" for several
candidates at once. The features are built exactly as the controller would record them if that
robot were chosen (ai/classical_ml/features.py), using cached route distances
(simulation/navigation/distance.py) instead of planning a route per candidate.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import joblib
import numpy as np
import pandas as pd

from ai.classical_ml.features import order_features
from simulation.environment.congestion import zone_of
from simulation.warehouse.entities import OrderStatus

if TYPE_CHECKING:
    from simulation.environment.engine import SimulationEngine
    from simulation.warehouse.entities import Order, Robot

MODEL = Path(__file__).resolve().parents[2] / "models" / "eta_v1.joblib"
Cell = tuple[int, int]


def manhattan(a: Cell, b: Cell) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


class EtaEstimator:
    def __init__(self, engine: SimulationEngine, model_path: Path = MODEL) -> None:
        self.engine = engine
        self.model = joblib.load(model_path)
        self.columns = list(self.model.feature_names_in_)
        self._packers = [(s.x, s.y) for s in engine.layout.stations if s.type == "PACKING"]

    def _route(self, a: Cell, b: Cell) -> int:
        """Legal route length, Manhattan if unreachable now (as the controller records it)."""
        if a == b:
            return 0
        d = self.engine.distances.distance(a, b)
        return d if d > 0 else manhattan(a, b)

    def order_plan(self, order: Order) -> tuple[list[Cell], Cell, int, int]:
        """Pick faces, packing station, and the route / straight distance after the first pick."""
        eng = self.engine
        stops = [eng.inventory.face[i.product_id] for i in order.items]
        station = min(self._packers, key=lambda s: manhattan(s, stops[-1]))
        legs = list(zip(stops, [*stops[1:], station], strict=True))
        rest_route = sum(self._route(a, b) for a, b in legs)
        rest_straight = sum(manhattan(a, b) for a, b in legs)
        return stops, station, rest_route, rest_straight

    def predict(self, order: Order, robots: list[Robot], plan=None) -> np.ndarray:
        """Predicted ticks to deliver `order` for each robot in `robots`."""
        eng = self.engine
        ctl = eng.controller
        stops, _, rest_route, rest_straight = plan or self.order_plan(order)
        shared = {
            "zone_congestion": eng.congestion.get(zone_of(eng.layout.zones, stops[0]) or "", 0.0),
            "fleet_busy": sum(not ctl.available(r) for r in eng.robots.values()),
            "pending_orders": sum(o.status == OrderStatus.PENDING for o in eng.orders.values()),
            "closures_active": len(eng.hazards.closures),
            "floor_hazards_active": len(eng.hazards.floor),
            "assigned_at": eng.time,
            "assigned_hour": eng.sim_hour,
        }
        rows = []
        for robot in robots:
            metrics = {
                **shared,
                "path_distance": self._route(robot.position, stops[0]) + rest_route,
                "est_distance": manhattan(robot.position, stops[0]) + rest_straight,
                "battery_start": round(robot.battery, 2),
                "temperature_start": round(robot.temperature, 1),
                "robot_speed": eng.faults.speed_factor(robot.robot_id),
            }
            rows.append(order_features(eng, order, metrics))
        return self.model.predict(pd.DataFrame(rows)[self.columns])

"""Switch the warehouse from its baseline rules to Phase 4 strategies.

    optimizer = Optimizer(engine, predictor, {"assignment": "eta", "planner": "astar", ...})
    # every tick, after engine.tick():  predictor.after_tick(); optimizer.after_tick()

Strategy keys (the same names as configs/simulation.yaml `strategies` and configs/experiments):

    assignment     nearest | random | eta | global            (ai/optimization/assignment.py)
    planner        bfs | dijkstra | astar                     (dijkstra.py, astar.py)
    traffic_aware  bool: planners add live traffic costs      (ai/optimization/traffic.py)
    traffic_weight strength of the traffic costs (1.0 = full, 0.25 = gentle)
    positioning    balanced | demand                          (ai/optimization/positioning.py)
    charging       threshold | predictive                     (ai/optimization/positioning.py)
    replanning     bool: re-plan long routes every 20 ticks with the current traffic

The baseline values change nothing: an engine with all-baseline strategies behaves exactly as
without an Optimizer.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from ai.optimization.assignment import make_assignment
from ai.optimization.positioning import DemandPositioning, PredictiveCharging
from ai.optimization.traffic import TrafficCosts
from simulation.navigation.planner import get_planner
from simulation.warehouse.entities import RobotStatus

if TYPE_CHECKING:
    from ai.classical_ml.live_predictor import Predictor
    from simulation.environment.engine import SimulationEngine

BASELINE = {
    "assignment": "nearest",
    "planner": "bfs",
    "traffic_aware": False,
    "traffic_weight": 1.0,
    "positioning": "balanced",
    "charging": "threshold",
    "replanning": False,
}
EXPERIMENTS_DIR = Path(__file__).resolve().parents[2] / "configs" / "experiments"
REPLAN_EVERY = 20  # ticks
REPLAN_MIN_ROUTE = 10  # only routes at least this long are worth re-planning


def experiment_presets() -> dict[str, dict]:
    """Phase 4 experiments usable as live presets: id -> {name, description, strategies}."""
    presets = {}
    for path in sorted(EXPERIMENTS_DIR.glob("E*.yaml")):
        cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
        if cfg.get("phase") == 4:
            presets[cfg["experiment_id"]] = {
                "name": cfg["name"],
                "description": " ".join(str(cfg.get("description", "")).split()),
                "strategies": {**BASELINE, **cfg["strategies"]},
            }
    return presets


class Optimizer:
    def __init__(
        self, engine: SimulationEngine, predictor: Predictor | None, strategies: dict
    ) -> None:
        self.engine = engine
        self.predictor = predictor
        self.strategies = {**BASELINE, **{k: v for k, v in strategies.items() if k in BASELINE}}
        s = self.strategies
        needs_forecasts = s["positioning"] == "demand" or s["charging"] == "predictive"
        if needs_forecasts and predictor is None:
            raise ValueError("demand positioning / predictive charging need a Predictor")

        # Every hook is set (or reset to its baseline value), so switching strategies on a running
        # engine, including back to the baseline, always leaves it in a clean state.
        traffic = TrafficCosts(engine, s["traffic_weight"]) if s["traffic_aware"] else None
        engine.planner = get_planner(s["planner"], traffic)
        engine.dispatcher.strategy = make_assignment(s["assignment"], engine)
        engine.dispatcher.top_up_threshold = None
        engine.controller.park_bias = (
            DemandPositioning(engine, predictor).bias if s["positioning"] == "demand" else None
        )
        self.charging = (
            PredictiveCharging(engine, predictor) if s["charging"] == "predictive" else None
        )

    def after_tick(self) -> None:
        eng = self.engine
        if self.charging and eng.time % 60 == 0:
            eng.dispatcher.top_up_threshold = self.charging.threshold()
        if self.strategies["replanning"] and eng.time % REPLAN_EVERY == 0:
            self._replan()

    def _replan(self) -> None:
        """Re-plan long routes with the current traffic (dynamic rerouting)."""
        ctl = self.engine.controller
        for robot in self.engine.robots.values():
            if (
                robot.status in (RobotStatus.PAUSED, RobotStatus.FAULT)
                or len(robot.route) < REPLAN_MIN_ROUTE
            ):
                continue
            task = ctl.tasks.get(robot.robot_id)
            if task and not task.working:
                ctl.reroute(robot)

    def describe(self) -> dict:
        return dict(self.strategies)

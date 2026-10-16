"""Assignment strategies: which free robot takes which waiting order (Phase 4).

The dispatcher (simulation/orders/dispatcher.py) hands every strategy the waiting orders in its
fixed priority order (HIGH first, then oldest) and the free robots (available, battery >= 20 %),
and starts the pairs the strategy returns. Strategies:

    nearest   baseline, built into the dispatcher: the robot closest (straight line) to the
              order's first rack
    random    E1 floor: any free robot (shows how much the baseline itself is worth)
    eta       for each order in turn, the robot the Phase 3 ETA model predicts will FINISH first
              (route distance, battery, motor temperature, speed, congestion, ...)
    global    all waiting orders of one priority at once: the combination of order-robot pairs
              with the lowest TOTAL predicted time (Hungarian algorithm), HIGH orders first
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import numpy as np
from scipy.optimize import linear_sum_assignment

from ai.optimization.eta_estimator import EtaEstimator, manhattan

if TYPE_CHECKING:
    from simulation.environment.engine import SimulationEngine
    from simulation.warehouse.entities import Order, Robot

CANDIDATES = 8  # robots evaluated per order: the closest by route distance
GLOBAL_BATCH = 20  # at most this many waiting orders per priority are optimised together
UNASSIGNABLE = 1e9


class AssignmentStrategy(ABC):
    name = "base"

    def __init__(self, engine: SimulationEngine) -> None:
        self.engine = engine

    @abstractmethod
    def assign(self, orders: list[Order], robots: list[Robot]) -> list[tuple[Order, Robot]]:
        """Pairs to start now. `orders` are in dispatch order; each robot used at most once."""

    def _first_stop(self, order: Order):
        return self.engine.inventory.face[order.items[0].product_id]

    def _closest(self, order: Order, robots: list[Robot], k: int = CANDIDATES) -> list[Robot]:
        """The k robots with the shortest legal route to the order's first rack."""
        field = self.engine.distances.field(self._first_stop(order))
        first = self._first_stop(order)
        return sorted(
            robots, key=lambda r: field.get(r.position, 10_000 + manhattan(r.position, first))
        )[:k]


class RandomAssignment(AssignmentStrategy):
    name = "random"

    def __init__(self, engine: SimulationEngine) -> None:
        super().__init__(engine)
        self.rng = random.Random(f"{engine.seed}:assignment")  # never disturbs the engine's RNG

    def assign(self, orders, robots):
        free, pairs = list(robots), []
        for order in orders:
            if not free:
                break
            robot = free.pop(self.rng.randrange(len(free)))
            pairs.append((order, robot))
        return pairs


class EtaAssignment(AssignmentStrategy):
    name = "eta"

    def __init__(self, engine: SimulationEngine, estimator: EtaEstimator | None = None) -> None:
        super().__init__(engine)
        self.estimator = estimator or EtaEstimator(engine)

    def assign(self, orders, robots):
        free, pairs = list(robots), []
        for order in orders:
            if not free:
                break
            candidates = self._closest(order, free)
            predicted = self.estimator.predict(order, candidates)
            robot = candidates[int(np.argmin(predicted))]
            free.remove(robot)
            pairs.append((order, robot))
        return pairs


class GlobalAssignment(AssignmentStrategy):
    name = "global"

    def __init__(self, engine: SimulationEngine, estimator: EtaEstimator | None = None) -> None:
        super().__init__(engine)
        self.estimator = estimator or EtaEstimator(engine)

    def assign(self, orders, robots):
        free, pairs = list(robots), []
        for priority in ("HIGH", "MEDIUM", "LOW"):  # urgent orders get first choice of robots
            batch = [o for o in orders if o.priority.value == priority][:GLOBAL_BATCH]
            if not batch or not free:
                continue
            cost = np.full((len(batch), len(free)), UNASSIGNABLE)
            index = {r.robot_id: j for j, r in enumerate(free)}
            for i, order in enumerate(batch):
                candidates = self._closest(order, free)
                for robot, ticks in zip(
                    candidates, self.estimator.predict(order, candidates), strict=True
                ):
                    cost[i, index[robot.robot_id]] = ticks
            rows, cols = linear_sum_assignment(cost)
            used = set()
            for i, j in zip(rows, cols, strict=True):
                if cost[i, j] < UNASSIGNABLE:
                    pairs.append((batch[i], free[j]))
                    used.add(j)
            free = [r for j, r in enumerate(free) if j not in used]
        return pairs


def make_assignment(name: str, engine: SimulationEngine) -> AssignmentStrategy | None:
    """None = the dispatcher's built-in nearest-robot baseline."""
    if name == "nearest":
        return None
    strategies = {"random": RandomAssignment, "eta": EtaAssignment, "global": GlobalAssignment}
    if name not in strategies:
        raise ValueError(
            f"unknown assignment {name!r}; choose nearest or one of {list(strategies)}"
        )
    return strategies[name](engine)

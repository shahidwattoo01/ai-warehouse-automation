"""The single definition of the order features used by the ETA and late-risk models.

The models were trained on dataset v3 (scripts/generate_data.py + simulation/environment/
recorder.py). At run time two places build the same features:

    live predictions   after an order is assigned, from the robot's task metrics
    optimisation       before assigning, for every candidate robot (ai/optimization/assignment.py)

Both call `order_features`, so a model always sees exactly the encoding it was trained on.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from simulation.environment.calendar import calendar_features, date_of_day

if TYPE_CHECKING:
    from simulation.environment.engine import SimulationEngine
    from simulation.warehouse.entities import Order

# Robot/situation values known at assignment (the keys of controller Task.metrics).
METRIC_KEYS = (
    "path_distance",
    "est_distance",
    "battery_start",
    "temperature_start",
    "robot_speed",
    "zone_congestion",
    "fleet_busy",
    "pending_orders",
    "closures_active",
    "floor_hazards_active",
)


def calendar_of_tick(engine: SimulationEngine, tick: int) -> dict:
    """Calendar features of the simulated day that `tick` falls in (day 1 = 2026-09-07)."""
    ticks_per_hour = engine.config.get("ticks_per_hour", 600)
    return calendar_features(date_of_day(tick // (24 * ticks_per_hour) + 1))


def order_features(engine: SimulationEngine, order: Order, metrics: dict) -> dict:
    """Model input row for `order` given the assignment metrics (see METRIC_KEYS, plus
    `assigned_at` and `assigned_hour`)."""
    catalog = engine.inventory.catalog
    lines = [(catalog[i.product_id], i.quantity) for i in order.items]
    heaviest = max(lines, key=lambda pq: pq[0].weight_kg * pq[1])[0]
    cal = calendar_of_tick(engine, metrics["assigned_at"])
    hour = metrics["assigned_hour"]
    return {
        **{k: metrics[k] for k in METRIC_KEYS},
        "queue_ticks": metrics["assigned_at"] - order.order_time,
        "n_items": len(order.items),
        "n_units": sum(i.quantity for i in order.items),
        "total_weight_kg": round(sum(p.weight_kg * q for p, q in lines), 2),
        "hour_sin": math.sin(2 * math.pi * hour / 24),
        "hour_cos": math.cos(2 * math.pi * hour / 24),
        "day_of_week": cal["day_of_week"],
        "is_weekend": int(cal["is_weekend"]),
        "is_promo_day": int(cal["is_promo_day"]),
        "priority": order.priority.value,
        "main_category": heaviest.category,
    }

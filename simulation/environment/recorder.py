"""Turn one simulation run into training-ready tables (TR-SIM-10, Layer 1 data engineering).

The recorder subscribes to the engine's event bus and samples robot telemetry after each tick:

    robot_status     per-robot telemetry every `status_every` ticks (position, battery, motor
                     temperature, ...) with ground-truth fault labels
    events           every simulator event (moves without details, others with a JSON payload)
    orders           every order created, with what was ordered and its outcome
    tasks            one row per delivered order: features known at assignment + actual
                     duration and lateness (ETA / late-risk models)
    demand_hourly    orders and order lines per simulated hour, by priority, product category
                     and storage zone (demand forecasting)
    anomaly_windows  per-robot sliding-window features + fault label (anomaly detection)
    hazards          aisle closures and floor hazards with their start and end ticks

`calendar` (date, weekday, season, ...) is copied onto orders, tasks and demand rows, so runs
generated as consecutive days form one continuous time series.
"""

from __future__ import annotations

import json
import random
import re
from typing import TYPE_CHECKING

from simulation.environment.congestion import zone_of
from simulation.events.events import Event, EventType
from simulation.inventory.catalog import CATEGORY_NAMES
from simulation.warehouse.entities import Order

if TYPE_CHECKING:
    import pandas as pd

    from simulation.environment.engine import SimulationEngine

FAULT_TYPES = [
    "none",
    "battery_spike",
    "speed_degradation",
    "stop_event",
    "route_deviation",
    "overheating",
]
TEMPERATURE_NOISE_C = 0.3  # sensor noise (std dev) on recorded motor temperatures
HAZARD_EVENTS = {
    EventType.AISLE_CLOSED,
    EventType.AISLE_OPENED,
    EventType.HAZARD_DETECTED,
    EventType.HAZARD_CLEARED,
}


def _slug(text: str) -> str:
    """'Home & Kitchen' -> 'home_kitchen' (safe column name)."""
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _ints(df: pd.DataFrame, *columns: str) -> pd.DataFrame:
    """Whole-number columns that may be empty (not yet delivered, ...) as nullable integers."""
    for col in columns:
        if col in df:
            df[col] = df[col].astype("Int64")
    return df


class Recorder:
    def __init__(
        self,
        engine: SimulationEngine,
        run_id: str,
        status_every: int = 1,
        window: int = 20,
        calendar: dict | None = None,
    ) -> None:
        self.engine = engine
        self.run_id = run_id
        self.status_every = max(1, status_every)
        self.window = window
        self.calendar = calendar or {}
        # Separate generator for sensor noise, so recording never changes the simulation itself.
        self.noise = random.Random(f"{engine.seed}-sensors")
        self.status_rows: list[dict] = []
        self.event_rows: list[dict] = []
        self.task_rows: list[dict] = []
        self.order_rows: dict[str, dict] = {}
        self.line_rows: list[dict] = []  # one per order line: when, category, zone (demand)
        self.hazard_rows: dict[str, dict] = {}
        self._prev_pos: dict[str, tuple[int, int]] = {}
        self._aisle_at = {c: a.aisle_id for a in engine.layout.aisles for c in a.cells}
        self._shelf_zone = {s.shelf_id: s.zone_id for s in engine.layout.shelves}
        engine.events.subscribe(self._on_event)

    # ----- collection ------------------------------------------------------------
    def _products(self, order: Order) -> dict:
        """What was ordered: total weight, the heaviest line's category, all categories."""
        catalog = self.engine.inventory.catalog
        lines = [(catalog[i.product_id], i.quantity) for i in order.items]
        heaviest = max(lines, key=lambda pq: pq[0].weight_kg * pq[1])[0]
        return {
            "total_weight_kg": round(sum(p.weight_kg * q for p, q in lines), 2),
            "main_category": heaviest.category,
            "categories": "|".join(sorted({p.category for p, _ in lines})),
            "zones": "|".join(sorted({self._zone_of_product(i.product_id) for i in order.items})),
        }

    def _zone_of_product(self, product_id: str) -> str:
        """Storage zone of the product's rack (its pick face may lie on a highway)."""
        return self._shelf_zone[self.engine.inventory.catalog[product_id].shelf_id]

    def _on_event(self, event: Event) -> None:
        eng = self.engine
        self.event_rows.append(
            {
                "run_id": self.run_id,
                "tick": event.tick,
                "type": event.type.value,
                "entity_id": event.entity_id,
                "is_injected_fault": event.is_injected_fault,
                "fault": event.payload.get("fault"),
                # Moves are 80 % of all events and their payload is the next cell: skip it.
                "details": None
                if event.type == EventType.ROBOT_MOVED or not event.payload
                else json.dumps(event.payload, default=str, sort_keys=True),
            }
        )
        if event.type == EventType.ORDER_CREATED:
            order = eng.orders[event.entity_id]
            self.order_rows[order.order_id] = {
                "run_id": self.run_id,
                **self.calendar,
                "order_id": order.order_id,
                "source": order.source,
                "priority": order.priority.value,
                "order_time": order.order_time,
                "sim_hour": eng.sim_hour,
                "deadline": order.deadline,
                "n_items": len(order.items),
                "n_units": sum(i.quantity for i in order.items),
                **self._products(order),
                "status": "PENDING",
                "assigned_robot": None,
                "assigned_at": None,
                "delivered_at": None,
            }
            catalog = eng.inventory.catalog
            self.line_rows += [
                {
                    "order_time": order.order_time,
                    "category": catalog[i.product_id].category,
                    "zone": self._zone_of_product(i.product_id),
                    "units": i.quantity,
                }
                for i in order.items
            ]
        elif event.type == EventType.ORDER_ASSIGNED:
            row = self.order_rows.get(event.entity_id)
            if row:
                row["assigned_robot"] = event.payload.get("robot_id")
                row["assigned_at"] = event.tick
        elif event.type == EventType.ORDER_DELIVERED:
            p = event.payload
            row = self.order_rows.get(event.entity_id)
            if row:
                row["status"] = "LATE" if p["late"] else "DELIVERED"
                row["delivered_at"] = p["delivered_at"]
            products = self._products(eng.orders[event.entity_id])
            self.task_rows.append(
                {
                    "run_id": self.run_id,
                    **self.calendar,
                    "order_id": event.entity_id,
                    **p,
                    **products,
                }
            )
        elif event.type in HAZARD_EVENTS:
            self._on_hazard(event)

    def _on_hazard(self, event: Event) -> None:
        p = event.payload
        hid = p.get("hazard_id", event.entity_id)
        if event.type in (EventType.AISLE_CLOSED, EventType.HAZARD_DETECTED):
            closure = event.type == EventType.AISLE_CLOSED
            cell = p.get("cell") or [None, None]
            self.hazard_rows[hid] = {
                "run_id": self.run_id,
                "hazard_id": hid,
                "kind": "AISLE_CLOSURE" if closure else p.get("kind"),
                "aisle_id": event.entity_id if closure else self._aisle_at.get(tuple(cell)),
                "reason": p.get("reason"),
                "x": cell[0],
                "y": cell[1],
                "start_tick": event.tick,
                "planned_end_tick": p.get("until"),
                "end_tick": None,
            }
        elif hid in self.hazard_rows:
            self.hazard_rows[hid]["end_tick"] = event.tick

    def after_tick(self) -> None:
        """Call once after every engine.tick()."""
        eng = self.engine
        t = eng.time - 1  # tick that just ran
        if t % self.status_every:
            return
        ctl = eng.controller
        for r in eng.robots.values():
            prev = self._prev_pos.get(r.robot_id, r.position)
            task = ctl.tasks.get(r.robot_id)
            started = task.metrics.get("assigned_at") if task and task.kind == "order" else None
            zone = zone_of(eng.layout.zones, r.position)
            self.status_rows.append(
                {
                    "run_id": self.run_id,
                    "tick": t,
                    "robot_id": r.robot_id,
                    "x": r.position[0],
                    "y": r.position[1],
                    "zone": zone or "FLOOR",
                    "aisle_id": self._aisle_at.get(r.position),
                    "status": r.status.value,
                    "battery": round(r.battery, 2),
                    "temperature": round(
                        r.temperature + self.noise.gauss(0.0, TEMPERATURE_NOISE_C), 1
                    ),
                    "load": r.load,
                    # Cells travelled per tick since the previous sample (not just the last
                    # tick, which would alias with faults that act on alternate ticks).
                    "moved": round(
                        (abs(prev[0] - r.position[0]) + abs(prev[1] - r.position[1]))
                        / self.status_every,
                        3,
                    ),
                    "route_len": len(r.route),
                    "task_elapsed": t - started if started is not None else 0,
                    "blocked_ticks": ctl.blocked.get(r.robot_id, 0),
                    "zone_congestion": eng.congestion.get(zone or "", 0.0),
                    "fault_label": eng.faults.label(r.robot_id) or "none",
                }
            )
            self._prev_pos[r.robot_id] = r.position

    # ----- tables ----------------------------------------------------------------
    def tables(self) -> dict[str, pd.DataFrame]:
        import pandas as pd

        status = pd.DataFrame(self.status_rows)
        orders = _ints(pd.DataFrame(list(self.order_rows.values())), "assigned_at", "delivered_at")
        hazards = _ints(
            pd.DataFrame(list(self.hazard_rows.values())),
            "x",
            "y",
            "planned_end_tick",
            "end_tick",
        )
        return {
            "robot_status": status,
            "events": pd.DataFrame(self.event_rows),
            "tasks": pd.DataFrame(self.task_rows),
            "orders": orders,
            "demand_hourly": self._demand_hourly(orders),
            "anomaly_windows": self._anomaly_windows(status),
            "hazards": hazards,
        }

    def _demand_hourly(self, orders: pd.DataFrame) -> pd.DataFrame:
        import pandas as pd

        if orders.empty:
            return pd.DataFrame()
        tph = self.engine.config.get("ticks_per_hour", 3600)
        complete = int(self.engine.time // tph)  # only complete hours
        hours = pd.RangeIndex(complete, name="hour_index")

        o = orders[orders["source"] == "GENERATOR"].assign(hour_index=orders["order_time"] // tph)
        counts = (
            o.pivot_table(
                index="hour_index", columns="priority", values="order_id", aggfunc="count"
            )
            .reindex(index=hours, columns=["HIGH", "MEDIUM", "LOW"])
            .fillna(0)
            .astype(int)
        )
        counts.columns = [f"orders_{c.lower()}" for c in counts.columns]
        counts.insert(0, "orders_total", counts.sum(axis=1))

        lines = pd.DataFrame(self.line_rows)
        lines["hour_index"] = lines["order_time"] // tph
        units = lines.groupby("hour_index")["units"].sum().reindex(hours).fillna(0).astype(int)
        by_cat = (
            lines.pivot_table(
                index="hour_index", columns="category", values="units", aggfunc="count"
            )
            .reindex(index=hours, columns=CATEGORY_NAMES)
            .fillna(0)
            .astype(int)
        )
        by_cat.columns = [f"lines_cat_{_slug(c)}" for c in by_cat.columns]
        zones = [z.zone_id for z in self.engine.layout.zones if z.zone_id.startswith("ZONE_")]
        by_zone = (
            lines.pivot_table(index="hour_index", columns="zone", values="units", aggfunc="count")
            .reindex(index=hours, columns=zones)
            .fillna(0)
            .astype(int)
        )
        by_zone.columns = [f"lines_{_slug(z)}" for z in by_zone.columns]

        out = pd.concat([counts, units.rename("units_total"), by_cat, by_zone], axis=1)
        out = out.reset_index()
        out.insert(0, "run_id", self.run_id)
        out.insert(2, "hour_of_day", out["hour_index"] % 24)
        for i, (k, v) in enumerate(self.calendar.items()):
            out.insert(1 + i, k, v)
        return out

    def _anomaly_windows(self, status: pd.DataFrame) -> pd.DataFrame:
        import pandas as pd

        if status.empty:
            return pd.DataFrame()
        w = max(2, self.window // self.status_every)
        step = max(1, w // 2)  # 50 % overlap between consecutive windows
        out = []
        for rid, g in status.sort_values("tick").groupby("robot_id", sort=True):
            g = g.reset_index(drop=True)
            if len(g) < w:
                continue
            # Robot has somewhere to go (a fault-stopped robot counts too; status is not a feature).
            busy = (
                g["status"].isin(["MOVING", "DELIVERING", "FAULT"]) & (g["route_len"] > 0)
            ).astype(float)
            moved = g["moved"].astype(float)
            busy_n = busy.rolling(w).sum()
            diff_batt = g["battery"].diff()
            temp = g["temperature"].astype(float)
            code = g["fault_label"].map({t: i for i, t in enumerate(FAULT_TYPES)}).fillna(0)
            f = pd.DataFrame(
                {
                    "run_id": self.run_id,
                    "robot_id": rid,
                    "tick_start": g["tick"].shift(w - 1),
                    "tick_end": g["tick"],
                    "move_rate": moved.rolling(w).mean(),
                    "move_rate_when_busy": (
                        (moved * busy).rolling(w).sum() / busy_n.where(busy_n > 0)
                    ).fillna(0.0),
                    "stop_count": ((moved == 0) & (busy > 0)).astype(int).rolling(w).sum(),
                    "battery_start": g["battery"].shift(w - 1),
                    "battery_delta": g["battery"] - g["battery"].shift(w - 1),
                    "battery_min_step": diff_batt.rolling(w - 1).min(),
                    "temperature_mean": temp.rolling(w).mean().round(2),
                    "temperature_max": temp.rolling(w).max(),
                    "temperature_delta": (temp - temp.shift(w - 1)).round(2),
                    "blocked_max": g["blocked_ticks"].rolling(w).max(),
                    "route_len_mean": g["route_len"].rolling(w).mean(),
                    "route_len_growth": g["route_len"].diff().clip(lower=0).rolling(w - 1).sum(),
                    "task_elapsed_max": g["task_elapsed"].rolling(w).max(),
                    "congestion_mean": g["zone_congestion"].rolling(w).mean(),
                    "fault_code": code.rolling(w).max(),
                }
            )
            out.append(f.iloc[w - 1 :: step])
        if not out:
            return pd.DataFrame()
        df = pd.concat(out, ignore_index=True)
        for col in ("tick_start", "stop_count", "blocked_max", "task_elapsed_max"):
            df[col] = df[col].astype(int)
        df["is_anomaly"] = (df["fault_code"] > 0).astype(int)
        df["fault_type"] = df.pop("fault_code").astype(int).map(dict(enumerate(FAULT_TYPES)))
        return df

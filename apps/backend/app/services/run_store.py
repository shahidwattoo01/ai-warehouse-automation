"""Persist the interactive simulation to PostgreSQL (TR-SIM-10, Backend Schema §4-7).

Per run: simulation_runs, orders, order_items, robot_tasks, robot_status (sampled), robot_events
and inventory levels. Rows are collected on the event loop after each tick (cheap, reads the
engine) and written in batches on a worker thread, so the simulation never waits on the database.
ROBOT_MOVED events are not stored (about 80 per second); positions are in robot_status samples.
If the database fails, persistence switches itself off and the simulator keeps running.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import dataclass, field

from sqlalchemy import Engine, create_engine, text

from app.database.reference import seed_reference
from simulation.environment.engine import SimulationEngine
from simulation.events.events import Event, EventType

log = logging.getLogger(__name__)

STATUS_EVERY = 10  # robot_status sample interval in ticks
SKIP_EVENTS = {EventType.ROBOT_MOVED}

# ----- SQL (named parameters; enum and JSON values are cast explicitly) --------------------
# While a run is recorded, metrics holds {"heartbeat": <time>}, refreshed every flush (paused or
# not); end_run replaces it with the final KPIs. A run whose heartbeat has been silent this long
# was left open by a crash or a killed server; a run still being recorded is never touched.
ABANDONED_AFTER = "60 seconds"

SQL_HEARTBEAT = text("""
UPDATE simulation_runs SET metrics = jsonb_build_object('heartbeat', now())
WHERE run_id = :run_id AND ended_at IS NULL""")

SQL_CLOSE_ABANDONED_RUNS = text(f"""
UPDATE simulation_runs r SET
  ended_at = now(),
  total_ticks = (SELECT max(s.tick) + 1 FROM robot_status s WHERE s.run_id = r.run_id),
  metrics = jsonb_build_object('closed_by', 'startup',
                               'note', 'server stopped without a clean shutdown')
WHERE r.ended_at IS NULL AND r.mode = 'INTERACTIVE'
  AND COALESCE((r.metrics->>'heartbeat')::timestamptz, r.started_at)
      < now() - interval '{ABANDONED_AFTER}'""")

SQL_UPSERT_ORDERS = text("""
INSERT INTO orders (run_id, order_id, priority, order_tick, deadline_tick, status,
                    packing_station_id, delivered_tick)
VALUES (:run_id, :order_id, CAST(:priority AS priority_t), :order_tick, :deadline_tick,
        CAST(:status AS order_status_t), :station, :delivered)
ON CONFLICT (run_id, order_id) DO UPDATE SET
  status = EXCLUDED.status,
  packing_station_id = EXCLUDED.packing_station_id,
  delivered_tick = EXCLUDED.delivered_tick""")

SQL_INSERT_ITEMS = text("""
INSERT INTO order_items (run_id, order_id, product_id, quantity)
VALUES (:run_id, :order_id, :product_id, :quantity)
ON CONFLICT DO NOTHING""")

SQL_INSERT_TASKS = text("""
INSERT INTO robot_tasks (task_id, run_id, robot_id, order_id, status, assigned_tick,
                         assignment_strategy, planner, planned_distance, start_battery,
                         start_congestion, items_count)
VALUES (CAST(:task_id AS uuid), :run_id, :robot_id, :order_id, 'ASSIGNED', :tick,
        :strategy, :planner, :distance, :battery, :congestion, :items)""")

SQL_COMPLETE_TASKS = text("""
UPDATE robot_tasks SET status = 'COMPLETED', completed_tick = :tick, actual_distance = :moves
WHERE task_id = CAST(:task_id AS uuid)""")

SQL_INSERT_STATUS = text("""
INSERT INTO robot_status (run_id, tick, robot_id, x, y, battery, speed, status, load,
                          current_task_id, temperature)
VALUES (:run_id, :tick, :robot_id, :x, :y, :battery, :speed,
        CAST(:status AS robot_status_t), :load, CAST(:task_id AS uuid), :temperature)
ON CONFLICT DO NOTHING""")

SQL_INSERT_EVENTS = text("""
INSERT INTO robot_events (run_id, tick, type, robot_id, order_id, is_injected_fault, payload)
VALUES (:run_id, :tick, CAST(:type AS event_type_t), :robot_id, :order_id, :fault,
        CAST(:payload AS jsonb))""")

SQL_UPSERT_MODEL = text("""
INSERT INTO model_versions (model_name, version, artifact_path, training_run_ids, metrics,
                            is_active)
VALUES (:model_name, :version, :artifact_path, '{}', CAST(:metrics AS jsonb), true)
ON CONFLICT (model_name, version) DO UPDATE
SET artifact_path = EXCLUDED.artifact_path, metrics = EXCLUDED.metrics, is_active = true
RETURNING model_version_id""")

SQL_INSERT_PREDICTIONS = text("""
INSERT INTO predictions (run_id, tick, model_version_id, target_type, target_id, input, output,
                         actual)
VALUES (:run_id, :tick, CAST(:model_version_id AS uuid), :target_type, :target_id,
        CAST(:input AS jsonb), CAST(:output AS jsonb), CAST(:actual AS jsonb))""")

SQL_INSERT_ALERTS = text("""
INSERT INTO alerts (run_id, tick, type, robot_id, order_id)
VALUES (:run_id, :tick, CAST(:type AS alert_type_t), :robot_id, :order_id)""")

SQL_UPDATE_STOCK = text("""
UPDATE inventory SET stock = :stock, updated_tick = :tick
WHERE run_id = :run_id AND product_id = :product_id""")


@dataclass
class Batch:
    orders: dict[str, dict] = field(default_factory=dict)  # latest row per order (upsert)
    items: list[dict] = field(default_factory=list)
    tasks_new: list[dict] = field(default_factory=list)
    tasks_done: list[dict] = field(default_factory=list)
    status: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    stock: dict[str, dict] = field(default_factory=dict)  # latest row per product (upsert)
    predictions: list[dict] = field(default_factory=list)  # finished model predictions
    alerts: list[dict] = field(default_factory=list)

    def empty(self) -> bool:
        return not (
            self.orders
            or self.items
            or self.tasks_new
            or self.tasks_done
            or self.status
            or self.events
            or self.stock
            or self.predictions
            or self.alerts
        )


class RunStore:
    def __init__(self, database_url: str) -> None:
        self.db: Engine = create_engine(database_url, pool_pre_ping=True)
        self.enabled = True
        self.run_id: str | None = None
        self._batch = Batch()
        self._known_orders: set[str] = set()
        self._task_ids: dict[str, str] = {}  # order_id -> robot_tasks.task_id
        self._lock = threading.Lock()  # one writer at a time
        self._model_ids: dict[str, str] = {}  # model name -> model_versions.model_version_id

    # ----- run lifecycle -----------------------------------------------------------
    def start_run(self, engine: SimulationEngine, models: list[dict] | None = None) -> None:
        """Seed reference data, register the live models, open a simulation_runs row and
        snapshot the inventory."""
        if not self.enabled:
            return
        try:
            with self._lock, self.db.begin() as conn:
                closed = conn.execute(SQL_CLOSE_ABANDONED_RUNS).rowcount
                if closed:
                    log.warning("Closed %d run(s) left open by an unclean shutdown", closed)
                seed_reference(conn, engine)
                self._model_ids = {
                    m["model_name"]: str(
                        conn.execute(
                            SQL_UPSERT_MODEL, {**m, "metrics": json.dumps(m["metrics"])}
                        ).scalar_one()
                    )
                    for m in models or []
                }
                self.run_id = (
                    conn.execute(
                        text("""INSERT INTO simulation_runs (mode, seed, layout_name, config,
                                                             metrics)
                            VALUES ('INTERACTIVE', :seed, :layout, CAST(:config AS jsonb),
                                    jsonb_build_object('heartbeat', now()))
                            RETURNING run_id"""),
                        {
                            "seed": engine.seed,
                            "layout": engine.layout.name,
                            "config": json.dumps(engine.config),
                        },
                    )
                    .scalar_one()
                    .hex
                )
                conn.execute(
                    text("""INSERT INTO inventory (run_id, product_id, stock, updated_tick)
                            VALUES (:run_id, :product_id, :stock, 0)"""),
                    [
                        {"run_id": self.run_id, "product_id": p, "stock": s}
                        for p, s in engine.inventory.stock.items()
                    ],
                )
            self._batch, self._known_orders, self._task_ids = Batch(), set(), {}
            log.info("Recording simulation run %s to the database", self.run_id)
        except Exception as exc:  # database down, not migrated, or seeded with another layout
            self._disable(exc)

    def end_run(self, engine: SimulationEngine) -> None:
        if not (self.enabled and self.run_id):
            return
        self.flush()
        try:
            with self._lock, self.db.begin() as conn:
                conn.execute(
                    text("""UPDATE simulation_runs SET ended_at = now(), total_ticks = :ticks,
                            metrics = CAST(:metrics AS jsonb) WHERE run_id = :run_id"""),
                    {
                        "ticks": engine.time,
                        "metrics": json.dumps(engine.kpis.snapshot()),
                        "run_id": self.run_id,
                    },
                )
        except Exception as exc:
            self._disable(exc)
        self.run_id = None

    # ----- per tick (event loop) ------------------------------------------------------
    def collect(self, engine: SimulationEngine, events: list[Event]) -> None:
        """Turn this tick's events and state into rows. Reads the engine; no I/O."""
        if not (self.enabled and self.run_id):
            return
        run, tick, b = self.run_id, engine.time - 1, self._batch
        for e in events:
            if e.type in SKIP_EVENTS:
                continue
            order_id = self._order_of(engine, e)
            if e.type == EventType.ORDER_CREATED and order_id:
                order = engine.orders[order_id]
                self._known_orders.add(order_id)
                b.items += [
                    {
                        "run_id": run,
                        "order_id": order_id,
                        "product_id": i.product_id,
                        "quantity": i.quantity,
                    }
                    for i in order.items
                ]
            elif e.type == EventType.ORDER_ASSIGNED and order_id:
                self._task_ids[order_id] = task_id = uuid.uuid4().hex
                b.tasks_new.append(self._task_row(engine, order_id, task_id, tick))
            elif e.type == EventType.ORDER_DELIVERED and order_id in self._task_ids:
                b.tasks_done.append(
                    {
                        "task_id": self._task_ids.pop(order_id),
                        "tick": tick,
                        "moves": e.payload["moves"],
                    }
                )
            elif e.type in (EventType.ITEM_PICKED, EventType.INVENTORY_RESTOCKED):
                pid = e.payload.get("product_id") or e.entity_id
                b.stock[pid] = {
                    "run_id": run,
                    "product_id": pid,
                    "stock": engine.inventory.stock[pid],
                    "tick": tick,
                }
            if order_id in engine.orders:
                b.orders[order_id] = self._order_row(engine, order_id)
            b.events.append(
                {
                    "run_id": run,
                    "tick": e.tick,
                    "type": e.type.value,
                    "robot_id": e.entity_id if e.entity_id in engine.robots else None,
                    "order_id": order_id if order_id in self._known_orders else None,
                    "fault": e.is_injected_fault,
                    "payload": json.dumps(e.payload, default=str),
                }
            )
        if tick % STATUS_EVERY == 0:
            for r in engine.robots.values():
                moves = engine.controller.recent_moves.get(r.robot_id) or [0]
                b.status.append(
                    {
                        "run_id": run,
                        "tick": tick,
                        "robot_id": r.robot_id,
                        "x": r.position[0],
                        "y": r.position[1],
                        "battery": round(r.battery, 2),
                        "speed": round(sum(moves) / len(moves), 2),
                        "status": r.status.value,
                        "load": r.load,
                        "task_id": self._task_ids.get(r.current_task or ""),
                        "temperature": round(r.temperature, 2),
                    }
                )

    @staticmethod
    def _order_of(engine: SimulationEngine, e: Event) -> str | None:
        if e.entity_id and e.entity_id.startswith("O"):
            return e.entity_id
        robot = engine.robots.get(e.entity_id or "")
        return robot.current_task if robot else None

    def _order_row(self, engine: SimulationEngine, order_id: str) -> dict:
        o = engine.orders[order_id]
        return {
            "run_id": self.run_id,
            "order_id": o.order_id,
            "priority": o.priority.value,
            "order_tick": o.order_time,
            "deadline_tick": o.deadline,
            "status": o.status.value,
            "station": o.destination,
            "delivered": o.delivered_at,
        }

    def _task_row(self, engine: SimulationEngine, order_id: str, task_id: str, tick: int) -> dict:
        order = engine.orders[order_id]
        task = engine.controller.tasks[order.assigned_robot]
        m = task.metrics
        return {
            "task_id": task_id,
            "run_id": self.run_id,
            "robot_id": order.assigned_robot,
            "order_id": order_id,
            "tick": tick,
            "strategy": "manual" if order.manual_assignment else "nearest",
            "planner": engine.planner.name,
            "distance": m["est_distance"],
            "battery": m["battery_start"],
            "congestion": min(m["zone_congestion"], 9.999),
            "items": len(order.items),
        }

    def add_predictions(self, records: list[dict], alerts: list[dict]) -> None:
        """Queue finished predictions (input, output, actual) and new alerts for the next write."""
        if not (self.enabled and self.run_id):
            return
        for r in records:
            model_id = self._model_ids.get(r["model"])
            if model_id:
                self._batch.predictions.append(
                    {
                        "run_id": self.run_id,
                        "tick": r["tick"],
                        "model_version_id": model_id,
                        "target_type": r["target_type"],
                        "target_id": r["target_id"],
                        "input": json.dumps(r["input"], default=float),
                        "output": json.dumps(r["output"], default=float),
                        "actual": json.dumps(r["actual"], default=float),
                    }
                )
        self._batch.alerts += [{"run_id": self.run_id, **a} for a in alerts]

    # ----- writing (worker thread) ---------------------------------------------------
    def take_batch(self) -> Batch | None:
        """Hand the collected rows to a writer; collection continues into a fresh batch."""
        if self._batch.empty():
            return None
        batch, self._batch = self._batch, Batch()
        return batch

    def flush(self) -> None:
        self.write(self.take_batch())

    def write(self, b: Batch | None) -> None:
        """Write one batch in a single transaction (parents first: rows below reference orders)
        and refresh the run's heartbeat. With no rows (e.g. paused) only the heartbeat is sent."""
        if not (self.enabled and self.run_id):
            return
        b = b or Batch()
        steps = [
            (SQL_UPSERT_ORDERS, list(b.orders.values())),
            (SQL_INSERT_ITEMS, b.items),
            (SQL_INSERT_TASKS, b.tasks_new),
            (SQL_COMPLETE_TASKS, b.tasks_done),
            (SQL_INSERT_STATUS, b.status),
            (SQL_INSERT_EVENTS, b.events),
            (SQL_UPDATE_STOCK, list(b.stock.values())),
            (SQL_INSERT_PREDICTIONS, b.predictions),
            (SQL_INSERT_ALERTS, b.alerts),
        ]
        try:
            with self._lock, self.db.begin() as conn:
                for sql, rows in steps:
                    if rows:
                        conn.execute(sql, rows)
                conn.execute(SQL_HEARTBEAT, {"run_id": self.run_id})
        except Exception as exc:
            self._disable(exc)

    def _disable(self, exc: Exception) -> None:
        self.enabled = False
        log.warning(
            "Run recording to PostgreSQL is off: %s. The simulator keeps running. Check "
            "DATABASE_URL, run `python tasks.py migrate`, and `python scripts/seed.py --reset` "
            "if the layout changed.",
            str(exc).splitlines()[0],
        )

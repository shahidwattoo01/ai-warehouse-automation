"""Live Phase 3 predictions: the trained models run against the simulator as it ticks.

    ETA         when an order is assigned: predicted ticks to delivery
    late risk   at the same moment: probability that the order misses its deadline
    demand      at the start of every simulated hour: total orders expected in that hour, and the
                breakdown per storage zone (order lines) and per priority (orders)
    anomaly     every 10 ticks per robot: is its last 20 ticks of telemetry abnormal?

Features are built exactly as in the training data (simulation/environment/recorder.py and the
notebooks), only from information available at prediction time. The simulator knows the truth
(actual delivery times, which robots have an injected fault), so every prediction is also scored
live, and each finished prediction becomes a record (input, output, actual) that the RunStore saves
to the `predictions` table, plus `alerts` for late-risk orders and abnormal robots.

Models are the files written by notebooks/01-05 in models/. A missing file disables that model.
Phase 5 networks (notebooks 07 and 08): the LSTM fault detector (anomaly_lstm_v1.pt) replaces
XGBoost when present (WAREHOUSE_ANOMALY_MODEL=xgboost keeps XGBoost). The demand network
(demand_dl_v1.pt) is used only with WAREHOUSE_DEMAND_MODEL=network: it reads the last 168 hours, and
in a short live run those are mostly planning estimates, where Gradient Boosting was better.
Used by the backend (live dashboard) and by scripts/run_experiments.py (Phase 4 optimisation).
"""

from __future__ import annotations

import json
import logging
import math
import os
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING

import joblib
import numpy as np
import pandas as pd

from ai.classical_ml.features import calendar_of_tick, order_features
from simulation.environment.congestion import zone_of
from simulation.events.events import Event, EventType
from simulation.warehouse.entities import OrderStatus

if TYPE_CHECKING:
    from simulation.environment.engine import SimulationEngine

log = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).resolve().parents[2] / "models"
MODEL_FILES = {  # key -> (model file, report file, version label), written by notebooks/01-05
    "eta": ("eta_v1.joblib", "eta_v1_report.json", "v1"),
    "late": ("late_risk_v1.joblib", "late_risk_v1_report.json", "v1"),
    "demand": ("demand_v1.joblib", "demand_v1_report.json", "v1"),
    "demand_breakdown": ("demand_breakdown_v1.joblib", "demand_breakdown_v1_report.json", "v1"),
    "anomaly": ("anomaly_v1.joblib", "anomaly_v1_report.json", "v1"),
}
STATUS_EVERY = 2  # telemetry sample interval, as in the dataset
WINDOW = 10  # samples per anomaly window (20 ticks)
WINDOW_STEP = 5  # evaluate every 5 samples (10 ticks), as the dataset's 50 % overlap
BUSY_STATUSES = {"MOVING", "DELIVERING", "FAULT"}
HISTORY_HOURS = 12
SCORE_MEMORY = 300  # recent outcomes used for the live accuracy figures
ZONE_TARGETS = {
    "lines_zone_a": "ZONE_A",
    "lines_zone_b": "ZONE_B",
    "lines_zone_c": "ZONE_C",
    "lines_zone_d": "ZONE_D",
}
PRIORITY_TARGETS = {"orders_high": "HIGH", "orders_medium": "MEDIUM", "orders_low": "LOW"}
# Phase 5 networks: key -> (file, report, version label, env var, default mode, mode that uses it)
DEEP_FILES = {
    "anomaly": ("anomaly_lstm_v1.pt", "anomaly_dl_v1_report.json", "v2",
                "WAREHOUSE_ANOMALY_MODEL", "lstm", "lstm"),
    "demand": ("demand_dl_v1.pt", "demand_dl_v1_report.json", "v2",
               "WAREHOUSE_DEMAND_MODEL", "gb", "network"),
}  # fmt: skip


class Predictor:
    def __init__(self, models_dir: Path = MODELS_DIR) -> None:
        self.models: dict[str, object] = {}
        self.deep: dict[str, object] = {}  # Phase 5 networks that replace a Phase 3 model
        self.reports: dict[str, dict] = {}
        self.versions: list[dict] = []  # what the RunStore registers in model_versions
        for key, (model_file, report_file, version) in MODEL_FILES.items():
            path = models_dir / model_file
            if not path.exists():
                log.warning("Model %s not found; %s predictions are off", model_file, key)
                continue
            self.models[key] = joblib.load(path)
            report = models_dir / report_file
            self.reports[key] = json.loads(report.read_text()) if report.exists() else {}
            self.versions.append(
                {
                    "model_name": key,
                    "version": version,
                    "artifact_path": f"models/{model_file}",
                    "metrics": self._test_metrics(key),
                }
            )
        for key, (net_file, report_file, version, env, default, on) in DEEP_FILES.items():
            path = models_dir / net_file
            if not path.exists() or os.environ.get(env, default).lower() != on:
                continue
            try:
                from ai.deep_learning.live import LiveDemandNet, LiveFaultLSTM

                cls = LiveFaultLSTM if key == "anomaly" else LiveDemandNet
                self.deep[key] = cls(path, models_dir / report_file)
            except Exception:  # PyTorch missing or an incompatible file: keep the Phase 3 model
                log.exception("Could not load %s; using the Phase 3 %s model", net_file, key)
                continue
            self.versions = [v for v in self.versions if v["model_name"] != key]
            self.versions.append(
                {
                    "model_name": key,
                    "version": version,
                    "artifact_path": f"models/{net_file}",
                    "metrics": self._test_metrics(key),
                }
            )
        self.engine: SimulationEngine | None = None

    def use_version(self, key: str, obj, version: str, artifact_path: str, metrics: dict) -> dict:
        """Replace the live `eta` or `late` model by another version (MLOps promotion or
        rollback). Call between ticks; orders already predicted keep their prediction."""
        self.models[key] = obj
        entry = {"model_name": key, "version": version, "artifact_path": artifact_path,
                 "metrics": metrics}  # fmt: skip
        self.versions = [v for v in self.versions if v["model_name"] != key] + [entry]
        return entry

    def _has(self, key: str) -> bool:
        return key in self.models or key in self.deep

    def _test_metrics(self, key: str) -> dict:
        if key == "anomaly" and key in self.deep:
            return {"algorithm": self.deep[key].algorithm, "test": self.deep[key].test}
        if key == "demand" and key in self.deep:
            return {"algorithm": self.deep[key].algorithm, "test_mae": self.deep[key].test_mae}
        r = self.reports.get(key, {})
        if key == "eta":
            return {"algorithm": r.get("algorithm"), "test": r.get("test")}
        if key == "late":
            return {
                "algorithm": r.get("algorithm"),
                "threshold": r.get("threshold"),
                "test": r.get("test"),
            }
        if key == "demand":
            return {"algorithm": r.get("algorithm"), "test_mae": r.get("test_mae")}
        if key == "anomaly":
            return {
                "algorithm": r.get("algorithm"),
                "test": r.get("test", {}).get(r.get("algorithm")),
            }
        return {"test": r.get("test")}

    def _algorithm(self, key: str) -> str | None:
        if key in self.deep:
            return self.deep[key].algorithm
        if key == "demand_breakdown":  # one model per target, possibly different algorithms
            chosen = sorted({spec["algorithm"] for spec in self.models[key]["targets"].values()})
            return "per target: " + ", ".join(chosen)
        return self.reports.get(key, {}).get("algorithm")

    # ----- lifecycle -------------------------------------------------------------------
    def attach(self, engine: SimulationEngine) -> None:
        """Start predicting for a (new) engine."""
        self.engine = engine
        self.tph = engine.config.get("ticks_per_hour", 600)
        self.orders: dict[str, dict] = {}  # order_id -> prediction (until delivered)
        # One reading more than a window: the networks need the step into the first reading.
        self.samples: dict[str, deque] = {r: deque(maxlen=WINDOW + 1) for r in engine.robots}
        self.prev_pos: dict[str, tuple[int, int]] = {}
        self.robot_health: dict[str, dict] = {}
        # Per simulated hour: customer orders, order lines per zone, orders per priority.
        self.counts: dict[str, dict[int, int]] = {
            "orders_total": {},
            **{t: {} for t in ZONE_TARGETS},
            **{t: {} for t in PRIORITY_TARGETS},
        }
        self.forecasts: dict[str, dict[int, float]] = {t: {} for t in self.counts}
        self.forecast_inputs: dict[str, dict[int, dict]] = {t: {} for t in self.counts}
        self.eta_errors: deque[float] = deque(maxlen=SCORE_MEMORY)
        self.late_outcomes: deque[tuple[bool, bool]] = deque(maxlen=SCORE_MEMORY)
        self.anomaly_outcomes: deque[tuple[bool, bool]] = deque(maxlen=SCORE_MEMORY * 10)
        self.records: list[dict] = []  # finished predictions for the database
        self.alerts: list[dict] = []  # new alerts for the database
        self._shelf_zone = {s.shelf_id: s.zone_id for s in engine.layout.shelves}
        engine.events.subscribe(self._on_event, external=True)
        self._forecast_hour(0)

    def drain(self) -> tuple[list[dict], list[dict]]:
        """Hand finished prediction records and new alerts to the RunStore."""
        records, alerts, self.records, self.alerts = self.records, self.alerts, [], []
        return records, alerts

    # ----- events: orders --------------------------------------------------------------
    def _count(self, target: str, hour: int, n: int = 1) -> None:
        self.counts[target][hour] = self.counts[target].get(hour, 0) + n

    def _on_event(self, event: Event) -> None:
        eng = self.engine
        if event.type == EventType.ORDER_CREATED:
            order = eng.orders.get(event.entity_id)
            if order and order.source == "GENERATOR":
                hour = event.tick // self.tph
                self._count("orders_total", hour)
                self._count(f"orders_{order.priority.value.lower()}", hour)
                for item in order.items:
                    zone = self._shelf_zone[eng.inventory.catalog[item.product_id].shelf_id]
                    self._count(f"lines_{zone.lower()}", hour)
        elif event.type == EventType.ORDER_ASSIGNED:
            self._predict_order(event.entity_id, event.payload.get("robot_id"))
        elif event.type == EventType.ORDER_DELIVERED:
            self._close_order(event)

    def _close_order(self, event: Event) -> None:
        pred = self.orders.pop(event.entity_id, None)
        if not pred:
            return
        p = event.payload
        actual_ticks, late = p["duration_ticks"], bool(p["late"])
        if "eta_ticks" in pred:
            self.eta_errors.append(abs(actual_ticks - pred["eta_ticks"]))
            self._record(
                "eta",
                pred["assigned_at"],
                "ORDER",
                event.entity_id,
                pred["input"],
                {"eta_ticks": pred["eta_ticks"]},
                {"duration_ticks": actual_ticks},
            )
        if "late_risk" in pred:
            self.late_outcomes.append((pred["late_flag"], late))
            self._record(
                "late",
                pred["assigned_at"],
                "ORDER",
                event.entity_id,
                pred["input"],
                {"late_risk": pred["late_risk"], "flag": pred["late_flag"]},
                {"late": late},
            )

    def _record(
        self,
        model: str,
        tick: int,
        target_type: str,
        target_id: str | None,
        inputs: dict,
        output: dict,
        actual: dict | None,
    ) -> None:
        self.records.append(
            {
                "model": model,
                "tick": int(tick),
                "target_type": target_type,
                "target_id": target_id,
                "input": inputs,
                "output": output,
                "actual": actual,
            }
        )

    def _calendar(self, tick: int) -> dict:
        return calendar_of_tick(self.engine, tick)

    def _order_features(self, order_id: str, robot_id: str) -> dict | None:
        task = self.engine.controller.tasks.get(robot_id)
        order = self.engine.orders.get(order_id)
        if not task or not order or task.kind != "order":
            return None
        return order_features(self.engine, order, task.metrics)

    def _predict_order(self, order_id: str, robot_id: str | None) -> None:
        if not robot_id or not ({"eta", "late"} & self.models.keys()):
            return
        row = self._order_features(order_id, robot_id)
        if row is None:
            return
        X = pd.DataFrame([row])
        assigned_at = self.engine.controller.tasks[robot_id].metrics["assigned_at"]
        pred: dict = {"assigned_at": assigned_at, "robot_id": robot_id, "input": row}
        if "eta" in self.models:
            model = self.models["eta"]
            eta = float(model.predict(X[list(model.feature_names_in_)])[0])
            pred["eta_ticks"] = max(1, round(eta))
            pred["eta_tick"] = assigned_at + pred["eta_ticks"]
        if "late" in self.models:
            bundle = self.models["late"]
            pipe = bundle["pipeline"]
            risk = float(pipe.predict_proba(X[list(pipe.feature_names_in_)])[0, 1])
            pred["late_risk"] = round(risk, 3)
            pred["late_flag"] = risk >= bundle["threshold"]
            if pred["late_flag"]:
                self.alerts.append(
                    {
                        "tick": assigned_at,
                        "type": "LATE_ORDER",
                        "robot_id": robot_id,
                        "order_id": order_id,
                    }
                )
        self.orders[order_id] = pred

    # ----- per tick: telemetry for anomaly detection, hourly demand --------------------
    def after_tick(self) -> None:
        eng = self.engine
        t = eng.time - 1  # the tick that just ran
        if eng.time % self.tph == 0:
            hour = eng.time // self.tph
            self._close_hour(hour - 1)
            self._forecast_hour(hour)
        if t % STATUS_EVERY:
            return
        ctl = eng.controller
        for r in eng.robots.values():
            prev = self.prev_pos.get(r.robot_id, r.position)
            task = ctl.tasks.get(r.robot_id)
            started = task.metrics.get("assigned_at") if task and task.kind == "order" else None
            zone = zone_of(eng.layout.zones, r.position)
            self.samples[r.robot_id].append(
                (
                    (abs(prev[0] - r.position[0]) + abs(prev[1] - r.position[1])) / STATUS_EVERY,
                    r.status.value,
                    len(r.route),
                    r.battery,
                    r.temperature,
                    ctl.blocked.get(r.robot_id, 0),
                    t - started if started is not None else 0,
                    eng.congestion.get(zone or "", 0.0),
                    eng.faults.label(r.robot_id) is not None,
                    r.load,
                )
            )
            self.prev_pos[r.robot_id] = r.position
        if self._has("anomaly") and (t // STATUS_EVERY) % WINDOW_STEP == 0:
            self._score_robots(t)

    @staticmethod
    def _window_features(samples: list[tuple]) -> dict:
        """The anomaly_windows features of one 20-tick window (see recorder._anomaly_windows)."""
        moved = np.array([s[0] for s in samples], dtype=float)
        busy = np.array([s[1] in BUSY_STATUSES and s[2] > 0 for s in samples], dtype=float)
        route = np.array([s[2] for s in samples], dtype=float)
        batt = np.array([s[3] for s in samples], dtype=float)
        temp = np.array([s[4] for s in samples], dtype=float)
        busy_n = busy.sum()
        return {
            "move_rate": float(moved.mean()),
            "move_rate_when_busy": float((moved * busy).sum() / busy_n) if busy_n else 0.0,
            "stop_count": int(((moved == 0) & (busy > 0)).sum()),
            "battery_delta": float(batt[-1] - batt[0]),
            "battery_min_step": float(np.diff(batt).min()),
            "temperature_mean": float(temp.mean()),
            "temperature_max": float(temp.max()),
            "temperature_delta": float(temp[-1] - temp[0]),
            "blocked_max": int(max(s[5] for s in samples)),
            "route_len_mean": float(route.mean()),
            "route_len_growth": float(np.clip(np.diff(route), 0, None).sum()),
            "task_elapsed_max": int(max(s[6] for s in samples)),
            "congestion_mean": float(np.mean([s[7] for s in samples])),
        }

    @staticmethod
    def _reason(f: dict) -> str:
        """A readable hint for the operator (the model itself only says normal / abnormal)."""
        if f["temperature_max"] > 55:
            return f"hot motor ({f['temperature_max']:.0f} °C)"
        if f["battery_min_step"] < -5:
            return f"battery drop ({f['battery_min_step']:.0f} %)"
        if f["stop_count"] >= 6:
            return "stopped while on a task"
        if f["route_len_growth"] > 2:
            return "left its route"
        if f["move_rate_when_busy"] < 0.7:
            return "moving slowly"
        return "unusual pattern"

    def _score_robots(self, tick: int) -> None:
        ids = [rid for rid, s in self.samples.items() if len(s) >= WINDOW]
        if not ids:
            return
        readings = {rid: list(self.samples[rid]) for rid in ids}
        windows = {rid: r[-WINDOW:] for rid, r in readings.items()}
        feats = [self._window_features(windows[rid]) for rid in ids]  # input or explanation
        if "anomaly" in self.deep:  # Phase 5 LSTM on the raw readings
            from ai.deep_learning.live import fault_channels

            net = self.deep["anomaly"]
            before = {
                rid: r[-WINDOW - 1] if len(r) > WINDOW else None for rid, r in readings.items()
            }
            seqs = np.stack([fault_channels(windows[rid], before[rid]) for rid in ids])
            scores, threshold = net.scores(seqs), net.threshold
        else:  # Phase 3 XGBoost on the 13 window features
            bundle = self.models["anomaly"]
            scores = bundle["model"].predict_proba(pd.DataFrame(feats)[bundle["features"]])[:, 1]
            threshold = bundle["threshold"]
        for rid, f, score in zip(ids, feats, scores, strict=True):
            flag = bool(score >= threshold)
            truth = any(s[8] for s in windows[rid])
            self.anomaly_outcomes.append((flag, truth))
            was = self.robot_health.get(rid, {})
            newly = flag and not was.get("abnormal")
            self.robot_health[rid] = {
                "score": round(float(score), 3),
                "abnormal": flag,
                "reason": self._reason(f) if flag else None,
                "since": tick if newly or not flag else was.get("since", tick),
            }
            if newly:  # one record and one alert when a robot turns abnormal
                self._record(
                    "anomaly",
                    tick,
                    "ROBOT",
                    rid,
                    f,
                    {"score": round(float(score), 3), "reason": self._reason(f)},
                    {"fault_active": truth},
                )
                self.alerts.append(
                    {"tick": tick, "type": "ANOMALY", "robot_id": rid, "order_id": None}
                )

    # ----- demand ----------------------------------------------------------------------
    def _expected(self, hour: int) -> float:
        """The planner's prior for an hour's customer orders (used before history exists)."""
        gen = self.engine.config["orders"]
        profile = gen.get("hourly_profile") or [1.0]
        return (
            gen.get("arrival_prob_per_tick", 0.0) * profile[hour % 24] / np.mean(profile) * self.tph
        )

    def _past(self, target: str, hour: int, now: int) -> float:
        """Observed count for a past hour, or the prior scaled by the target's usual share."""
        if 0 <= hour < now:
            return float(self.counts[target].get(hour, 0))
        share = 1.0
        if target != "orders_total" and "demand_breakdown" in self.models:
            share = self.models["demand_breakdown"]["share_of_total"].get(target, 1.0)
        return self._expected(hour) * share

    def _calendar_row(self, hour: int) -> dict:
        cal = self._calendar(hour * self.tph)
        return {
            "hour_sin": math.sin(2 * math.pi * (hour % 24) / 24),
            "hour_cos": math.cos(2 * math.pi * (hour % 24) / 24),
            "day_of_week": cal["day_of_week"],
            "is_weekend": int(cal["is_weekend"]),
            "month": cal["month"],
            "is_promo_day": int(cal["is_promo_day"]),
        }

    def _calendar_flags(self, hour: int) -> dict:
        cal = self._calendar(hour * self.tph)
        return {"is_weekend": float(cal["is_weekend"]), "is_promo_day": float(cal["is_promo_day"])}

    def _forecast_hour(self, hour: int) -> None:
        """Forecast simulated hour `hour` from earlier hours only (total + breakdown)."""
        cal = self._calendar_row(hour)
        if self._has("demand"):
            total = "orders_total"
            row = {
                **cal,
                "lag_1h_orders": self._past(total, hour - 1, hour),
                "lag_2h_orders": self._past(total, hour - 2, hour),
                "lag_24h_orders": self._past(total, hour - 24, hour),
                "lag_168h_orders": self._past(total, hour - 168, hour),
                "rolling_24h_mean_orders": float(
                    np.mean([self._past(total, hour - k, hour) for k in range(1, 25)])
                ),
            }
            if "demand" in self.deep:  # Phase 5 network on the last week, hour by hour
                net = self.deep["demand"]
                past = range(hour - net.history, hour)
                calendars = [{"hour": h % 24, **self._calendar_flags(h)} for h in past]
                target = {"hour": hour % 24, "day_of_week": cal["day_of_week"]}
                target |= self._calendar_flags(hour)
                orders = [self._past(total, h, hour) for h in past]
                value = net.forecast(orders, calendars, target, row)
            else:
                model = self.models["demand"]
                value = float(model.predict(pd.DataFrame([row])[list(model.feature_names_in_)])[0])
            self.forecasts[total][hour] = round(max(value, 0.0), 1)
            self.forecast_inputs[total][hour] = row
        if "demand_breakdown" in self.models:
            bundle = self.models["demand_breakdown"]
            for target, spec in bundle["targets"].items():
                row = {
                    **cal,
                    "lag_1h": self._past(target, hour - 1, hour),
                    "lag_2h": self._past(target, hour - 2, hour),
                    "lag_24h": self._past(target, hour - 24, hour),
                    "lag_168h": self._past(target, hour - 168, hour),
                    "rolling_24h_mean": float(
                        np.mean([self._past(target, hour - k, hour) for k in range(1, 25)])
                    ),
                    "total_lag_1h": self._past("orders_total", hour - 1, hour),
                    "total_lag_24h": self._past("orders_total", hour - 24, hour),
                }
                value = float(spec["model"].predict(pd.DataFrame([row])[bundle["features"]])[0])
                self.forecasts[target][hour] = round(max(value, 0.0), 1)
                self.forecast_inputs[target][hour] = row

    def _close_hour(self, hour: int) -> None:
        """An hour ended: store each forecast with what really arrived."""
        for target, forecasts in self.forecasts.items():
            if hour in forecasts:
                actual = self.counts[target].get(hour, 0)
                self._record(
                    "demand_breakdown" if target != "orders_total" else "demand",
                    hour * self.tph,
                    "HOUR",
                    f"{target}:{hour}",
                    self.forecast_inputs[target][hour],
                    {"forecast": forecasts[hour]},
                    {"count": actual},
                )

    # ----- output ----------------------------------------------------------------------
    @staticmethod
    def _precision_recall(outcomes) -> dict:
        tp = sum(1 for p, t in outcomes if p and t)
        fp = sum(1 for p, t in outcomes if p and not t)
        fn = sum(1 for p, t in outcomes if t and not p)
        return {
            "precision": round(tp / (tp + fp), 3) if tp + fp else None,
            "recall": round(tp / (tp + fn), 3) if tp + fn else None,
            "n": len(outcomes),
        }

    def snapshot(self) -> dict:
        """Compact live predictions for the stream (active orders, robot health, demand)."""
        if not self.engine:
            return {}
        eng = self.engine
        hour = eng.time // self.tph
        active = {
            oid: {k: p[k] for k in ("eta_tick", "eta_ticks", "late_risk", "late_flag") if k in p}
            for oid, p in self.orders.items()
            if (o := eng.orders.get(oid))
            and o.status in (OrderStatus.ASSIGNED, OrderStatus.IN_PROGRESS)
        }
        total = "orders_total"
        history = [
            {
                "hour": h,
                "forecast": self.forecasts[total].get(h),
                "actual": self.counts[total].get(h, 0),
            }
            for h in range(max(0, hour - HISTORY_HOURS), hour)
        ]
        done = [x for x in history if x["forecast"] is not None]

        def part(targets: dict[str, str]) -> dict:
            return {
                label: {
                    "forecast": self.forecasts[t].get(hour),
                    "so_far": self.counts[t].get(hour, 0),
                }
                for t, label in targets.items()
            }

        return {
            "models": sorted(set(self.models) | set(self.deep)),
            "orders": active,
            "robots": self.robot_health,
            "demand": {
                "hour": hour,
                "forecast": self.forecasts[total].get(hour),
                "so_far": self.counts[total].get(hour, 0),
                "history": history,
                "zones": part(ZONE_TARGETS) if "demand_breakdown" in self.models else {},
                "priorities": part(PRIORITY_TARGETS) if "demand_breakdown" in self.models else {},
            },
            "live_accuracy": {
                "eta_mae": round(float(np.mean(self.eta_errors)), 1) if self.eta_errors else None,
                "eta_n": len(self.eta_errors),
                "late": self._precision_recall(self.late_outcomes),
                "demand_mae": round(
                    float(np.mean([abs(x["forecast"] - x["actual"]) for x in done])), 1
                )
                if done
                else None,
                "anomaly": self._precision_recall(self.anomaly_outcomes),
            },
            "test_scores": {
                "eta_mae": (self.reports.get("eta", {}).get("test") or {}).get("MAE"),
                "late": self.reports.get("late", {}).get("test"),
                "demand_mae": self._test_metrics("demand").get("test_mae")
                if self._has("demand")
                else None,
                "anomaly": self._test_metrics("anomaly").get("test")
                if self._has("anomaly")
                else None,
            },
            "algorithms": {
                k: self._algorithm(k) for k in sorted(set(self.models) | set(self.deep))
            },
        }

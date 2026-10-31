"""Model operations next to the live simulator (backlog PR-19; docs/mlops.md).

    finished predictions ──► drift monitors (window of recent outcomes per model)
                                 │ every check_every_ticks: PSI of inputs, live error
                                 ▼
                     OK / WARN / DRIFT ── DRIFT confirmed ──► retrain (worker thread)
                                                                 │
                     candidate + gate tests ◄────────────────────┘
                         passed ──► promoted (auto_promote) ──► the live predictor swaps
                         failed ──► rejected (production stays)

Promotions and rollbacks are applied on the event loop between ticks (the predictor is used
there); training runs in a worker thread and only reads a copy of the live outcomes.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from pathlib import Path

import joblib
import yaml

from ai.mlops.drift import DriftMonitor
from ai.mlops.registry import ROOT, Registry
from ai.mlops.retrain import retrain

log = logging.getLogger(__name__)
CONFIG = ROOT / "configs" / "mlops.yaml"
MODELS = ("eta", "late")


class MlopsService:
    def __init__(self, registry: Registry | None = None, config: Path = CONFIG) -> None:
        self.cfg = yaml.safe_load(Path(config).read_text(encoding="utf-8"))
        self.registry = registry or Registry()
        self.monitors: dict[str, DriftMonitor] = {}
        self.live: dict[str, deque] = {}
        self.predictor = None
        self.store = None
        self.job: dict | None = None  # the retraining in progress or last finished
        self._thread: threading.Thread | None = None
        self._pending: deque = deque()  # (model, version, by, event) to apply on the loop
        self._last_retrain: dict[str, int] = {}
        self.counts: dict[str, int] = {"retrains": 0, "promoted": 0, "rejected": 0}
        self.events: deque = deque(maxlen=100)  # for the screen and the event bus
        self._published = 0

    # ----- set-up ----------------------------------------------------------------------------
    def attach(self, predictor, store=None) -> None:
        """Follow a predictor (a new run): put the production versions in and watch them."""
        self.predictor, self.store = predictor, store
        for model in MODELS:
            if model not in predictor.models:
                continue
            entry = self.registry.production(model)
            if entry["version"] != "v1":  # the predictor loads v1 by itself
                self._use(model, entry)
            self.monitors[model] = DriftMonitor(
                model, self._profile(entry), self._baseline(entry), self.cfg
            )
            self.live.setdefault(model, deque(maxlen=self.cfg["retrain"]["keep_live"]))

    def _profile(self, entry: dict) -> dict:
        path = self.registry.path_of(entry, "reference")
        if not path.exists():
            log.warning("No reference profile %s: input drift is not checked", path.name)
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _baseline(entry: dict) -> dict:
        return entry.get("baseline") or entry.get("test") or {}

    def _use(self, model: str, entry: dict) -> None:
        obj = joblib.load(self.registry.path_of(entry))
        metrics = {"version": entry["version"], "test": entry.get("test")}
        registered = self.predictor.use_version(model, obj, entry["version"], entry["file"],
                                                metrics)  # fmt: skip
        if self.store is not None:
            threading.Thread(
                target=self.store.register_models, args=([registered],), daemon=True
            ).start()

    # ----- on the loop -----------------------------------------------------------------------
    def observe(self, records: list[dict]) -> None:
        for r in records:
            if r["model"] in self.monitors and r.get("actual") is not None:
                self.monitors[r["model"]].observe(r)
                self.live[r["model"]].append(r)

    def after_tick(self, tick: int) -> None:
        """Never lets an error reach the simulator loop: the warehouse runs without MLOps."""
        try:
            self._after_tick(tick)
        except Exception:
            log.exception("Model operations failed at tick %s; the warehouse carries on", tick)

    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _after_tick(self, tick: int) -> None:
        while self._pending:
            self._apply(*self._pending.popleft())
        if not self.monitors or tick % self.cfg["monitor"]["check_every_ticks"]:
            return
        for model, mon in self.monitors.items():
            before = (mon.last or {}).get("status")
            result = mon.check(tick)
            if result["status"] != before and result["status"] in ("OK", "WARN", "DRIFT"):
                text = "; ".join(result["reasons"]) or "inputs and live error as expected"
                self._event("status_" + result["status"].lower(), model, text)
            r = self.cfg["retrain"]
            due = tick - self._last_retrain.get(model, -(10**9)) >= r["cooldown_ticks"]
            # One retraining at a time: another model waits for its next check.
            if (r["auto"] and result["status"] == "DRIFT" and due and not self.busy()
                    and mon.confirmed >= self.cfg["drift"]["confirm_checks"]):  # fmt: skip
                self.start_retrain(model, "drift: " + "; ".join(result["reasons"]), "auto", tick)

    def _apply(self, model: str, version: str, by: str, event: str) -> None:
        entry = self.registry.get(model, version)
        self._use(model, entry)
        self.monitors[model].reset(self._profile(entry), self._baseline(entry))
        self._event(event, model, f"{version} in production", by)

    # ----- retraining ------------------------------------------------------------------------
    def start_retrain(self, model: str, reason: str, by: str, tick: int = 0) -> dict:
        if self.busy():
            raise RuntimeError(f"retraining {self.job['model']} is still running")
        if model not in self.live:
            raise KeyError(model)
        records = list(self.live[model])
        need = self.cfg["monitor"]["min_samples"]
        if len(records) < need:
            raise ValueError(f"{len(records)} finished predictions, {need} needed")
        self._last_retrain[model] = tick
        self.job = {"model": model, "status": "RUNNING", "reason": reason, "by": by,
                    "started": time.time(), "live_rows": len(records)}  # fmt: skip
        self._event("retrain_started", model, reason, by)
        self._thread = threading.Thread(
            target=self._retrain, args=(model, records, reason, by), daemon=True
        )
        self._thread.start()
        return self.job

    def _retrain(self, model: str, records: list[dict], reason: str, by: str) -> None:
        try:
            entry = retrain(model, records, self.registry, self.cfg, reason)
        except Exception as err:
            log.exception("Retraining %s failed", model)
            self.job.update(status="FAILED", error=f"{type(err).__name__}: {err}",
                            finished=time.time())  # fmt: skip
            self._event("retrain_failed", model, str(err), by)
            return
        self.counts["retrains"] += 1
        version = entry["version"]
        self.job.update(status="DONE", version=version, passed=entry["passed"],
                        gate=entry["gate"], finished=time.time())  # fmt: skip
        if not entry["passed"]:
            self.counts["rejected"] += 1
            failed = [t["test"] for t in entry["gate"] if not t["passed"]]
            self._event("candidate_rejected", model, f"{version} failed: {', '.join(failed)}")
        elif self.cfg["gate"]["auto_promote"]:
            self.registry.promote(model, version, by="gate")
            self.counts["promoted"] += 1
            self._pending.append((model, version, "gate", "promoted"))
        else:
            self._event("candidate_ready", model, f"{version} passed; waiting for approval")

    # ----- by hand ---------------------------------------------------------------------------
    def promote(self, model: str, version: str, by: str) -> dict:
        entry = self.registry.promote(model, version, by)
        self.counts["promoted"] += 1
        self._apply(model, version, by, "promoted")
        return entry

    def rollback(self, model: str, by: str) -> dict:
        entry = self.registry.rollback(model, by)
        self._apply(model, entry["version"], by, "rolled_back")
        return entry

    # ----- reporting -------------------------------------------------------------------------
    def _event(self, kind: str, model: str, text: str, by: str | None = None) -> None:
        self.events.appendleft({"at": time.time(), "event": kind, "model": model, "text": text,
                                "by": by})  # fmt: skip
        log.warning("Model %s: %s %s", model, kind, text)

    def take_events(self) -> list[dict]:
        """New events since the last call (for the platform event bus)."""
        fresh = [e for e in self.events if e["at"] > self._published]
        if fresh:
            self._published = fresh[0]["at"]
        return list(reversed(fresh))

    def status(self) -> dict:
        models = {}
        for model, mon in self.monitors.items():
            prod = self.registry.production(model)
            models[model] = {
                "production": prod["version"],
                "baseline": self._baseline(prod),
                "check": mon.last,
                "history": list(mon.history)[-60:],
                "live_rows": len(self.live.get(model, [])),
                "versions": [
                    {k: v.get(k) for k in ("version", "status", "created", "trained_on", "test",
                                           "gate", "reason", "history")}
                    for v in reversed(self.registry.versions(model))
                ],
            }  # fmt: skip
        job = dict(self.job) if self.job else None
        return {"models": models, "job": job, "events": list(self.events)[:30],
                "counts": self.counts,
                "settings": {"auto_retrain": self.cfg["retrain"]["auto"],
                             "auto_promote": self.cfg["gate"]["auto_promote"],
                             "check_every_ticks": self.cfg["monitor"]["check_every_ticks"],
                             "window": self.cfg["monitor"]["window"]}}  # fmt: skip


mlops = MlopsService()

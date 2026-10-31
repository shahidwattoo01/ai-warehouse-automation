"""Owns the single SimulationEngine, its background tick loop, the live stream fan-out and
(optionally) recording runs to PostgreSQL.

All engine access happens on the asyncio event loop (the tick loop and async endpoints). The only
worker-thread work is database I/O on rows already collected, or on an engine that has stopped.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from pathlib import Path

from ai.optimization.optimizer import BASELINE, Optimizer
from app.core.config import get_settings
from app.services.alerts import EVERY_TICKS
from app.services.alerts import centre as alert_centre
from app.services.copilot import copilot
from app.services.erp import erp
from app.services.events import events_service
from app.services.leader import LeaderLock
from app.services.mlops import mlops
from app.services.predictor import Predictor
from app.services.recovery import Recovery, snapshot_key
from app.services.run_store import RunStore
from app.services.vda5050 import vda
from simulation.environment.engine import SimulationEngine

MAX_QUEUED_FRAMES = 5  # a client this far behind skips frames instead of buffering without limit
FLUSH_SECONDS = 2.0  # how often recorded rows are written to the database


class SimulatorService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.tick_hz = self.settings.sim_tick_hz
        self.engine = self._new_engine()
        vda.attach(self.engine)  # the robots as VDA 5050 vehicles, the platform as master control
        erp.attach(self.engine)  # sales orders in, shipments and stock out
        events_service.attach(self.engine)  # platform events for other systems (message bus)
        self.predictor = Predictor()  # Phase 3 models, scored live against the simulator
        self.predictor.attach(self.engine)
        copilot.attach(self.engine)  # Phase 6: operator commands in plain language
        self.strategies = dict(BASELINE)  # Phase 4: the decision rules in use
        self.preset: str | None = "E2"
        self.optimizer = Optimizer(self.engine, self.predictor, self.strategies)
        self._layout_json: str | None = None
        self._task: asyncio.Task | None = None
        self._subscribers: set[asyncio.Queue[str]] = set()
        self.store = RunStore(self.settings.database_url) if self.settings.persist_runs else None
        mlops.attach(self.predictor, self.store)  # drift monitoring and retraining (PR-19)
        self._last_flush = time.monotonic()
        # Loop health for /ready and /metrics: when the loop last ran, how late it was, tick cost.
        self.loop_heartbeat = time.monotonic()
        self.loop_lag = 0.0
        self.ticks_total = 0
        self.tick_seconds_total = 0.0
        self.tick_seconds_max = 0.0
        # Recovery and active/standby (docs/recovery.md).
        key = snapshot_key(self.settings.jwt_secret) if self.settings.state_recovery else None
        self.recovery = Recovery(Path(self.settings.state_dir), key)
        self.role = "active"  # active | standby (HA_MODE=active-standby)
        self.leader: LeaderLock | None = None
        self._ha_task: asyncio.Task | None = None
        self._last_snapshot = time.monotonic()
        self._snapshot_mark: tuple | None = None
        self._writing: asyncio.Future | None = None

    def _new_engine(self) -> SimulationEngine:
        return SimulationEngine(
            seed=self.settings.sim_seed,
            overrides={
                "layout": self.settings.sim_layout,
                "inventory_model": self.settings.inventory_model,
                "safety": {"slow_zones": self.settings.safety_slow_zones},
            },
        )

    def _attach_services(self) -> None:
        vda.attach(self.engine)
        erp.attach(self.engine)
        events_service.attach(self.engine)
        self.predictor.attach(self.engine)
        copilot.attach(self.engine)
        self.optimizer = Optimizer(self.engine, self.predictor, self.strategies)  # same rules
        self._layout_json = None

    def adopt_engine(self, engine: SimulationEngine, strategies: dict, preset: str | None) -> None:
        """Take over a restored engine (recovery): every service follows it."""
        self.engine, self.strategies, self.preset = engine, dict(strategies), preset
        alert_centre.reset()  # the caller puts the saved incidents back
        self._attach_services()

    async def reset(self) -> None:
        """Start a fresh run: a new engine with the same layout and seed (stopped, speed 1x)."""
        old, self.engine = self.engine, self._new_engine()
        alert_centre.reset()  # incidents belong to a run
        self._attach_services()
        self._last_snapshot = 0.0  # save the new run soon: the old snapshot is no longer it
        if self.store:  # close the old run and open the new one (the old engine no longer ticks)
            await asyncio.to_thread(self.store.end_run, old)
            await asyncio.to_thread(self.store.start_run, self.engine, self.predictor.versions)
        self._layout_json = None
        self._broadcast(self.layout_message())  # connected clients re-sync to the new run
        self._broadcast(self.tick_message())

    def publish_state(self) -> None:
        """Send the current state to every client now. The loop only broadcasts while running, so
        after a pause clients would otherwise never learn that the run stopped."""
        self._broadcast(self.tick_message())

    # ----- background loop ---------------------------------------------------
    async def start_loop(self) -> None:
        if self.settings.ha_mode == "active-standby":
            self.role = "standby"  # until this instance holds the leader lock
            self.leader = LeaderLock(self.settings.database_url)
            self._ha_task = asyncio.create_task(self._watch_leadership())
        else:
            await self._become_active()

    async def _become_active(self) -> None:
        """Restore the latest saved state (if any), then run the loop."""
        if self.recovery.enabled:
            data = await asyncio.to_thread(self.recovery.load)
            if data is not None:
                self.recovery.adopt(self, data)
        if self.store:
            await asyncio.to_thread(self.store.start_run, self.engine, self.predictor.versions)
        self._snapshot_mark = (id(self.engine), self.engine.time)
        self._last_snapshot = time.monotonic()
        self.loop_heartbeat = time.monotonic()
        if self._task is None:
            self._task = asyncio.create_task(self._run())
            self._task.add_done_callback(_report_crash)
        self.role = "active"
        self.publish_state()

    async def _watch_leadership(self, every: float = 2.0) -> None:
        """Standby: wait for the leader lock. Active: step down the moment the lock is lost."""
        log = logging.getLogger(__name__)
        while True:
            if self.role == "standby":
                if await asyncio.to_thread(self.leader.try_acquire):
                    log.warning("Leader lock taken: this instance is now active")
                    await self._become_active()
            elif not await asyncio.to_thread(self.leader.still_held):
                log.critical("Leader lock lost: stepping down to standby")
                await self._stop_ticking()  # no snapshot: another instance may be active now
                self.role = "standby"
            await asyncio.sleep(every)

    async def _stop_ticking(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def stop_loop(self) -> None:
        if self._ha_task:
            self._ha_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._ha_task
            self._ha_task = None
        was_active = self._task is not None and self.role == "active"
        await self._stop_ticking()
        if was_active and self.recovery.enabled:  # a clean shutdown loses nothing
            await self.save_state()
        if self.store and was_active:
            await asyncio.to_thread(self.store.end_run, self.engine)
        if self.leader:
            await asyncio.to_thread(self.leader.release)

    async def save_state(self) -> dict:
        """Snapshot now (on the loop), write in a worker thread and wait for it."""
        if self._writing is not None:
            await self._writing
        blob = self.recovery.capture(self)
        await asyncio.to_thread(self.recovery.write, blob, self.engine.time)
        self._last_snapshot = time.monotonic()
        self._snapshot_mark = (id(self.engine), self.engine.time)
        return self.recovery.status()

    def _snapshot_if_due(self) -> None:
        """Every SNAPSHOT_SECONDS when the warehouse changed (and every 10 minutes regardless,
        since commands while paused change state without ticks)."""
        rec = self.recovery
        if not rec.enabled or self.role != "active" or self.settings.snapshot_seconds <= 0:
            return
        if self._writing is not None and not self._writing.done():
            return
        age = time.monotonic() - self._last_snapshot
        mark = (id(self.engine), self.engine.time)
        if age < self.settings.snapshot_seconds or (mark == self._snapshot_mark and age < 600):
            return
        try:
            blob = rec.capture(self)
        except Exception as err:  # never let a snapshot stop the warehouse
            rec.failures += 1
            rec.last_error = f"capture: {type(err).__name__}: {err}"
            logging.getLogger(__name__).exception("Could not capture the warehouse state")
            self._last_snapshot = time.monotonic()
            return
        self._last_snapshot, self._snapshot_mark = time.monotonic(), mark
        loop = asyncio.get_running_loop()
        self._writing = loop.run_in_executor(None, rec.write, blob, self.engine.time)

    async def _run(self) -> None:
        next_tick = time.monotonic()
        while True:
            engine = self.engine
            now = time.monotonic()
            self.loop_lag, self.loop_heartbeat = max(0.0, now - next_tick), now
            if engine.running:
                began = time.perf_counter()
                events = engine.tick()
                self.predictor.after_tick()
                self.optimizer.after_tick()
                vda.after_tick(events)
                erp.after_tick()
                if engine.time % EVERY_TICKS == 0:  # alert rules every 3 simulated minutes
                    alert_centre.evaluate(engine, self.predictor.snapshot())
                if self._subscribers:  # build the frame only if someone is watching
                    self._broadcast(self.tick_message(events))
                incidents = alert_centre.take_changed()
                events_service.after_tick(events, incidents)
                records, model_alerts = self.predictor.drain()
                mlops.observe(records)  # finished predictions: the drift monitors' data
                mlops.after_tick(engine.time)
                events_service.publish_models(mlops.take_events(), engine.time)
                if self.store:
                    self.store.collect(engine, events)
                    self.store.add_incidents(incidents)
                    self.store.add_predictions(records, model_alerts)
                cost = time.perf_counter() - began
                self.ticks_total += 1
                self.tick_seconds_total += cost
                self.tick_seconds_max = max(self.tick_seconds_max * 0.999, cost)  # slow decay
            self._flush_if_due()
            self._snapshot_if_due()
            # Fixed-rate schedule: the tick's own compute time does not slow the simulation down.
            next_tick += 1.0 / (self.tick_hz * engine.speed)
            # After a stall (e.g. laptop sleep), do not race to catch up.
            next_tick = max(next_tick, time.monotonic() - 1.0)
            await asyncio.sleep(max(0.0, next_tick - time.monotonic()))

    def set_strategies(self, strategies: dict, preset: str | None = None) -> dict:
        """Switch the decision rules of the running warehouse (applied between ticks)."""
        self.optimizer = Optimizer(self.engine, self.predictor, strategies)
        self.strategies, self.preset = self.optimizer.describe(), preset
        return self.strategies

    def _flush_if_due(self) -> None:
        """Every FLUSH_SECONDS hand collected rows to a worker thread (writes are serialised).
        Runs even when paused: the write also refreshes the run's heartbeat."""
        if not self.store or time.monotonic() - self._last_flush < FLUSH_SECONDS:
            return
        self._last_flush = time.monotonic()
        asyncio.get_running_loop().run_in_executor(None, self.store.write, self.store.take_batch())

    # ----- stream ------------------------------------------------------------
    def layout_message(self) -> str:
        """Static geometry, serialised once per run."""
        if self._layout_json is None:
            self._layout_json = json.dumps(
                {"type": "layout", "layout": self.engine.layout_snapshot()}
            )
        return self._layout_json

    def tick_message(self, events: list | None = None) -> str:
        state = self.engine.state(include_inventory=False)
        return json.dumps(
            {
                "type": "tick",
                "state": state,
                "predictions": self.predictor.snapshot(),
                "alerts": alert_centre.summary(),
                "strategy": {"preset": self.preset, **self.strategies},
                "events": [e.to_dict() for e in events or []],
            }
        )

    def _broadcast(self, frame: str) -> None:
        """Serialise once, hand the same string to every client."""
        for queue in list(self._subscribers):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(frame)

    def subscribe(self) -> asyncio.Queue[str]:
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=MAX_QUEUED_FRAMES)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[str]) -> None:
        self._subscribers.discard(queue)


def _report_crash(task: asyncio.Task) -> None:
    """The loop never ends on its own: if it does, say why (otherwise asyncio stays silent)."""
    if not task.cancelled() and task.exception() is not None:
        logging.getLogger(__name__).critical(
            "The simulator loop stopped", exc_info=task.exception()
        )


simulator = SimulatorService()

"""Owns the single SimulationEngine, its background tick loop, the live stream fan-out and
(optionally) recording runs to PostgreSQL.

All engine access happens on the asyncio event loop (the tick loop and async endpoints). The only
worker-thread work is database I/O on rows already collected, or on an engine that has stopped.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time

from ai.optimization.optimizer import BASELINE, Optimizer
from app.core.config import get_settings
from app.services.predictor import Predictor
from app.services.run_store import RunStore
from simulation.environment.engine import SimulationEngine

MAX_QUEUED_FRAMES = 5  # a client this far behind skips frames instead of buffering without limit
FLUSH_SECONDS = 2.0  # how often recorded rows are written to the database


class SimulatorService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.tick_hz = self.settings.sim_tick_hz
        self.engine = self._new_engine()
        self.predictor = Predictor()  # Phase 3 models, scored live against the simulator
        self.predictor.attach(self.engine)
        self.strategies = dict(BASELINE)  # Phase 4: the decision rules in use
        self.preset: str | None = "E2"
        self.optimizer = Optimizer(self.engine, self.predictor, self.strategies)
        self._layout_json: str | None = None
        self._task: asyncio.Task | None = None
        self._subscribers: set[asyncio.Queue[str]] = set()
        self.store = RunStore(self.settings.database_url) if self.settings.persist_runs else None
        self._last_flush = time.monotonic()

    def _new_engine(self) -> SimulationEngine:
        return SimulationEngine(
            seed=self.settings.sim_seed, overrides={"layout": self.settings.sim_layout}
        )

    async def reset(self) -> None:
        """Start a fresh run: a new engine with the same layout and seed (stopped, speed 1x)."""
        old, self.engine = self.engine, self._new_engine()
        self.predictor.attach(self.engine)
        self.optimizer = Optimizer(self.engine, self.predictor, self.strategies)  # same rules
        if self.store:  # close the old run and open the new one (the old engine no longer ticks)
            await asyncio.to_thread(self.store.end_run, old)
            await asyncio.to_thread(self.store.start_run, self.engine, self.predictor.versions)
        self._layout_json = None
        self._broadcast(self.layout_message())  # connected clients re-sync to the new run
        self._broadcast(self.tick_message())

    # ----- background loop ---------------------------------------------------
    async def start_loop(self) -> None:
        if self.store:
            await asyncio.to_thread(self.store.start_run, self.engine, self.predictor.versions)
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop_loop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self.store:
            await asyncio.to_thread(self.store.end_run, self.engine)

    async def _run(self) -> None:
        next_tick = time.monotonic()
        while True:
            engine = self.engine
            if engine.running:
                events = engine.tick()
                self.predictor.after_tick()
                self.optimizer.after_tick()
                if self._subscribers:  # build the frame only if someone is watching
                    self._broadcast(self.tick_message(events))
                if self.store:
                    self.store.collect(engine, events)
                    self.store.add_predictions(*self.predictor.drain())
                else:
                    self.predictor.drain()  # nothing records them: drop instead of piling up
            self._flush_if_due()
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


simulator = SimulatorService()

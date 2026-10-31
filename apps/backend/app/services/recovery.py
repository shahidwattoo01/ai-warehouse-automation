"""Restart recovery of the warehouse state (backlog PR-17).

The simulator owns the whole live warehouse in memory: robots, orders, stock, the WMS, safety
state. Every SNAPSHOT_SECONDS (and on a clean shutdown) it is saved to STATE_DIR, together with
what the services around it keep in memory: alert-centre incidents, the ERP connector's imports
and outbox (and the mock ERP's own books), the platform-event sequence and replay buffer. At
start-up the latest snapshot is restored, paused, so an operator checks the floor before robots
move again (and a standby instance taking over does the same; see app/services/leader.py).

File format: MAGIC, an HMAC-SHA256 over the compressed body, the zlib-compressed pickle. The HMAC
key is derived from JWT_SECRET; a file whose HMAC does not match is never unpickled (pickle would
run code), so a tampered or foreign file is set aside, not loaded. Without a fixed JWT_SECRET the
key would change at every start, so recovery is off then.

Writes are atomic (temp file + rename) and the previous snapshot is kept as `.prev`, so a crash
in the middle of a write leaves a good file. Pickling runs on the event loop (it reads the
engine; ~0.1 s for the large layout); compressing and writing run in a worker thread.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import hmac
import itertools
import logging
import os
import pickle
import time
import zlib
from collections import deque
from pathlib import Path

log = logging.getLogger(__name__)

MAGIC = b"WAI-STATE-1\n"
FORMAT = 1
NAME = "warehouse_state.bin"


def snapshot_key(jwt_secret: str) -> bytes | None:
    if not jwt_secret:
        return None
    return hmac.new(jwt_secret.encode(), b"warehouse-state-snapshot", hashlib.sha256).digest()


def _peek(counter: itertools.count) -> int:
    """The next value of an itertools.count without losing it (counts are not picklable from
    Python 3.14)."""
    return int(repr(counter)[len("count(") : -1])


# ----- what is saved besides the engine --------------------------------------------------------
def _alerts_state(centre) -> dict:
    names = ("incidents", "active", "quiet", "notifications", "_seq", "_seen", "_gone")
    return {n: getattr(centre, n) for n in names}


def _erp_state(erp) -> dict | None:
    c = erp.connector
    if c is None:
        return None
    m = erp.mock
    with c._lock, m._lock:
        return {
            "connector": {
                "imported": dict(c.imported),
                "rejected": dict(c.rejected),
                "outbox": list(c.outbox),
                "log": list(c.log),
                "_shipped": set(c._shipped),
                "last_pull": c.last_pull,
            },
            "mock": {
                "orders": dict(m.orders),
                "shipments": dict(m.shipments),
                "stock": dict(m.stock),
                "stock_updated": m.stock_updated,
                "_stock_keys": set(m._stock_keys),
                "received": dict(m.received),
                "next_number": _peek(m._numbers),
            },
        }


def _restore_erp(erp, saved: dict | None) -> None:
    if not saved or erp.connector is None:
        return
    c, m = erp.connector, erp.mock
    with c._lock:
        cs = saved["connector"]
        c.imported, c.rejected, c._shipped = cs["imported"], cs["rejected"], cs["_shipped"]
        c.outbox = deque(cs["outbox"], maxlen=c.outbox.maxlen)
        c.log = deque(cs["log"], maxlen=c.log.maxlen)
        c.last_pull = cs["last_pull"]
    with m._lock:
        ms = saved["mock"]
        for name in ("orders", "shipments", "stock", "stock_updated", "_stock_keys", "received"):
            setattr(m, name, ms[name])
        m._numbers = itertools.count(ms["next_number"])


def _events_state(service) -> dict | None:
    p = service.publisher
    if p is None:
        return None
    return {
        "seq": p.seq,
        "recent": list(p.recent),
        "counts": dict(p.counts),
        "order_status": dict(service._order_status),
        "safety_seq": service._safety_seq,
        "alert_seq": service._alert_seq,
    }


def _restore_events(service, saved: dict | None) -> None:
    if not saved or service.publisher is None:
        return
    p = service.publisher
    p.seq, p.counts = saved["seq"], saved["counts"]  # subscribers' `after=` stays valid
    p.recent = deque(saved["recent"], maxlen=p.recent.maxlen)
    service._order_status = saved["order_status"]
    service._safety_seq, service._alert_seq = saved["safety_seq"], saved["alert_seq"]


# ----- the snapshot file -----------------------------------------------------------------------
class Recovery:
    def __init__(self, state_dir: Path, key: bytes | None) -> None:
        self.dir = Path(state_dir)
        self.key = key
        self.path = self.dir / NAME
        self.saved_at: float | None = None  # wall clock of the last good write
        self.saved_tick: int | None = None
        self.size = 0
        self.capture_seconds = 0.0
        self.writes = 0
        self.failures = 0
        self.restored: dict | None = None  # what start-up restored, for the status page
        self.last_error: str | None = None

    @property
    def enabled(self) -> bool:
        return self.key is not None

    def capture(self, simulator) -> bytes:
        """Pickle everything worth keeping. Call on the event loop (engine access)."""
        from app.services.alerts import centre
        from app.services.erp import erp
        from app.services.events import events_service

        began = time.perf_counter()
        eng = simulator.engine
        data = {
            "format": FORMAT,
            "saved_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "tick": eng.time,
            "engine": eng,
            "strategies": simulator.strategies,
            "preset": simulator.preset,
            "alerts": _alerts_state(centre),
            "erp": _erp_state(erp),
            "events": _events_state(events_service),
        }
        blob = pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL)
        self.capture_seconds = time.perf_counter() - began
        return blob

    def write(self, blob: bytes, tick: int) -> None:
        """Compress, sign and store atomically (worker thread)."""
        try:
            body = zlib.compress(blob, 3)
            mac = hmac.new(self.key, body, hashlib.sha256).digest()
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "wb") as fh:
                fh.write(MAGIC + mac + body)
                fh.flush()
                os.fsync(fh.fileno())
            if self.path.exists():
                os.replace(self.path, self.path.with_suffix(".prev"))
            os.replace(tmp, self.path)
            self.saved_at, self.saved_tick, self.size = time.time(), tick, len(body)
            self.writes += 1
            self.last_error = None
        except OSError as err:
            self.failures += 1
            self.last_error = f"{type(err).__name__}: {err}"
            log.error("Could not save the warehouse state: %s", self.last_error)

    def _read(self, path: Path) -> dict | None:
        raw = path.read_bytes()
        if not raw.startswith(MAGIC):
            raise ValueError("not a warehouse state file")
        mac, body = raw[len(MAGIC) : len(MAGIC) + 32], raw[len(MAGIC) + 32 :]
        good = hmac.new(self.key, body, hashlib.sha256).digest()
        if not hmac.compare_digest(mac, good):
            raise ValueError("signature does not match (other JWT_SECRET, or changed on disk)")
        data = pickle.loads(zlib.decompress(body))  # noqa: S301 (signed by us, checked above)
        if data.get("format") != FORMAT:
            raise ValueError(f"format {data.get('format')} is not {FORMAT}")
        return data

    def load(self) -> dict | None:
        """The newest readable snapshot, or None. Bad files are renamed `.rejected`."""
        if not self.enabled:
            return None
        for path in (self.path, self.path.with_suffix(".prev")):
            if not path.exists():
                continue
            try:
                data = self._read(path)
                log.info("Found warehouse state from %s (tick %s)", data["saved_at"], data["tick"])
                return data
            except Exception as err:  # unreadable, foreign, or from incompatible code
                self.last_error = f"{path.name}: {err}"
                log.error("Ignoring saved state %s: %s", path.name, err)
                with contextlib.suppress(OSError):
                    os.replace(path, path.with_suffix(".rejected"))
        return None

    def adopt(self, simulator, data: dict) -> None:
        """Put a loaded snapshot in place (on the event loop, before the loop ticks)."""
        from app.services.alerts import centre
        from app.services.erp import erp
        from app.services.events import events_service

        engine = data["engine"]
        engine.running = False  # an operator checks the floor before robots move again
        simulator.adopt_engine(engine, data["strategies"], data["preset"])
        for name, value in data["alerts"].items():
            setattr(centre, name, value)
        _restore_erp(erp, data["erp"])
        _restore_events(events_service, data["events"])
        self.restored = {"saved_at": data["saved_at"], "tick": data["tick"]}
        log.warning(
            "Restored the warehouse from %s at tick %s (paused)", data["saved_at"], data["tick"]
        )

    def status(self) -> dict:
        return {
            "enabled": self.enabled,
            "file": str(self.path),
            "saved_at": (
                dt.datetime.fromtimestamp(self.saved_at, dt.UTC).isoformat(timespec="seconds")
                if self.saved_at
                else None
            ),
            "age_seconds": round(time.time() - self.saved_at, 1) if self.saved_at else None,
            "saved_tick": self.saved_tick,
            "size_bytes": self.size,
            "capture_ms": round(self.capture_seconds * 1000, 1),
            "writes": self.writes,
            "failures": self.failures,
            "restored": self.restored,
            "last_error": self.last_error,
        }

"""Active/standby instances behind a load balancer (backlog PR-17).

The live warehouse is one simulation in one process, so two backends must never both run it.
With HA_MODE=active-standby every instance tries to take a PostgreSQL advisory lock; the one that
holds it is active (restores the latest state snapshot and runs the loop), the others are standby
(answer 503, so the load balancer sends traffic to the active one) and keep trying.

The lock belongs to a database session: when the active process dies, or loses its database
connection, PostgreSQL releases it and a standby takes over within a few seconds from the shared
state directory. An active instance that can no longer see its lock steps down at once, so there
is never a time with two writers.
"""

from __future__ import annotations

import logging

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

log = logging.getLogger(__name__)

LOCK_KEY = 0x57414931  # "WAI1": one key for the whole platform


class LeaderLock:
    def __init__(self, database_url: str, key: int = LOCK_KEY) -> None:
        self.db = create_engine(database_url, poolclass=NullPool, future=True)
        self.key = key
        self.conn = None

    @property
    def held(self) -> bool:
        return self.conn is not None

    def try_acquire(self) -> bool:
        """Take the lock if nobody has it (blocking I/O: call from a worker thread)."""
        if self.conn is not None:
            return True
        try:
            conn = self.db.connect().execution_options(isolation_level="AUTOCOMMIT")
        except Exception as err:
            log.warning("Leader lock: database not reachable (%s)", type(err).__name__)
            return False
        got = conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": self.key}).scalar()
        if got:
            self.conn = conn
            return True
        conn.close()
        return False

    def still_held(self) -> bool:
        """False once the session holding the lock is gone (then the lock is gone too)."""
        if self.conn is None:
            return False
        try:
            self.conn.execute(text("SELECT 1"))
            return True
        except Exception as err:
            log.error("Leader lock lost with the database session (%s)", type(err).__name__)
            self._drop()
            return False

    def release(self) -> None:
        if self.conn is None:
            return
        try:
            self.conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": self.key})
        except Exception:  # the session is gone: so is the lock
            pass
        self._drop()

    def _drop(self) -> None:
        conn, self.conn = self.conn, None
        try:
            conn.close()
        except Exception:
            pass


class StandbyMiddleware:
    """A standby instance answers 503 to everything but the probes, so the load balancer retries
    on the active instance (nginx: proxy_next_upstream http_503). Live streams are closed with
    1013 (try again later)."""

    def __init__(self, app, is_active, exempt: tuple[str, ...] = ("/health", "/ready", "/metrics")):
        self.app = app
        self.is_active = is_active
        self.exempt = exempt

    async def __call__(self, scope, receive, send) -> None:
        if (
            scope["type"] not in ("http", "websocket")
            or self.is_active()
            or (scope["path"] in self.exempt)
        ):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1013})
            return
        from starlette.responses import JSONResponse

        body = {"detail": {"code": "standby", "message": "This instance is on standby"}}
        await JSONResponse(body, status_code=503, headers={"Retry-After": "2"})(
            scope, receive, send
        )

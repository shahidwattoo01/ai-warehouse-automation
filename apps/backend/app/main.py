"""FastAPI entry point — Warehouse AI Platform backend."""

from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Make the repo root importable (simulation/, ai/) when running from apps/backend.
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import hmac  # noqa: E402

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse, PlainTextResponse  # noqa: E402

from app.api.v1 import api_router  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.observability import RequestMiddleware, setup_logging  # noqa: E402
from app.core.ratelimit import (  # noqa: E402
    RateLimiter,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    default_rules,
)
from app.core.security import OriginCheckMiddleware  # noqa: E402
from app.services import monitoring  # noqa: E402
from app.services.leader import StandbyMiddleware  # noqa: E402
from app.services.simulator import simulator  # noqa: E402


@asynccontextmanager
async def lifespan(_: FastAPI):
    await simulator.start_loop()
    yield
    await simulator.stop_loop()


settings = get_settings()
setup_logging(settings.log_format, settings.log_level)
app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
# Order matters: the origin check runs first, then CORS answers preflights for allowed origins.
# Credentials are allowed only for the listed origins (never "*").
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=True,  # the refresh-token cookie (httpOnly) is sent to /auth
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)
app.add_middleware(OriginCheckMiddleware, allowed_origins=settings.cors_list)
# A standby instance (HA_MODE=active-standby) refuses work before anything else runs.
app.add_middleware(StandbyMiddleware, is_active=lambda: simulator.role == "active")
# Added last = runs first: over-limit requests are refused before any other work.
limiter = RateLimiter(default_rules(settings.api_prefix, settings.rate_limit_scale))
app.add_middleware(
    RateLimitMiddleware,
    limiter=limiter,
    enabled=settings.rate_limit_enabled,
    trust_proxy=settings.trust_proxy_headers,
    exempt=("/health", "/ready", "/metrics"),  # probes and scrapes are never throttled
)
# Outermost: every answer carries the security headers, refusals included.
app.add_middleware(
    SecurityHeadersMiddleware, api_prefix=settings.api_prefix, https=settings.cookie_secure
)
# Outermost of all: request id, timing and HTTP metrics see every answer, refusals included.
app.add_middleware(RequestMiddleware)
app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/health", tags=["health"])
async def health() -> dict:
    """Liveness: the process answers (restart it if this fails)."""
    return {"status": "ok", "tick": simulator.engine.time}


@app.get("/ready", tags=["health"])
async def ready() -> JSONResponse:
    """Readiness: the simulator loop ticks and the required services answer (503 if not)."""
    ok, checks = await asyncio.to_thread(monitoring.readiness, simulator)
    return JSONResponse({"ready": ok, "checks": checks}, status_code=200 if ok else 503)


@app.get("/metrics", tags=["health"], include_in_schema=False)
async def metrics(request: Request) -> PlainTextResponse:
    """Prometheus metrics (text format 0.0.4); needs `Bearer METRICS_TOKEN` when one is set."""
    if settings.metrics_token:
        sent = request.headers.get("authorization", "")
        if not hmac.compare_digest(sent.encode(), f"Bearer {settings.metrics_token}".encode()):
            return PlainTextResponse("unauthorised\n", status_code=401)
    body = monitoring.collect(simulator, limiter)
    return PlainTextResponse(body, media_type="text/plain; version=0.0.4; charset=utf-8")

"""FastAPI entry point — Warehouse AI Platform backend."""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Make the repo root importable (simulation/, ai/) when running from apps/backend.
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from app.api.v1 import api_router  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.security import OriginCheckMiddleware  # noqa: E402
from app.services.simulator import simulator  # noqa: E402


@asynccontextmanager
async def lifespan(_: FastAPI):
    await simulator.start_loop()
    yield
    await simulator.stop_loop()


settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
# Order matters: the origin check runs first, then CORS answers preflights for allowed origins.
# Credentials are allowed only for the listed origins (never "*").
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=True,  # the refresh-token cookie (httpOnly) is sent to /auth
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type", "Authorization"],
)
app.add_middleware(OriginCheckMiddleware, allowed_origins=settings.cors_list)
app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok", "tick": simulator.engine.time}

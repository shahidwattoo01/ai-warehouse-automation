"""FastAPI application entry point.

Routers under ``warehouse_ai.api.routers`` are included here as they are implemented.
"""

from __future__ import annotations

from fastapi import FastAPI

from warehouse_ai import __version__

app = FastAPI(title="Warehouse AI Platform", version=__version__)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check used by Docker, monitoring and the n8n MLOps workflow."""
    return {"status": "ok", "version": __version__}

"""Model operations (backlog PR-19; docs/mlops.md): drift status, retraining, promotion."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import Principal, need, require
from app.services.mlops import MODELS, mlops

router = APIRouter(prefix="/mlops", tags=["mlops"])
Manager = Annotated[Principal, Depends(require("models:manage"))]


def _model(model: str) -> str:
    if model not in MODELS or model not in mlops.monitors:
        raise HTTPException(404, {"code": "not_found", "message": f"No live model {model}"})
    return model


@router.get("/status", dependencies=[need("analytics:view")])
async def status() -> dict:
    """Per model: production version, last drift check, history, versions and gate results."""
    return mlops.status()


@router.post("/{model}/retrain")
async def retrain(model: str, user: Manager) -> dict:
    """Train a candidate now on the recent live outcomes; the gate decides about promotion."""
    try:
        return mlops.start_retrain(_model(model), f"requested by {user.username}", user.username)
    except (RuntimeError, ValueError) as err:
        raise HTTPException(409, {"code": "cannot_retrain", "message": str(err)}) from err


@router.post("/{model}/promote/{version}")
async def promote(model: str, version: str, user: Manager) -> dict:
    """Put a candidate that passed its gate (or an archived version) into production."""
    try:
        entry = mlops.promote(_model(model), version, user.username)
    except KeyError as err:
        raise HTTPException(404, {"code": "not_found", "message": str(err)}) from err
    except ValueError as err:
        raise HTTPException(409, {"code": "gate_failed", "message": str(err)}) from err
    return {"model": model, "production": entry["version"]}


@router.post("/{model}/rollback")
async def rollback(model: str, user: Manager) -> dict:
    """Back to the previous production version."""
    try:
        entry = mlops.rollback(_model(model), user.username)
    except ValueError as err:
        raise HTTPException(409, {"code": "no_rollback", "message": str(err)}) from err
    return {"model": model, "production": entry["version"]}

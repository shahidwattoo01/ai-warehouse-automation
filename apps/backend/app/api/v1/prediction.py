"""Prediction endpoints (TRD Section 7): the Phase 3 models running on the live simulation."""

from __future__ import annotations

from fastapi import APIRouter

from app.services.simulator import simulator

router = APIRouter(prefix="/prediction", tags=["prediction"])


@router.get("/live")
async def live() -> dict:
    """Current predictions: ETA and late risk per active order, robot health, next-hour demand,
    plus each model's live accuracy on this run and its offline test score."""
    return simulator.predictor.snapshot()


@router.get("/eta/{order_id}")
async def eta(order_id: str) -> dict:
    """Predicted delivery of one order (made when it was assigned)."""
    pred = simulator.predictor.orders.get(order_id)
    return {"order_id": order_id, "prediction": pred}


@router.get("/anomaly/{robot_id}")
async def anomaly(robot_id: str) -> dict:
    """Latest anomaly score of one robot (every 10 ticks, from its last 20 ticks)."""
    return {"robot_id": robot_id, "health": simulator.predictor.robot_health.get(robot_id)}


@router.get("/demand")
async def demand() -> dict:
    """Forecast for the current simulated hour and the recent forecast-vs-actual history."""
    return simulator.predictor.snapshot().get("demand", {})

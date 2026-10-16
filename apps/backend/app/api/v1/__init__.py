"""API v1 router aggregation."""

from fastapi import APIRouter

from app.api.v1 import (
    agents,
    analytics,
    copilot,
    inventory,
    navigation,
    orders,
    prediction,
    rag,
    robots,
    simulation,
    tools,
    vision,
)

api_router = APIRouter()
api_router.include_router(simulation.router)
api_router.include_router(robots.router)
api_router.include_router(orders.router)
api_router.include_router(inventory.router)
api_router.include_router(prediction.router)
api_router.include_router(vision.router)
api_router.include_router(navigation.router)
api_router.include_router(rag.router)
api_router.include_router(agents.router)
api_router.include_router(tools.router)
api_router.include_router(copilot.router)
api_router.include_router(analytics.router)

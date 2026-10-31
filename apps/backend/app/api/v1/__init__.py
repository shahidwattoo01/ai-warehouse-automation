"""API v1 router aggregation."""

from fastapi import APIRouter

from app.api.v1 import (
    agents,
    alerts,
    analytics,
    auth,
    copilot,
    erp,
    events,
    inventory,
    mlops,
    navigation,
    orders,
    prediction,
    rag,
    robots,
    safety,
    simulation,
    tools,
    vda5050,
    vision,
    wms,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(auth.users_router)
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
api_router.include_router(wms.router)
api_router.include_router(safety.router)
api_router.include_router(alerts.router)
api_router.include_router(vda5050.router)
api_router.include_router(erp.router)
api_router.include_router(events.router)
api_router.include_router(mlops.router)

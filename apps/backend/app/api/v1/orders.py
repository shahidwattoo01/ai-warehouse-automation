"""Orders endpoints (TRD Section 7).

Writes go through simulator commands, never direct mutation. The endpoints are async so they run
on the same event loop as the tick loop: validation reads a consistent state between ticks, and the
command is applied at the start of the next tick (0.5 s at 1x speed).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.auth import need
from app.schemas.simulation import AssignOrderRequest, CreateOrderRequest
from app.services.simulator import simulator
from simulation.environment.engine import Command

router = APIRouter(prefix="/orders", tags=["orders"])

STATUS_ORDER = {
    "PENDING": 0,
    "ASSIGNED": 1,
    "IN_PROGRESS": 2,
    "LATE": 3,
    "DELIVERED": 4,
    "CANCELLED": 5,
}


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message})


@router.get("", dependencies=[need("dashboard:view")])
async def list_orders() -> list[dict]:
    """List orders (pending first, then in progress, then finished; oldest first within each)."""
    orders = [o.to_dict() for o in simulator.engine.orders.values()]
    return sorted(orders, key=lambda o: (STATUS_ORDER.get(o["status"], 9), o["order_time"]))


@router.post("", status_code=202, dependencies=[need("orders:create")])
async def create_order(body: CreateOrderRequest) -> dict:
    """Create an order as an operator. With no items, random in-stock products are picked."""
    engine = simulator.engine
    for item in body.items:
        if item.product_id not in engine.inventory:
            raise _error(422, "unknown_product", f"No product {item.product_id} in this warehouse")
        have = engine.inventory.stock_of(item.product_id)
        if have < item.quantity:
            raise _error(409, "out_of_stock", f"{item.product_id} has only {have} in stock")
    if body.robot_id:
        robot = engine.robots.get(body.robot_id)
        if robot is None:
            raise _error(404, "not_found", f"Robot {body.robot_id} not found")
        if reason := engine.controller.unavailable_reason(robot):
            raise _error(409, "robot_unavailable", reason)
    order_id = engine.next_order_id()
    args = {
        "order_id": order_id,
        "priority": body.priority,
        "items": [i.model_dump() for i in body.items],
        "robot_id": body.robot_id,
    }
    engine.submit(Command("create_order", args))
    return {"queued": "create_order", "order_id": order_id, "robot_id": body.robot_id}


@router.post("/{order_id}/assign", status_code=202, dependencies=[need("orders:assign")])
async def assign_order(order_id: str, body: AssignOrderRequest) -> dict:
    """Assign a waiting order to a specific robot (manual dispatch)."""
    engine = simulator.engine
    order = engine.orders.get(order_id)
    if order is None:
        raise _error(404, "not_found", f"Order {order_id} not found")
    if order.status.value != "PENDING":
        raise _error(409, "not_pending", f"{order_id} is already {order.status.value.lower()}")
    robot = engine.robots.get(body.robot_id)
    if robot is None:
        raise _error(404, "not_found", f"Robot {body.robot_id} not found")
    if reason := engine.controller.unavailable_reason(robot):
        raise _error(409, "robot_unavailable", reason)
    engine.submit(Command("assign_order", {"order_id": order_id, "robot_id": body.robot_id}))
    return {"queued": "assign_order", "order_id": order_id, "robot_id": body.robot_id}

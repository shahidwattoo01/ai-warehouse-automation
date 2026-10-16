"""Inventory endpoints (TRD Section 7)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.services.simulator import simulator

router = APIRouter(prefix="/inventory", tags=["inventory"])


def _item(product_id: str) -> dict:
    inventory = simulator.engine.inventory
    product = inventory.catalog[product_id]
    x, y = inventory.face[product_id]
    return {
        "product_id": product_id,
        "name": product.name,
        "category": product.category,
        "weight_kg": product.weight_kg,
        "location": product.location,  # rack location Zone-Row-Bay, e.g. "A-05-12"
        "shelf_id": product.shelf_id,
        "pick_face": {"x": x, "y": y},
        "stock": inventory.stock[product_id],
        "restocking": inventory.restocking(product_id),
    }


@router.get("")
async def list_inventory() -> list[dict]:
    """Every product with its rack location and stock (order forms, the copilot)."""
    return [_item(p) for p in sorted(simulator.engine.inventory.face)]


@router.get("/{product_id}")
async def get_inventory(product_id: str) -> dict:
    """Stock and shelf location of one product."""
    if product_id not in simulator.engine.inventory:
        raise HTTPException(
            404, detail={"code": "not_found", "message": f"Product {product_id} not found"}
        )
    return _item(product_id)

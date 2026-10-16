from typing import Literal

from pydantic import BaseModel, Field


class SpeedRequest(BaseModel):
    multiplier: float = Field(gt=0, le=50)


class AssignmentModeRequest(BaseModel):
    mode: Literal["auto", "manual"]


class StrategyRequest(BaseModel):
    """Either a Phase 4 experiment preset (E1-E5) or individual strategies."""

    preset: str | None = Field(default=None, pattern=r"^E\d[a-z]?$")
    assignment: Literal["nearest", "random", "eta", "global"] | None = None
    planner: Literal["bfs", "dijkstra", "astar"] | None = None
    traffic_aware: bool | None = None
    traffic_weight: float | None = Field(default=None, ge=0, le=5)
    positioning: Literal["balanced", "demand"] | None = None
    charging: Literal["threshold", "predictive"] | None = None
    replanning: bool | None = None


class OrderItemIn(BaseModel):
    product_id: str
    quantity: int = Field(default=1, ge=1, le=20)


class CreateOrderRequest(BaseModel):
    priority: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    items: list[OrderItemIn] = Field(
        default_factory=list, max_length=4
    )  # empty: random in-stock items
    robot_id: str | None = None  # assign straight away to this robot


class AssignOrderRequest(BaseModel):
    robot_id: str

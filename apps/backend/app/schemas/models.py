"""API data models — the contract between backend, frontend and tool layer (Backend Schema §11)."""

from __future__ import annotations

from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class RobotStatus(str, Enum):
    IDLE = "IDLE"
    MOVING = "MOVING"
    PICKING = "PICKING"
    DELIVERING = "DELIVERING"
    CHARGING = "CHARGING"
    PAUSED = "PAUSED"
    FAULT = "FAULT"


class Priority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Position(BaseModel):
    x: int
    y: int


class RobotOut(BaseModel):
    robot_id: str
    position: Position
    battery: float = Field(ge=0, le=100)
    speed: float
    status: RobotStatus
    load: int
    current_task: str | None = None
    route: list[Position] = []
    anomaly_score: float | None = None


class OrderItem(BaseModel):
    product_id: str
    quantity: int = Field(gt=0)


class OrderOut(BaseModel):
    order_id: str
    items: list[OrderItem]
    priority: Priority
    order_tick: int
    deadline_tick: int
    status: str
    assigned_robot: str | None = None
    predicted_eta_ticks: float | None = None


class InventoryOut(BaseModel):
    product_id: str
    shelf_location: Position
    stock: int


class WarehouseState(BaseModel):
    run_id: UUID | None = None
    time: int
    robots: list[RobotOut]
    orders: list[OrderOut]
    inventory: list[InventoryOut]
    obstacles: list[dict]
    stations: list[dict]
    congestion: dict[str, float]


class ParsedCommand(BaseModel):
    intent: Literal[
        "status_query",
        "investigation",
        "task_assignment",
        "prioritise",
        "reroute",
        "pause",
        "resume",
        "knowledge_query",
    ]
    entities: dict[str, str | None]


class ToolCall(BaseModel):
    tool: str
    arguments: dict
    result: dict | None = None
    duration_ms: int | None = None


class AgentAction(BaseModel):
    action_id: UUID
    agent: str
    tool: str
    arguments: dict
    is_write: bool
    status: Literal["PROPOSED", "APPROVED", "REJECTED", "EXECUTED", "VERIFIED", "FAILED"]
    reason: str | None = None


class Source(BaseModel):
    source: str
    section: str
    snippet: str


class CopilotRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: UUID | None = None


class CopilotResponse(BaseModel):
    session_id: UUID
    answer: str
    route: Literal["monitoring", "investigation", "planning", "knowledge", "action", "clarify"]
    tools_called: list[ToolCall] = []
    sources: list[Source] = []
    pending_actions: list[AgentAction] = []


class RagAnswer(BaseModel):
    answer: str
    sources: list[Source]
    grounded: bool

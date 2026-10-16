"""Core simulator entities. Field names match the warehouse_state schema (TRD 4.2)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum


class RobotStatus(str, Enum):
    IDLE = "IDLE"
    MOVING = "MOVING"
    PICKING = "PICKING"
    DELIVERING = "DELIVERING"
    CHARGING = "CHARGING"
    PAUSED = "PAUSED"
    FAULT = "FAULT"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    DELIVERED = "DELIVERED"
    LATE = "LATE"
    CANCELLED = "CANCELLED"


class Priority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass
class Shelf:
    shelf_id: str
    zone_id: str
    x: int
    y: int
    levels: int = 4


@dataclass
class Station:
    station_id: str
    type: str  # PACKING | CHARGING
    x: int
    y: int
    capacity: int = 1
    queue: int = 0


@dataclass
class Zone:
    zone_id: str
    name: str
    bounds: tuple[int, int, int, int]  # x_min, y_min, x_max, y_max
    capacity: int

    def contains(self, x: int, y: int) -> bool:
        x0, y0, x1, y1 = self.bounds
        return x0 <= x <= x1 and y0 <= y <= y1


@dataclass
class Robot:
    robot_id: str
    position: tuple[int, int]
    battery: float = 100.0
    speed: float = 1.0
    status: RobotStatus = RobotStatus.IDLE
    current_task: str | None = None
    load: int = 0
    route: list[tuple[int, int]] = field(default_factory=list)
    heading: float = 0.0  # radians, used by the 3D view for orientation
    temperature: float = 24.0  # drive-motor temperature, deg C (simulation/robots/thermal.py)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        d["position"] = list(self.position)
        d["route"] = [list(p) for p in self.route]
        return d


@dataclass
class OrderItem:
    product_id: str
    quantity: int


@dataclass
class Order:
    order_id: str
    items: list[OrderItem]
    priority: Priority
    order_time: int
    deadline: int
    status: OrderStatus = OrderStatus.PENDING
    assigned_robot: str | None = None
    destination: str | None = None
    source: str = "GENERATOR"  # GENERATOR (simulated customer demand) | MANUAL (operator)
    delivered_at: int | None = None  # tick the order reached its packing station
    manual_assignment: bool = False  # robot chosen by an operator rather than the dispatcher

    def to_dict(self) -> dict:
        d = asdict(self)
        d["priority"] = self.priority.value
        d["status"] = self.status.value
        return d


@dataclass
class Obstacle:
    position: tuple[int, int]
    type: str  # WORKER | PACKAGE (dropped parcel) | DEBRIS (fallen pallet)
    until: int | None = None
    obstacle_id: str | None = None

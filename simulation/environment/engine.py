"""Simulation engine: owns the only authoritative warehouse_state (TRD 4.3).

Each tick (TR-SIM-01):
    1. apply operator commands      (pause/resume robots, create/assign orders, dispatch mode)
    2. customer orders arrive       (orders/generator.py)
    3. aisles close/reopen, floor hazards appear/clear (environment/hazards.py)
    4. dispatcher assigns orders    (orders/dispatcher.py)
    5. faults are injected/cleared  (environment/faults.py)
    6. robots work or move          (robots/controller.py), motors heat/cool (robots/thermal.py)
    7. workers walk                 (environment/workers.py)
    8. congestion, restocking, order pruning

Nothing outside the engine mutates state directly: the API and AI tools submit Commands, which are
applied at the start of the next tick.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from simulation.environment.congestion import zone_congestion
from simulation.environment.faults import FaultInjector
from simulation.environment.hazards import Hazards
from simulation.environment.kpis import Kpis
from simulation.environment.safety import Safety
from simulation.environment.workers import Workers
from simulation.events.events import Event, EventBus, EventType
from simulation.inventory.inventory import Inventory
from simulation.navigation.distance import DistanceFields
from simulation.navigation.planner import Planner, get_planner
from simulation.orders.dispatcher import Dispatcher
from simulation.orders.generator import OrderGenerator
from simulation.robots.controller import RobotController
from simulation.robots.thermal import thermal_config, update_temperatures
from simulation.warehouse.entities import (
    Obstacle,
    Order,
    OrderItem,
    OrderStatus,
    Priority,
    Robot,
    RobotStatus,
)
from simulation.warehouse.layout import CONFIG_DIR, Layout, load_layout

Cell = tuple[int, int]
KEEP_FINISHED_ORDERS = 50  # finished orders kept in the state (bounds the live payload)
OPERATOR_CLOSURE_TICKS = 10**9  # an aisle an operator closes stays closed until reopened


@dataclass
class Command:
    """A change request from the API or an AI tool, applied at the start of the next tick.

    name: pause_robot | resume_robot | create_order | assign_order | set_assignment_mode
    """

    name: str
    args: dict = field(default_factory=dict)


def _deep_merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for k, v in extra.items():
        out[k] = (
            _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
        )
    return out


class SimulationEngine:
    def __init__(
        self,
        config_path: Path | None = None,
        seed: int | None = None,
        overrides: dict | None = None,
    ) -> None:
        cfg_file = config_path or CONFIG_DIR / "simulation.yaml"
        self.config: dict = _deep_merge(yaml.safe_load(cfg_file.read_text()), overrides or {})
        self.seed = seed if seed is not None else self.config["seed"]
        self.rng = random.Random(self.seed)  # the one source of randomness: runs are reproducible

        self.layout: Layout = load_layout(self.config["layout"])
        self.planner: Planner = get_planner(self.config["strategies"]["planner"])
        self.distances = DistanceFields(self.layout.grid)  # cached legal route lengths
        self.events = EventBus()

        self.time = 0
        self.running = False
        self.speed = 1.0
        self.robots: dict[str, Robot] = {}
        self.orders: dict[str, Order] = {}
        self.obstacles: list[Obstacle] = []
        self.congestion: dict[str, float] = {}
        self._commands: list[Command] = []

        # Construction order matters: each part draws from self.rng in turn.
        if self.config.get("inventory_model", "simple") == "wms":
            from simulation.inventory.wms_stock import WmsStock

            self.inventory = WmsStock(
                self.layout,
                self.seed,
                self.config.get("ticks_per_hour", 3600),
                self.config.get("wms"),
                self.config.get("orders"),
            )
        else:
            self.inventory = Inventory(self.layout, self.stream("inventory"))
        self.controller = RobotController(self)
        self._spawn_robots()
        self.workers = Workers(self)
        self.faults = FaultInjector(self)
        self.hazards = Hazards(self)
        self.thermal = thermal_config(self.config)
        self.generator = OrderGenerator(self.config, self.stream("orders"))
        self.safety = Safety(self)  # e-stop, slow zones, safety log (no randomness)
        self.dispatcher = Dispatcher(self)
        self.kpis = Kpis(self)

    def stream(self, name: str) -> random.Random:
        """Random numbers for an environment process (orders, faults, hazards, inventory).

        By default everything shares the engine's one generator (dataset v3 and the golden master
        depend on that). With `independent_streams: true` each process gets its own generator from
        the seed, so the orders, faults and hazards stay the same whatever the robots decide: the
        fair setup for comparing strategies (common random numbers, scripts/run_experiments.py).
        """
        if self.config.get("independent_streams", False):
            return random.Random(f"{self.seed}:{name}")
        return self.rng

    def _spawn_robots(self) -> None:
        """Robots start spread over the parking areas (small layouts: along the service lane)."""
        cfg = self.layout.robot_config
        homes = list(self.layout.spawn)
        if not homes:
            grid = self.layout.grid
            lane_y = grid.height - 3
            free = [x for x in range(grid.width) if grid.is_walkable(x, lane_y)]
            homes = [(free[(i * 3) % len(free)], lane_y) for i in range(cfg["count"])]
        for i, home in enumerate(homes[: cfg["count"]]):
            robot = Robot(f"R{i + 1}", home, speed=cfg["max_speed"])
            robot.battery = round(self.rng.uniform(75.0, 100.0), 1)
            self.robots[robot.robot_id] = robot
            self.controller.home[robot.robot_id] = home
        if not self.controller.parking:
            self.controller.parking = list(self.controller.home.values())

    # ----- control ---------------------------------------------------------------
    def start(self) -> None:
        self.running = True

    def pause(self) -> None:
        self.running = False

    def set_speed(self, multiplier: float) -> None:
        self.speed = max(0.1, min(multiplier, 50.0))

    def submit(self, command: Command) -> None:
        self._commands.append(command)

    def next_order_id(self) -> str:
        """Reserve an order id, so the API can answer with it before the next tick runs."""
        return self.generator.next_id()

    @property
    def sim_hour(self) -> int:
        """Hour of the simulated day (0-23); drives the demand profile."""
        return (self.time // self.config.get("ticks_per_hour", 3600)) % 24

    # ----- tick ------------------------------------------------------------------
    def tick(self) -> list[Event]:
        self._apply_commands()
        pending = sum(o.status == OrderStatus.PENDING for o in self.orders.values())
        order = self.generator.customer_order(self.time, self.sim_hour, self.inventory, pending)
        if order:
            self._add_order(order)
        self.hazards.step()
        self.dispatcher.step()
        self.faults.step()
        self.safety.step()
        self.controller.advance()
        update_temperatures(self)
        self.workers.step()
        self._update_resources()
        self.time += 1
        events = self.events.drain()
        self.safety.observe(events)
        return events

    def _apply_commands(self) -> None:
        for cmd in self._commands:
            args = cmd.args
            robot = self.robots.get(args.get("robot_id", ""))
            if cmd.name == "pause_robot" and robot:
                robot.status = RobotStatus.PAUSED
                self.events.emit(Event(self.time, EventType.ROBOT_PAUSED, robot.robot_id))
            elif cmd.name == "resume_robot" and robot and robot.status == RobotStatus.PAUSED:
                robot.status = self.controller.status_for(robot)
                self.events.emit(Event(self.time, EventType.ROBOT_RESUMED, robot.robot_id))
            elif cmd.name == "create_order":
                items = [
                    OrderItem(i["product_id"], int(i.get("quantity", 1)))
                    for i in args.get("items", [])
                ]
                priority = Priority(args.get("priority", "MEDIUM"))
                self._add_order(
                    self.generator.operator_order(
                        args["order_id"], self.time, priority, items, self.inventory
                    )
                )
                if args.get("robot_id"):
                    self.dispatcher.assign_manual(args["order_id"], args["robot_id"])
            elif cmd.name == "assign_order":
                self.dispatcher.assign_manual(args["order_id"], args["robot_id"])
            elif cmd.name == "set_assignment_mode":
                self.dispatcher.auto = bool(args["auto"])
            elif cmd.name == "close_aisle":  # operator closure: until reopened (or `ticks`)
                ticks = int(args.get("ticks", OPERATOR_CLOSURE_TICKS))
                self.hazards.close_aisle(
                    args["aisle_id"], args.get("reason", "operator request"), ticks
                )
            elif cmd.name == "open_aisle":
                self.hazards.reopen_aisle(args["aisle_id"])
            elif cmd.name == "reroute_robot" and robot:
                self.controller.reroute_avoiding(robot, self.cells_to_avoid(args))
        self._commands.clear()

    def cells_to_avoid(self, args: dict) -> set[tuple[int, int]]:
        """Cells of the aisles (and the aisles of the zone) an operator asked a robot to avoid."""
        avoid_aisles = set(args.get("avoid", []))
        zone = args.get("avoid_zone")
        cells: set[tuple[int, int]] = set()
        for aisle in self.layout.aisles:
            if aisle.aisle_id in avoid_aisles or (zone and aisle.zone_id == zone):
                cells |= set(aisle.cells)
        return cells

    def _add_order(self, order: Order) -> None:
        self.orders[order.order_id] = order
        self.inventory.order_created(order)  # WMS model: allocate the stock now
        payload = {"priority": order.priority.value, "source": order.source}
        self.events.emit(Event(self.time, EventType.ORDER_CREATED, order.order_id, payload))

    def _update_resources(self) -> None:
        self.congestion = zone_congestion(
            self.layout.zones, [r.position for r in self.robots.values()]
        )
        self.inventory.step(
            self.time,
            lambda pid, added: self.events.emit(
                Event(self.time, EventType.INVENTORY_RESTOCKED, pid, {"added": added})
            ),
        )
        for spec in self.inventory.take_new_orders():  # WMS: backorders whose stock arrived
            order = self.generator.operator_order(
                self.next_order_id(),
                self.time,
                Priority(spec["priority"]),
                [OrderItem(sku, qty) for sku, qty in spec["items"]],
                self.inventory,
            )
            order.source = "BACKORDER"
            self._add_order(order)
        finished = [
            k
            for k, o in self.orders.items()
            if o.status in (OrderStatus.DELIVERED, OrderStatus.LATE, OrderStatus.CANCELLED)
        ]
        for k in finished[:-KEEP_FINISHED_ORDERS]:
            del self.orders[k]

    # ----- state -----------------------------------------------------------------
    def state(self, include_inventory: bool = True) -> dict:
        """warehouse_state snapshot (TRD 4.2), the input to every AI component.

        The live stream leaves out the inventory (1,500+ products, ~65 % of the payload), which the
        3D view never uses; GET /simulation/state and /inventory still serve it.
        """
        state = {
            "time": self.time,
            "running": self.running,
            "assignment_mode": "auto" if self.dispatcher.auto else "manual",
            "robots": [
                {**r.to_dict(), **self.controller.activity(r)} for r in self.robots.values()
            ],
            "orders": [o.to_dict() for o in self.orders.values()],
            "obstacles": [
                {"position": list(o.position), "type": o.type, "obstacle_id": o.obstacle_id}
                for o in self.obstacles
            ],
            "closures": self.hazards.snapshot(),
            "stations": [vars(s) for s in self.layout.stations],
            "congestion": self.congestion,
            "safety": self.safety.snapshot(),
            "kpis": self.kpis.snapshot(),
            "clock": self.kpis.clock(),
        }
        if include_inventory:
            state["inventory"] = [
                {"product_id": p, "stock": s} for p, s in self.inventory.stock.items()
            ]
        return state

    def layout_snapshot(self) -> dict:
        """Static geometry for the 3D scene, sent once when a client connects."""
        lay = self.layout
        grid = lay.grid
        return {
            "name": lay.name,
            "width": grid.width,
            "height": grid.height,
            "zones": [vars(z) for z in lay.zones],
            "shelves": [vars(s) for s in lay.shelves],
            "stations": [vars(s) for s in lay.stations],
            "one_way": lay.one_way,
            "aisles": [
                {
                    "aisle_id": a.aisle_id,
                    "name": a.name,
                    "zone_id": a.zone_id,
                    "y": a.y,
                    "x_start": a.x_start,
                    "x_end": a.x_end,
                    "direction": a.direction,
                }
                for a in lay.aisles
            ],
            "parking_areas": [
                {"area_id": a.area_id, "name": a.name, "cells": [list(c) for c in a.cells]}
                for a in lay.parking_areas
            ],
            "blocked": [
                [x, y]
                for y in range(grid.height)
                for x in range(grid.width)
                if grid.get(x, y).value == "#"
            ],
        }

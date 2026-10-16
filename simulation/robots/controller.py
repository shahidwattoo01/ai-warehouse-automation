"""Robot behaviour: tasks, movement, traffic, charging and parking (TR-SIM-02, TR-SIM-04).

Every robot is either free (parked, or driving to parking) or busy with one Task:

    order:  TO_PICK -> PICKING -> (next rack ...) -> TO_PACK -> DROPPING -> park
    charge: TO_CHARGE -> CHARGING (until 95 %) -> park
    park:   TO_PARK -> free

Traffic: a robot moves one cell per tick if the next cell is free. Behind a robot that is
working (picking, dropping, charging) it waits its turn; otherwise it replans around nearby
robots after 2 blocked ticks and backs off to a random free cell after 4-7 (deadlock breaker).
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from simulation.environment.congestion import zone_of
from simulation.events.events import Event, EventType
from simulation.warehouse.entities import Order, OrderStatus, Robot, RobotStatus

if TYPE_CHECKING:
    from simulation.environment.engine import SimulationEngine

Cell = tuple[int, int]

WORKING_STAGES = ("PICKING", "DROPPING", "CHARGING")  # robot is parked doing work
STAGE_STATUS = {
    "PICKING": RobotStatus.PICKING,
    "TO_PACK": RobotStatus.DELIVERING,
    "DROPPING": RobotStatus.DELIVERING,
    "CHARGING": RobotStatus.CHARGING,
}
PATIENCE_BEHIND_WORKER = 20  # ticks to queue behind a working robot before trying another way
REPLAN_AFTER = 2  # blocked ticks before replanning around nearby robots
CHARGED = 95.0  # charging stops here
DROP_BAY_QUEUE_COST = 25  # metres a robot will detour to avoid one robot already heading to a bay
# Idle positioning: metres a robot will drive further to park in an emptier area (cost added per
# 100 % of an area's bays taken). Keeps idle robots spread around the building instead of all
# parking beside the packing stations. 0 = always the nearest free bay.
PARKING_BALANCE_COST = 150


def manhattan(a: Cell, b: Cell) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


@dataclass
class Task:
    kind: str  # order | charge | park
    stage: str
    dwell: int = 0  # ticks left at the current stop (picking, dropping)
    # order
    order_id: str | None = None
    stops: list[Cell] = field(default_factory=list)  # pick faces still to visit
    stop_names: list[str] = field(default_factory=list)  # rack locations of all picks
    drop: Cell | None = None  # packing bay
    # charge
    bay: Cell | None = None
    charger: str | None = None
    # park
    park: Cell | None = None
    # ETA dataset: features known at assignment, plus counters filled in on the way
    metrics: dict = field(default_factory=dict)

    @property
    def working(self) -> bool:
        return self.stage in WORKING_STAGES


class RobotController:
    def __init__(self, engine: SimulationEngine) -> None:
        self.engine = engine
        self.tasks: dict[str, Task] = {}  # robot_id -> current task
        self.home: dict[str, Cell] = {}  # spawn cell, fallback parking spot
        self.blocked: dict[str, int] = {}  # consecutive ticks a robot could not move
        self.goal: dict[str, Cell] = {}  # where each robot's current route ends
        self.recent_moves: dict[str, deque] = {}  # last 4 ticks: 1 if moved (live speed)

        layout = engine.layout
        self.parking: list[Cell] = list(layout.parking)  # every bay of every parking area
        self.parking_area: dict[Cell, str] = {  # bay -> "P3 · West"
            c: f"{a.area_id} · {a.name}" for a in layout.parking_areas for c in a.cells
        }
        self._area_of: dict[Cell, str] = {
            c: a.area_id for a in layout.parking_areas for c in a.cells
        }
        self._area_size: dict[str, int] = {a.area_id: len(a.cells) for a in layout.parking_areas}
        self.parking_balance = engine.config.get("parking", {}).get(
            "balance_cost", PARKING_BALANCE_COST
        )
        # Phase 4 hook: metres of cost removed for a bay (demand-aware positioning). None = off.
        self.park_bias = None
        # Each packing station has up to three drop bays along the front of its bench.
        self.drop_bays: dict[str, list[Cell]] = {
            s.station_id: [
                (s.x + dx, s.y) for dx in (-1, 0, 1) if layout.grid.is_walkable(s.x + dx, s.y)
            ]
            for s in layout.stations
            if s.type == "PACKING"
        }

    # ----- availability -------------------------------------------------------------
    def available(self, robot: Robot) -> bool:
        """Free for a new order: idle, or just driving to parking (re-taskable on the way)."""
        if robot.status in (RobotStatus.PAUSED, RobotStatus.FAULT):
            return False
        task = self.tasks.get(robot.robot_id)
        return task is None or task.kind == "park"

    def unavailable_reason(self, robot: Robot) -> str | None:
        """Why this robot cannot take a new order now (None = it can)."""
        if robot.status in (RobotStatus.PAUSED, RobotStatus.FAULT):
            return f"{robot.robot_id} is {robot.status.value.lower()}"
        if not self.available(robot):
            doing = (
                "charging" if self.tasks[robot.robot_id].kind == "charge" else "on another order"
            )
            return f"{robot.robot_id} is busy ({doing})"
        if robot.battery < self.engine.config["battery"]["low_threshold"]:
            return f"{robot.robot_id} battery too low ({robot.battery:.0f}%)"
        return None

    def status_for(self, robot: Robot) -> RobotStatus:
        task = self.tasks.get(robot.robot_id)
        if task is None:
            return RobotStatus.IDLE
        return STAGE_STATUS.get(task.stage, RobotStatus.MOVING)

    # ----- starting tasks --------------------------------------------------------------
    def start_order(self, order: Order, robot: Robot) -> None:
        """Give an order to a robot and send it to the first rack."""
        eng = self.engine
        stops = [eng.inventory.face[i.product_id] for i in order.items]
        packers = [s for s in eng.layout.stations if s.type == "PACKING"]
        station = min(packers, key=lambda s: manhattan((s.x, s.y), stops[-1]))
        legs = list(zip([robot.position, *stops], [*stops, (station.x, station.y)], strict=True))
        order.status = OrderStatus.ASSIGNED
        order.assigned_robot = robot.robot_id
        order.destination = station.station_id
        robot.current_task = order.order_id
        path = [robot.position, *stops, (station.x, station.y)]
        self.tasks[robot.robot_id] = Task(
            kind="order",
            stage="TO_PICK",
            order_id=order.order_id,
            stops=stops,
            stop_names=[eng.inventory.location(i.product_id) for i in order.items],
            drop=(station.x, station.y),
            metrics={
                "assigned_at": eng.time,
                "assigned_hour": eng.sim_hour,
                "start": robot.position,
                "battery_start": round(robot.battery, 2),
                "est_distance": sum(manhattan(a, b) for a, b in zip(path, path[1:], strict=False)),
                # Shortest legal route (one-way aisles, closures), ignoring other robots.
                "path_distance": sum(self._path_length(a, b) for a, b in legs),
                "robot_speed": eng.faults.speed_factor(robot.robot_id),
                "temperature_start": round(robot.temperature, 1),
                "closures_active": len(eng.hazards.closures),
                "floor_hazards_active": len(eng.hazards.floor),
                "zone_congestion": eng.congestion.get(
                    zone_of(eng.layout.zones, stops[0]) or "", 0.0
                ),
                "fleet_busy": sum(not self.available(r) for r in eng.robots.values()),
                "pending_orders": sum(o.status == OrderStatus.PENDING for o in eng.orders.values())
                + 1,
                "moves": 0,
                "waits": 0,
                "reroutes": 0,
            },
        )
        self._route(robot, stops[0])
        eng.events.emit(
            Event(
                eng.time,
                EventType.ORDER_ASSIGNED,
                order.order_id,
                {"robot_id": robot.robot_id, "manual": order.manual_assignment},
            )
        )

    def send_to_charger(self, robot: Robot, low: bool = True) -> bool:
        """Send a robot to the nearest free charger bay; `low` = battery-low (else a top-up)."""
        eng = self.engine
        taken = {t.bay for t in self.tasks.values() if t.bay}
        bays: list[tuple[Cell, str]] = []
        for st in (s for s in eng.layout.stations if s.type == "CHARGING"):
            half = st.capacity // 2
            for dy in range(-half, half + 1):
                cell = (st.x, st.y + dy)
                if eng.layout.grid.is_walkable(*cell) and cell not in taken:
                    bays.append((cell, st.station_id))
        if not bays:
            return False
        bay, charger = min(bays, key=lambda b: manhattan(b[0], robot.position))
        self.tasks[robot.robot_id] = Task(
            kind="charge", stage="TO_CHARGE", bay=bay, charger=charger
        )
        self._route(robot, bay)
        if low:
            eng.events.emit(
                Event(
                    eng.time,
                    EventType.BATTERY_LOW,
                    robot.robot_id,
                    {"battery": round(robot.battery, 1)},
                )
            )
        return True

    def park(self, robot: Robot) -> None:
        """Drive to a free parking bay: nearby, but preferring areas that are less full."""
        robots = self.engine.robots.values()
        parked = {
            r.position
            for r in robots
            if r.robot_id != robot.robot_id and r.robot_id not in self.tasks
        }
        reserved = {t.park for rid, t in self.tasks.items() if rid != robot.robot_id and t.park}
        free = [c for c in self.parking if c not in parked and c not in reserved] or [
            self.home[robot.robot_id]
        ]
        taken: dict[str, int] = {}  # bays occupied or reserved per area
        for cell in parked | reserved:
            if cell in self._area_of:
                taken[self._area_of[cell]] = taken.get(self._area_of[cell], 0) + 1

        def cost(bay: Cell) -> float:
            area = self._area_of.get(bay)
            fullness = taken.get(area, 0) / self._area_size[area] if area else 0.0
            bias = self.park_bias(bay) if self.park_bias else 0.0
            return manhattan(bay, robot.position) + self.parking_balance * fullness - bias

        spot = min(free, key=cost)
        self.tasks[robot.robot_id] = Task(kind="park", stage="TO_PARK", park=spot)
        self._route(robot, spot)
        if not robot.route:
            self.tasks.pop(robot.robot_id)
            robot.status = RobotStatus.IDLE

    # ----- per-tick movement ---------------------------------------------------------
    def advance(self) -> None:
        """Move every robot one step: work at its stop, drive, or wait in traffic."""
        eng = self.engine
        drain = eng.config["battery"]["drain_per_move"]
        before = {rid: r.position for rid, r in eng.robots.items()}
        robot_at = {r.position: r.robot_id for r in eng.robots.values()}  # updated as robots move
        obstacle_cells = {o.position for o in eng.obstacles}

        for robot in eng.robots.values():
            if robot.status in (RobotStatus.PAUSED, RobotStatus.FAULT):
                continue
            rid = robot.robot_id
            task = self.tasks.get(rid)
            if task and task.working:
                self._work(robot, task)
                continue
            if not robot.route:
                if task and robot.position != self.goal.get(rid, robot.position):
                    self._route(robot, self.goal[rid])  # no path last time: retry
                elif task:
                    self._arrive(robot, task)
                continue
            if eng.faults.slowed(rid):
                continue

            nxt = robot.route[0]
            if nxt in robot_at or nxt in obstacle_cells:
                self._wait_in_traffic(robot, task, nxt, robot_at, obstacle_cells)
                continue

            self.blocked[rid] = 0
            if task and task.kind == "order":
                task.metrics["moves"] += 1
            robot.route.pop(0)
            self._face(robot, nxt)
            del robot_at[robot.position]
            robot_at[nxt] = rid
            robot.position = nxt
            robot.battery = max(0.0, robot.battery - drain)
            eng.events.emit(Event(eng.time, EventType.ROBOT_MOVED, rid, {"to": list(nxt)}))
            if not robot.route and task:
                self._arrive(robot, task)

        for rid, robot in eng.robots.items():
            self.recent_moves.setdefault(rid, deque(maxlen=4)).append(
                int(robot.position != before[rid])
            )

    def _wait_in_traffic(
        self,
        robot: Robot,
        task: Task | None,
        nxt: Cell,
        robot_at: dict[Cell, str],
        obstacle_cells: set[Cell],
    ) -> None:
        eng = self.engine
        rid = robot.robot_id
        waited = self.blocked[rid] = self.blocked.get(rid, 0) + 1
        if task and task.kind == "order":
            task.metrics["waits"] += 1
        ahead = self.tasks.get(robot_at.get(nxt, ""))
        if ahead and ahead.working and waited < PATIENCE_BEHIND_WORKER:
            return  # the robot ahead is picking/dropping/charging: queue behind it
        occupied = (robot_at.keys() - {robot.position}) | obstacle_cells
        if waited == REPLAN_AFTER:
            # Replan around every robot/worker nearby, not just the one in front.
            near = {c for c in occupied if manhattan(c, robot.position) <= 4}
            self._route(robot, robot.route[-1], avoid=near)
            if task and task.kind == "order":
                task.metrics["reroutes"] += 1
            eng.events.emit(Event(eng.time, EventType.ROUTE_CHANGED, rid))
        elif waited >= 4 + eng.rng.randint(0, 3):
            old = robot.position
            self._back_off(robot, occupied)
            if robot.position != old:
                del robot_at[old]
                robot_at[robot.position] = rid

    def _back_off(self, robot: Robot, occupied: set[Cell]) -> None:
        """Deadlock breaker: step into a random free neighbour cell, then replan from there."""
        eng = self.engine
        self.blocked[robot.robot_id] = 0
        goal = robot.route[-1] if robot.route else robot.position
        free = [c for c in eng.layout.grid.neighbors(*robot.position) if c not in occupied]
        if not free:
            return
        step = eng.rng.choice(free)
        self._face(robot, step)
        robot.position = step
        self._route(robot, goal)
        eng.events.emit(
            Event(eng.time, EventType.ROBOT_BLOCKED, robot.robot_id, {"yielded_to": list(step)})
        )

    def detour(self, robot: Robot) -> None:
        """Route-deviation fault: wander to a random nearby cell before resuming the route."""
        if not robot.route:
            return
        eng = self.engine
        grid = eng.layout.grid
        goal = robot.route[-1]
        x, y = robot.position
        options = [
            (x + dx, y + dy)
            for dx in range(-4, 5)
            for dy in range(-4, 5)
            if (dx or dy) and grid.is_walkable(x + dx, y + dy)
        ]
        if not options:
            return
        via = eng.rng.choice(options)
        first = eng.planner.plan(grid, robot.position, via)
        second = eng.planner.plan(grid, via, goal)
        if first and second:
            robot.route = first + second

    # ----- task stages ---------------------------------------------------------------
    def _arrive(self, robot: Robot, task: Task) -> None:
        """End of route reached: advance the task to its next stage."""
        cfg = self.engine.config["orders"]
        if task.stage == "TO_PICK":
            task.stage, task.dwell = "PICKING", cfg.get("pick_ticks", 4)
            self.engine.orders[task.order_id].status = OrderStatus.IN_PROGRESS
        elif task.stage == "TO_PACK":
            task.stage, task.dwell = "DROPPING", cfg.get("drop_ticks", 3)
        elif task.stage == "TO_CHARGE":
            task.stage = "CHARGING"
        elif task.stage == "TO_PARK":
            self.tasks.pop(robot.robot_id)
        robot.status = self.status_for(robot)

    def _work(self, robot: Robot, task: Task) -> None:
        """One tick of work at a stop: charging, picking or dropping."""
        eng = self.engine
        if task.stage == "CHARGING":
            robot.battery = min(100.0, robot.battery + eng.config["battery"]["charge_per_tick"] * 4)
            if robot.battery >= CHARGED:
                self.park(robot)
            return
        task.dwell -= 1
        if task.dwell > 0:
            return
        order = eng.orders[task.order_id]
        if task.stage == "PICKING":
            self._finish_pick(robot, task, order)
        else:
            self._finish_drop(robot, task, order)

    def _finish_pick(self, robot: Robot, task: Task, order: Order) -> None:
        eng = self.engine
        item = order.items[len(order.items) - len(task.stops)]
        eng.inventory.take(item.product_id, item.quantity)
        robot.load += 1
        robot.battery = max(0.0, robot.battery - eng.config["battery"]["drain_per_item"])
        eng.events.emit(
            Event(eng.time, EventType.ITEM_PICKED, robot.robot_id, {"product_id": item.product_id})
        )
        task.stops.pop(0)
        if task.stops:
            task.stage = "TO_PICK"
            self._route(robot, task.stops[0])
        else:
            task.stage = "TO_PACK"
            order.destination, task.drop = self._least_busy_drop_bay(robot)
            self._route(robot, task.drop)

    def _finish_drop(self, robot: Robot, task: Task, order: Order) -> None:
        eng = self.engine
        order.status = OrderStatus.DELIVERED if eng.time <= order.deadline else OrderStatus.LATE
        order.delivered_at = eng.time
        robot.load = 0
        robot.current_task = None
        m = task.metrics
        payload = {  # one row of the ETA training table (simulation/environment/recorder.py)
            "robot_id": robot.robot_id,
            "priority": order.priority.value,
            "n_items": len(order.items),
            "n_units": sum(i.quantity for i in order.items),
            "order_time": order.order_time,
            "assigned_at": m["assigned_at"],
            "sim_hour": m["assigned_hour"],
            "delivered_at": eng.time,
            "queue_ticks": m["assigned_at"] - order.order_time,
            "duration_ticks": eng.time - m["assigned_at"],
            "late": order.status == OrderStatus.LATE,
            "start_x": m["start"][0],
            "start_y": m["start"][1],
            "station": order.destination,
            "battery_start": m["battery_start"],
            "est_distance": m["est_distance"],
            "path_distance": m["path_distance"],
            "robot_speed": m["robot_speed"],
            "temperature_start": m["temperature_start"],
            "closures_active": m["closures_active"],
            "floor_hazards_active": m["floor_hazards_active"],
            "zone_congestion": m["zone_congestion"],
            "fleet_busy": m["fleet_busy"],
            "pending_orders": m["pending_orders"],
            "moves": m["moves"],
            "waits": m["waits"],
            "reroutes": m["reroutes"],
        }
        eng.events.emit(Event(eng.time, EventType.ORDER_DELIVERED, order.order_id, payload))
        self.park(robot)

    # ----- helpers -------------------------------------------------------------------
    def _least_busy_drop_bay(self, robot: Robot) -> tuple[str, Cell]:
        """Nearest packing bay, penalised by robots already heading to it."""
        load: dict[Cell, int] = {}
        for rid, t in self.tasks.items():
            if rid != robot.robot_id and t.kind == "order" and t.stage in ("TO_PACK", "DROPPING"):
                load[t.drop] = load.get(t.drop, 0) + 1
        return min(
            ((sid, bay) for sid, bays in self.drop_bays.items() for bay in bays),
            key=lambda sb: (
                manhattan(robot.position, sb[1]) + DROP_BAY_QUEUE_COST * load.get(sb[1], 0)
            ),
        )

    def reroute(self, robot: Robot) -> None:
        """Plan the current route again (cells on it were just closed)."""
        if robot.route:
            self._route(robot, self.goal.get(robot.robot_id, robot.route[-1]))
            eng = self.engine
            eng.events.emit(Event(eng.time, EventType.ROUTE_CHANGED, robot.robot_id))

    def _path_length(self, a: Cell, b: Cell) -> int:
        """Metres along the shortest legal route; Manhattan distance if none exists now."""
        if a == b:
            return 0
        d = self.engine.distances.distance(a, b)
        return d if d > 0 else manhattan(a, b)

    def _route(self, robot: Robot, goal: Cell, avoid: set[Cell] | None = None) -> None:
        eng = self.engine
        grid = eng.layout.grid
        self.goal[robot.robot_id] = goal
        if robot.position == goal:
            robot.route = []
        else:
            robot.route = eng.planner.plan(
                grid, robot.position, goal, avoid, rng=eng.rng
            ) or eng.planner.plan(grid, robot.position, goal, rng=eng.rng)
        robot.status = self.status_for(robot)

    @staticmethod
    def _face(robot: Robot, cell: Cell) -> None:
        dx, dy = cell[0] - robot.position[0], cell[1] - robot.position[1]
        robot.heading = math.atan2(-dy, dx)  # three.js rotation.y for a model facing +X

    # ----- reporting -----------------------------------------------------------------
    def activity(self, robot: Robot) -> dict:
        """Where the robot is heading and why, plus its recent speed (cells per tick)."""
        task = self.tasks.get(robot.robot_id)
        moves = self.recent_moves.get(robot.robot_id)
        # Parked, or driving to a bay: name the parking area when there is one.
        bay = task.park if task and task.park else robot.position
        area = self.parking_area.get(bay)
        info: dict = {
            "speed_cells_per_tick": round(sum(moves) / len(moves), 2) if moves else 0.0,
            "destination": f"Parking {area}" if area else "Parking",
            "destination_type": "PARKING",
            "order_priority": None,
            "items_left": 0,
        }
        if task is None:
            return info
        if task.kind == "order":
            order = self.engine.orders.get(task.order_id)
            info["order_priority"] = order.priority.value if order else None
            info["items_left"] = len(task.stops)
            if task.stage in ("TO_PICK", "PICKING"):
                info["destination"] = (
                    f"Rack {task.stop_names[len(task.stop_names) - len(task.stops)]}"
                )
                info["destination_type"] = "SHELF"
            else:
                info["destination"] = (order.destination if order else None) or "Packing"
                info["destination_type"] = "PACKING"
        elif task.kind == "charge":
            info["destination"] = task.charger or "Charger"
            info["destination_type"] = "CHARGER"
        return info

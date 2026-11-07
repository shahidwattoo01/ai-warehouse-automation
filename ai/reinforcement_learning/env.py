"""Gymnasium environment wrapping the warehouse simulator (PR-05 / Phase 9).

Observation space (per robot)
------------------------------
- 7 × 7 local occupancy grid centred on the robot (0 = free, 1 = robot, 2 = wall/rack)
- 4-dim route direction one-hot (N/E/S/W) toward the next waypoint
- battery level (0–1)
- tote load fraction (0–1, load / tote_capacity)
- 3 deadline urgency bins for the robot's current orders (high / medium / low; binary)
Total: 49 + 4 + 1 + 1 + 3 = 58 floats per agent.

Action space (per robot): Discrete(5) — UP / DOWN / LEFT / RIGHT / WAIT

Reward (per tick per robot)
----------------------------
+10   order delivered (all orders in tote)
+2    item picked
-0.1  per tick alive (time pressure)
-5    collision (attempted move onto occupied cell)
-1    wait (WAIT action when not in traffic)
+0.5  per cell of progress toward next pick/drop (Manhattan delta)

Episode: one simulated hour (ticks_per_hour ticks) or until all robots are idle.
"""

from __future__ import annotations

import copy
from typing import Any

import numpy as np

OBS_DIM = 58
N_ACTIONS = 5  # UP DOWN LEFT RIGHT WAIT
DIRECTIONS = [(0, -1), (0, 1), (1, 0), (-1, 0)]  # UP DOWN RIGHT LEFT
ACTION_DELTA = {0: (0, -1), 1: (0, 1), 2: (1, 0), 3: (-1, 0), 4: (0, 0)}

# Reward table (TRD 8.9)
R_DELIVER = 10.0
R_PICK = 2.0
R_TICK = -0.1
R_COLLISION = -5.0
R_IDLE_WAIT = -1.0
R_PROGRESS = 0.5


def _obs_for_robot(engine, robot_id: str, tote_capacity: int = 3) -> np.ndarray:
    """Build the 58-dim observation vector for one robot."""
    from simulation.warehouse.entities import RobotStatus

    eng = engine
    robot = eng.robots[robot_id]
    grid = eng.layout.grid
    task = eng.controller.tasks.get(robot_id)

    # 7x7 local occupancy (flattened, 49 dims)
    rx, ry = robot.position
    occupied_cells = {r.position for r in eng.robots.values()}
    local = np.zeros(49, dtype=np.float32)
    idx = 0
    for dy in range(-3, 4):
        for dx in range(-3, 4):
            cx, cy = rx + dx, ry + dy
            if not grid.is_walkable(cx, cy):
                local[idx] = 2.0
            elif (cx, cy) in occupied_cells and (cx, cy) != robot.position:
                local[idx] = 1.0
            idx += 1

    # Route direction one-hot (4 dims)
    direction = np.zeros(4, dtype=np.float32)
    if robot.route:
        nxt = robot.route[0]
        dx, dy = nxt[0] - rx, nxt[1] - ry
        for i, (ddx, ddy) in enumerate(DIRECTIONS):
            if (ddx, ddy) == (dx, dy):
                direction[i] = 1.0
                break

    # Battery (1 dim)
    battery = np.array([robot.battery / 100.0], dtype=np.float32)

    # Tote load fraction (1 dim)
    load = np.array([min(robot.load / max(tote_capacity, 1), 1.0)], dtype=np.float32)

    # Deadline urgency (3 dims: HIGH/MEDIUM/LOW flags)
    urgency = np.zeros(3, dtype=np.float32)
    if task and task.order_ids:
        for oid in task.order_ids:
            order = eng.orders.get(oid)
            if order:
                from simulation.warehouse.entities import Priority
                if order.priority == Priority.HIGH:
                    urgency[0] = 1.0
                elif order.priority == Priority.MEDIUM:
                    urgency[1] = 1.0
                else:
                    urgency[2] = 1.0

    return np.concatenate([local, direction, battery, load, urgency])


class WarehouseEnv:
    """Multi-robot Gymnasium-style environment over the simulator.

    Supports both single-agent (one robot_id) and shared-policy multi-agent (all robots)
    modes.  The shared-policy MARL trainer uses the multi-agent interface.

    Single-agent interface  (robot_id set at construction)
    -------------------------------------------------------
    obs, info = env.reset()
    obs, reward, terminated, truncated, info = env.step(action)

    Multi-agent interface  (robot_id = None → all robots)
    -------------------------------------------------------
    obs_dict  = env.reset_multi()          # {robot_id: obs_array}
    results   = env.step_multi(action_dict) # {robot_id: (obs, reward, done)}
    """

    metadata: dict = {"render_modes": []}

    def __init__(
        self,
        engine_factory,
        robot_id: str | None = None,
        episode_ticks: int | None = None,
        tote_capacity: int = 3,
        seed: int = 42,
    ) -> None:
        self._factory = engine_factory
        self._robot_id = robot_id
        self._episode_ticks = episode_ticks
        self._tote_capacity = tote_capacity
        self._seed = seed
        self.engine = None
        self._start_tick = 0
        self._prev_dist: dict[str, int] = {}

    # ----- Gymnasium API (single agent) ------------------------------------------

    def reset(self, seed: int | None = None, options: dict | None = None):
        self.engine = self._factory(seed or self._seed)
        self.engine.start()
        self._start_tick = self.engine.time
        rid = self._robot_id or next(iter(self.engine.robots))
        self._prev_dist[rid] = self._dist_to_goal(rid)
        obs = _obs_for_robot(self.engine, rid, self._tote_capacity)
        return obs, {"robot_id": rid}

    def step(self, action: int):
        eng = self.engine
        rid = self._robot_id or next(iter(eng.robots))
        robot = eng.robots[rid]

        reward = R_TICK
        terminated = False

        if action == 4:  # WAIT
            task = eng.controller.tasks.get(rid)
            if task and task.kind == "order":
                reward += 0
            else:
                reward += R_IDLE_WAIT
        else:
            dx, dy = ACTION_DELTA[action]
            nx, ny = robot.position[0] + dx, robot.position[1] + dy
            if not eng.layout.grid.is_walkable(nx, ny) or any(
                r.position == (nx, ny) for r in eng.robots.values() if r.robot_id != rid
            ):
                reward += R_COLLISION
            else:
                robot.route = [(nx, ny)] + robot.route[1:]

        events = eng.tick()
        for ev in events:
            if ev.entity_id == rid:
                from simulation.events.events import EventType
                if ev.type == EventType.ITEM_PICKED:
                    reward += R_PICK
                elif ev.type == EventType.ORDER_DELIVERED:
                    reward += R_DELIVER
            elif ev.entity_id in (eng.controller.tasks.get(rid) or type("", (), {"order_ids": []})()).order_ids:
                from simulation.events.events import EventType
                if ev.type == EventType.ORDER_DELIVERED:
                    reward += R_DELIVER

        # Progress shaping
        new_dist = self._dist_to_goal(rid)
        prev = self._prev_dist.get(rid, new_dist)
        reward += R_PROGRESS * max(0, prev - new_dist)
        self._prev_dist[rid] = new_dist

        episode_ticks = self._episode_ticks or eng.config.get("ticks_per_hour", 600)
        truncated = eng.time - self._start_tick >= episode_ticks
        obs = _obs_for_robot(eng, rid, self._tote_capacity)
        return obs, reward, terminated, truncated, {"tick": eng.time}

    # ----- Multi-agent interface --------------------------------------------------

    def reset_multi(self, seed: int | None = None) -> dict[str, np.ndarray]:
        self.engine = self._factory(seed or self._seed)
        self.engine.start()
        self._start_tick = self.engine.time
        result = {}
        for rid in self.engine.robots:
            self._prev_dist[rid] = self._dist_to_goal(rid)
            result[rid] = _obs_for_robot(self.engine, rid, self._tote_capacity)
        return result

    def step_multi(
        self, action_dict: dict[str, int]
    ) -> dict[str, tuple[np.ndarray, float, bool]]:
        """Apply actions for all robots, run one tick, return (obs, reward, done) per robot."""
        eng = self.engine
        episode_ticks = self._episode_ticks or eng.config.get("ticks_per_hour", 600)
        truncated = eng.time - self._start_tick >= episode_ticks

        # Apply RL actions (override route head for non-WAIT actions)
        for rid, action in action_dict.items():
            if action == 4:
                continue
            robot = eng.robots.get(rid)
            if robot is None or robot.route:
                continue  # let the existing route run; RL only acts when robot is free
            dx, dy = ACTION_DELTA[action]
            nx, ny = robot.position[0] + dx, robot.position[1] + dy
            if eng.layout.grid.is_walkable(nx, ny):
                robot.route = [(nx, ny)]

        events = eng.tick()

        per_robot_rewards: dict[str, float] = {rid: R_TICK for rid in eng.robots}
        for ev in events:
            from simulation.events.events import EventType
            if ev.entity_id and ev.type == EventType.ITEM_PICKED:
                per_robot_rewards[ev.entity_id] = per_robot_rewards.get(ev.entity_id, 0) + R_PICK
            elif ev.type == EventType.ORDER_DELIVERED:
                rid_match = next(
                    (rid for rid, t in eng.controller.tasks.items()
                     if t.order_id == ev.entity_id or ev.entity_id in t.order_ids),
                    ev.entity_id,
                )
                per_robot_rewards[rid_match] = per_robot_rewards.get(rid_match, 0) + R_DELIVER

        result = {}
        for rid in eng.robots:
            new_dist = self._dist_to_goal(rid)
            prev = self._prev_dist.get(rid, new_dist)
            reward = per_robot_rewards.get(rid, R_TICK)
            reward += R_PROGRESS * max(0, prev - new_dist)
            self._prev_dist[rid] = new_dist
            obs = _obs_for_robot(eng, rid, self._tote_capacity)
            result[rid] = (obs, reward, truncated)
        return result

    # ----- helpers ---------------------------------------------------------------

    def _dist_to_goal(self, robot_id: str) -> int:
        eng = self.engine
        robot = eng.robots.get(robot_id)
        if robot is None:
            return 0
        task = eng.controller.tasks.get(robot_id)
        if task and task.stops:
            goal = task.stops[0]
        elif task and task.drop:
            goal = task.drop
        else:
            return 0
        return abs(robot.position[0] - goal[0]) + abs(robot.position[1] - goal[1])

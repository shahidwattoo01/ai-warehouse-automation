"""Tool registry for the agents (Phase 8; docs/phase8_agents.md).

The 15 tools of data/processed/agents/tools.json: each has a JSON schema for its arguments, a
read/write flag and whether it needs a person's approval. Every call is validated against the
schema and against the live warehouse (does the robot / order / aisle exist?) before it runs.
Results are structured data (what an LLM or a planner reads), not prose.

Write tools never act directly: they become simulator commands, applied at the start of the next
tick, exactly as an operator's button would. `close_aisle` is safe by construction: if robots or
picks are still in the aisle it is scheduled and closes the moment the aisle is clear.
"""

from __future__ import annotations

import json
from collections import defaultdict, deque
from dataclasses import asdict, is_dataclass
from pathlib import Path

import jsonschema

from simulation.environment.engine import Command
from simulation.events.events import Event, EventType

ROOT = Path(__file__).resolve().parents[2]
TOOLS_FILE = ROOT / "data" / "processed" / "agents" / "tools.json"
TICK_SECONDS = 0.5


class ToolError(ValueError):
    """A call the registry refuses: unknown tool, bad arguments, or an entity that is not there."""


ROUTINE = {"ROUTE_CHANGED", "ROBOT_BLOCKED", "ITEM_PICKED"}  # counted, a few shown


class EventLog:
    """Recent events per entity (robot, order, aisle), for `get_events`."""

    def __init__(self, engine, keep: int = 400) -> None:
        self.by_entity: dict[str, deque] = defaultdict(lambda: deque(maxlen=keep))
        engine.events.subscribe(self._on_event, external=True)

    def _on_event(self, e: Event) -> None:
        if e.type == EventType.ROBOT_MOVED:  # every tick for every robot: it would bury the rest
            return
        self.by_entity[e.entity_id].append(e)
        for key in ("robot_id", "order_id"):
            other = (e.payload or {}).get(key)
            if other and other != e.entity_id:
                self.by_entity[other].append(e)


def load_specs(path: Path = TOOLS_FILE) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else data["tools"]


class ToolRegistry:
    def __init__(self, specs: list[dict] | None = None) -> None:
        self.specs = {s["name"]: s for s in (specs or load_specs())}

    def schema(self) -> list[dict]:
        """For the API and for an LLM's tool list."""
        return [
            {
                "name": s["name"],
                "description": s["description"],
                "parameters": s["parameters"],
                "is_write": s["is_write"],
                "requires_approval": s["requires_approval"],
            }
            for s in self.specs.values()
        ]

    def is_write(self, name: str) -> bool:
        return self.specs[name]["is_write"]

    def needs_approval(self, name: str) -> bool:
        return self.specs[name]["requires_approval"]

    # ----- validation ------------------------------------------------------------------------
    def validate(self, engine, name: str, args: dict) -> None:
        spec = self.specs.get(name)
        if spec is None:
            raise ToolError(f"unknown tool {name}")
        try:
            jsonschema.validate(args, spec["parameters"])
        except jsonschema.ValidationError as err:
            raise ToolError(f"{name}: {err.message}") from err
        if "robot_id" in args and args["robot_id"] not in engine.robots:
            raise ToolError(f"there is no robot {args['robot_id']}")
        if "order_id" in args and args["order_id"] not in engine.orders:
            raise ToolError(f"there is no order {args['order_id']}")
        aisles = {a.aisle_id for a in engine.layout.aisles}
        for aisle in [args.get("aisle_id"), *args.get("avoid", [])]:
            if aisle and aisle not in aisles:
                raise ToolError(f"there is no {aisle}")
        if "product_id" in args and args["product_id"] not in engine.inventory:
            raise ToolError(f"there is no product {args['product_id']}")

    # ----- running ---------------------------------------------------------------------------
    def run(self, ctx: dict, name: str, args: dict) -> dict:
        """Validate and run one call. `ctx`: engine, events (EventLog), knowledge (callable),
        pending_closures (dict, shared across calls)."""
        eng = ctx["engine"]
        self.validate(eng, name, args)
        return getattr(self, f"_{name}")(ctx, eng, args)

    # reads ------------------------------------------------------------------------------------
    def _get_robot_status(self, ctx, eng, a) -> dict:
        r = eng.robots[a["robot_id"]]
        fault = eng.faults.active.get(r.robot_id) if hasattr(eng.faults, "active") else None
        if fault is not None and is_dataclass(fault):
            fault = asdict(fault)
        task = eng.controller.tasks.get(r.robot_id)
        order = eng.orders.get(getattr(task, "order_id", None)) if task else None
        carrying = None
        if order is not None:
            carrying = {
                "order_id": order.order_id,
                "priority": order.priority.value,
                "deadline_ticks_left": order.deadline - eng.time,
                "items_left": len(task.stops),
                "items": len(order.items),
            }
        return {
            **r.to_dict(),
            **eng.controller.activity(r),
            "available": eng.controller.available(r),
            "unavailable_reason": eng.controller.unavailable_reason(r),
            "fault": fault,
            "order_id": getattr(task, "order_id", None) if task else None,
            "throttled": r.temperature >= 60.0,
            "order": carrying,
        }

    def _get_pending_orders(self, ctx, eng, a) -> dict:
        pending = [
            o
            for o in eng.orders.values()
            if o.status.value == "PENDING"
            and o.priority.value == a.get("priority", o.priority.value)
        ]
        pending.sort(key=lambda o: (o.priority.value != "HIGH", o.order_time))
        free = [rid for rid, r in eng.robots.items() if eng.controller.available(r)]
        return {
            "count": len(pending),
            "orders": [
                {
                    "order_id": o.order_id,
                    "priority": o.priority.value,
                    "waiting_ticks": eng.time - o.order_time,
                    "deadline_ticks_left": o.deadline - eng.time,
                }
                for o in pending[:15]
            ],
            "free_robots": free,
            "assignment_mode": "auto" if eng.dispatcher.auto else "manual",
        }

    def _get_inventory(self, ctx, eng, a) -> dict:
        pid = a["product_id"]
        return {
            "product_id": pid,
            "stock": eng.inventory.stock_of(pid),
            "restocking": eng.inventory.restocking(pid),
        }

    def _get_warehouse_state(self, ctx, eng, a) -> dict:
        by_status: dict[str, int] = {}
        for r in eng.robots.values():
            by_status[r.status.value] = by_status.get(r.status.value, 0) + 1
        k = eng.kpis.snapshot()
        closures = ctx.setdefault("pending_closures", {})
        aisles_in_use = {}
        for aisle in eng.layout.aisles:
            blockers = eng.hazards.blockers(aisle.aisle_id)
            if blockers:
                aisles_in_use[aisle.aisle_id] = blockers
        return {
            "tick": eng.time,
            "robots": by_status,
            "pending_orders": sum(o.status.value == "PENDING" for o in eng.orders.values()),
            "kpis": k,
            "closed_aisles": sorted(eng.hazards.closures),
            "scheduled_closures": sorted(closures),
            "aisles_in_use": aisles_in_use,
            "assignment_mode": "auto" if eng.dispatcher.auto else "manual",
        }

    def _get_events(self, ctx, eng, a) -> dict:
        since = a.get("since_tick", 0)
        events = [e for e in ctx["events"].by_entity.get(a["entity_id"], []) if e.tick >= since]
        counts: dict[str, int] = {}
        for e in events:
            counts[e.type.value] = counts.get(e.type.value, 0) + 1
        notable = [e for e in events if e.type.value not in ROUTINE]
        events = [e for e in events if e.type.value in ROUTINE][-10:] + notable[-20:]
        events.sort(key=lambda e: e.tick)
        return {
            "counts": counts,
            "entity_id": a["entity_id"],
            "events": [
                {"tick": e.tick, "type": e.type.value, **(e.payload or {})} for e in events[-15:]
            ],
        }

    def _calculate_route(self, ctx, eng, a) -> dict:
        robot = eng.robots[a["robot_id"]]
        goal = _place(eng, a.get("destination"))
        if goal is None:
            raise ToolError(f"unknown destination {a.get('destination')}")
        path = eng.planner.plan(
            eng.layout.grid,
            robot.position,
            goal,
            eng.cells_to_avoid(a) or None,
            rng=ctx.setdefault("rng", _rng()),
        )
        if not path:
            return {"reachable": False}
        return {"reachable": True, "metres": len(path), "seconds": len(path) * TICK_SECONDS}

    def _search_knowledge(self, ctx, eng, a) -> dict:
        ask = ctx.get("knowledge")
        if ask is None:
            return {"answer": None, "sources": [], "note": "knowledge base not available"}
        result = ask(a["query"])
        sources = [f"{s['doc_id']}#{s['section_id']}" for s in result.get("sources", [])[:3]]
        return {
            "answer": result.get("answer"),
            "covered": result.get("covered"),
            "sources": sources,
        }

    # writes -----------------------------------------------------------------------------------
    def _submit(self, eng, name: str, args: dict) -> dict:
        eng.submit(Command(name, args))
        return {"status": "queued", "applies_at_tick": eng.time + 1}

    def _assign_order(self, ctx, eng, a) -> dict:
        robot = eng.robots[a["robot_id"]]
        if not eng.controller.available(robot):
            reason = eng.controller.unavailable_reason(robot)
            raise ToolError(f"{robot.robot_id} cannot take an order: {reason}")
        order = eng.orders[a["order_id"]]
        holder = eng.robots.get(order.assigned_robot) if order.assigned_robot else None
        stopped = holder is not None and holder.status.value in ("PAUSED", "FAULT")
        if order.status.value != "PENDING" and not stopped:  # a stopped robot's: SOP-03 step 3
            raise ToolError(f"{a['order_id']} is not waiting for a robot")
        return self._submit(eng, "assign_order", a)

    def _reroute_robot(self, ctx, eng, a) -> dict:
        return self._submit(eng, "reroute_robot", a)

    def _pause_robot(self, ctx, eng, a) -> dict:
        return self._submit(eng, "pause_robot", {"robot_id": a["robot_id"]})

    def _resume_robot(self, ctx, eng, a) -> dict:
        return self._submit(eng, "resume_robot", {"robot_id": a["robot_id"]})

    def _close_aisle(self, ctx, eng, a) -> dict:
        reason = a.get("reason", "operator request")
        blockers = eng.hazards.blockers(a["aisle_id"])
        if blockers:  # never trap a robot: close as soon as it is clear
            ctx.setdefault("pending_closures", {})[a["aisle_id"]] = reason
            return {"status": "scheduled", "closes_when_clear": True, "blockers": blockers}
        return self._submit(eng, "close_aisle", {"aisle_id": a["aisle_id"], "reason": reason})

    def _open_aisle(self, ctx, eng, a) -> dict:
        ctx.setdefault("pending_closures", {}).pop(a["aisle_id"], None)
        return self._submit(eng, "open_aisle", a)

    def _set_assignment_mode(self, ctx, eng, a) -> dict:
        return self._submit(eng, "set_assignment_mode", {"auto": a["mode"] == "auto"})

    def _create_order(self, ctx, eng, a) -> dict:
        order_id = eng.next_order_id()
        self._submit(
            eng,
            "create_order",
            {
                "order_id": order_id,
                "priority": a.get("priority", "MEDIUM"),
                "items": a["items"],
                "robot_id": None,
            },
        )
        return {"status": "queued", "order_id": order_id}


def close_scheduled_aisles(ctx: dict) -> list[str]:
    """Call every tick: scheduled closures happen as soon as their aisle is clear."""
    eng, closed = ctx["engine"], []
    for aisle_id, reason in list(ctx.get("pending_closures", {}).items()):
        if not eng.hazards.blockers(aisle_id):
            eng.submit(Command("close_aisle", {"aisle_id": aisle_id, "reason": reason}))
            del ctx["pending_closures"][aisle_id]
            closed.append(aisle_id)
    return closed


def _place(eng, name: str | None):
    if not name:
        return None
    for s in eng.layout.stations:
        if s.station_id == name:
            return (s.x, s.y)
    for area in eng.layout.parking_areas:
        if area.area_id == name and area.cells:
            return area.cells[0]
    return eng.inventory.face.get(f"P-{name}") or eng.inventory.face.get(name)


def _rng():
    import random

    return random.Random(0)  # route questions never touch the simulation's own random sequence

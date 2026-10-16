"""Agent evaluation scenarios (Phases 8-9): real operational situations found in the simulator.

    python scripts/generate_agent_scenarios.py

The script runs the simulator with several seeds and stops at moments an operator would ask the
copilot for help: a stopped robot, an overheating robot, a robot blocked in traffic, an aisle to
close while a robot is still in it, a late order to explain, a low-stock product, a queue of urgent
orders, an assignment to a robot that cannot take it. Each moment becomes one scenario:

    request          what the operator types
    replay           seed + overrides + tick: run the engine that long to get the exact state back
    facts            ground truth at that moment (statuses, temperatures, causes, ...)
    expected         tools the agent must call (in order), tools it may call, tools it must not
                     call, and the step budget
    success          machine-checkable conditions on the state after the agent acted
    reference_answer what a correct report says; sources = the SOP / manual sections it follows

Writes data/processed/agents/scenarios.jsonl and states/<id>.json (the state snapshot).
Metrics it supports: task success rate, tool-selection accuracy, number of steps, failure rate.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simulation.environment.engine import SimulationEngine  # noqa: E402
from simulation.events.events import EventType  # noqa: E402
from simulation.warehouse.entities import OrderStatus, Priority, RobotStatus  # noqa: E402

OUT = ROOT / "data" / "processed" / "agents"
SEEDS = range(500, 512)
TICKS = 5000
WARMUP = 300
OVERRIDES = {
    "layout": "large",
    "ticks_per_hour": 600,
    "orders": {"arrival_prob_per_tick": 0.2, "max_pending": 600},
    "faults": {"enabled": True, "probability_per_hour": 2.0},
    "hazards": {"enabled": True, "closures_per_hour": 1.0, "floor_hazards_per_hour": 1.5},
}
PER_TYPE_PER_SEED = 1


def fingerprint(engine: SimulationEngine) -> str:
    """Short hash of robot positions and statuses: proves a replay reached the same state."""
    data = [
        (r.robot_id, r.position, r.status.value, round(r.battery, 3))
        for r in engine.robots.values()
    ]
    return hashlib.sha256(json.dumps(data).encode()).hexdigest()[:16]


class Finder:
    def __init__(self, seed: int) -> None:
        self.seed = seed
        self.engine = SimulationEngine(seed=seed, overrides=OVERRIDES)
        self.events: list = []
        self.engine.events.subscribe(self.events.append)
        self.found: dict[str, int] = {}
        self.scenarios: list[dict] = []

    def run(self) -> list[dict]:
        eng = self.engine
        eng.start()
        for _ in range(TICKS):
            eng.tick()
            if eng.time < WARMUP:
                continue
            for check in (
                self.stopped_robot,
                self.overheating,
                self.blocked_robot,
                self.close_busy_aisle,
                self.late_order,
                self.low_stock,
                self.urgent_queue,
                self.unavailable_robot,
            ):
                kind = check.__name__
                if self.found.get(kind, 0) < PER_TYPE_PER_SEED:
                    scenario = check()
                    if scenario:
                        self.found[kind] = self.found.get(kind, 0) + 1
                        self.add(kind, scenario)
        return self.scenarios

    def add(self, kind: str, s: dict) -> None:
        eng = self.engine
        sid = f"AGT-{kind}-{self.seed}"
        state = eng.state(include_inventory=False)
        self.scenarios.append(
            {
                "id": sid,
                "type": kind,
                "request": s["request"],
                "replay": {
                    "seed": self.seed,
                    "overrides": OVERRIDES,
                    "ticks": eng.time,
                    "fingerprint": fingerprint(eng),
                },  # fmt: skip
                "facts": s["facts"],
                "expected": {
                    "required_tools": s["required"],
                    "allowed_tools": s.get("allowed", []),
                    "forbidden_tools": s.get("forbidden", []),
                    "max_steps": s.get("max_steps", 6),
                },
                "success": s["success"],
                "reference_answer": s["answer"],
                "sources": s["sources"],
                "state_file": f"states/{sid}.json",
            }
        )
        (OUT / "states").mkdir(parents=True, exist_ok=True)
        (OUT / "states" / f"{sid}.json").write_text(json.dumps(state, default=str))

    # ----- detectors -------------------------------------------------------------------
    def _task_order(self, rid: str):
        task = self.engine.controller.tasks.get(rid)
        if task and task.kind == "order":
            return self.engine.orders.get(task.order_id)
        return None

    def stopped_robot(self) -> dict | None:
        eng = self.engine
        for r in eng.robots.values():
            fault = eng.faults.active.get(r.robot_id)
            order = self._task_order(r.robot_id)
            if r.status == RobotStatus.FAULT and fault and fault.type == "stop_event" and order:
                left = order.deadline - eng.time
                urgent = order.priority == Priority.HIGH and left < 120
                return {
                    "request": f"Robot {r.robot_id} has stopped. Handle it.",
                    "facts": {
                        "robot_id": r.robot_id,
                        "status": "FAULT",
                        "fault": "stop_event",
                        "fault_ticks_left": fault.until - eng.time,
                        "order_id": order.order_id,
                        "order_priority": order.priority.value,
                        "deadline_ticks_left": left,
                        "position": list(r.position),
                    },  # fmt: skip
                    "required": [
                        {"name": "get_robot_status", "arguments": {"robot_id": r.robot_id}}
                    ]
                    + (
                        [
                            {"name": "pause_robot", "arguments": {"robot_id": r.robot_id}},
                            {"name": "assign_order", "arguments": {"order_id": order.order_id}},
                        ]
                        if urgent
                        else []
                    ),  # fmt: skip
                    "allowed": ["get_events", "search_knowledge", "get_warehouse_state"],
                    "forbidden": [] if urgent else ["pause_robot"],
                    "success": [{"check": "order_reassigned", "order_id": order.order_id}]
                    if urgent
                    else [{"check": "no_write_actions_except", "allowed": []}],
                    "answer": (
                        f"{r.robot_id} has a stop_event fault and is carrying HIGH-priority "
                        f"{order.order_id} with only {left} ticks left, so it was paused and the "
                        "order reassigned to a free robot (SOP-03 step 3)."
                        if urgent
                        else f"{r.robot_id} has a stop_event fault (normally clears within "
                        f"15-60 ticks). Its order {order.order_id} ({order.priority.value}) has "
                        f"{left} ticks left, so wait up to 60 ticks before pausing and "
                        "reassigning (SOP-03)."
                    ),
                    "sources": ["sops#SOP-03", "robot_manual#RM-6.1"],
                }
        return None

    def overheating(self) -> dict | None:
        eng = self.engine
        for r in eng.robots.values():
            if r.temperature >= 62 and r.status not in (RobotStatus.PAUSED, RobotStatus.FAULT):
                hot = r.temperature > 70
                return {
                    "request": f"{r.robot_id} is running hot. What should we do?",
                    "facts": {
                        "robot_id": r.robot_id,
                        "temperature_c": round(r.temperature, 1),
                        "status": r.status.value,
                        "throttled": True,
                        "has_order": self._task_order(r.robot_id) is not None,
                    },  # fmt: skip
                    "required": [
                        {"name": "get_robot_status", "arguments": {"robot_id": r.robot_id}},
                        {"name": "search_knowledge", "arguments": {}},
                    ],  # fmt: skip
                    "allowed": ["get_events"] + (["pause_robot", "assign_order"] if hot else []),
                    "forbidden": [] if hot else ["pause_robot"],
                    "success": [{"check": "no_new_order_for_robot", "robot_id": r.robot_id}],
                    "answer": (
                        f"{r.robot_id} is at {r.temperature:.0f} C: above 60 C it throttles "
                        "to half "
                        "speed. "
                        + (
                            "Above 70 C: pause it at the next safe stop and reassign its order. "
                            if hot
                            else "Let it finish its current order. "
                        )  # fmt: skip
                        + "No new orders until it is below 55 C (SOP-04)."
                    ),
                    "sources": ["sops#SOP-04", "robot_manual#RM-5.3"],
                }
        return None

    def blocked_robot(self) -> dict | None:
        eng = self.engine
        for r in eng.robots.values():
            blocked = eng.controller.blocked.get(r.robot_id, 0)
            if blocked >= 3 and r.route and r.status not in (RobotStatus.PAUSED, RobotStatus.FAULT):
                return {
                    "request": f"Robot {r.robot_id[1:]} is blocking the lane. Handle it.",
                    "facts": {
                        "robot_id": r.robot_id,
                        "blocked_ticks": blocked,
                        "position": list(r.position),
                        "status": r.status.value,
                        "next_cell": list(r.route[0]),
                    },  # fmt: skip
                    "required": [
                        {"name": "get_robot_status", "arguments": {"robot_id": r.robot_id}}
                    ],
                    "allowed": [
                        "get_warehouse_state",
                        "get_events",
                        "reroute_robot",
                        "search_knowledge",
                    ],  # fmt: skip
                    "forbidden": ["close_aisle"],
                    "success": [
                        {"check": "robot_moves_within", "robot_id": r.robot_id, "ticks": 30}
                    ],
                    "answer": (
                        f"{r.robot_id} has been blocked for {blocked} ticks behind another "
                        "robot or "
                        "obstacle. Standoffs normally clear by replanning after 2 ticks or a "
                        "side-step after 4-7; if not, reroute it and verify traffic flows (SOP-09)."
                    ),
                    "sources": ["sops#SOP-09", "warehouse_manual#WM-6.2"],
                }
        return None

    def close_busy_aisle(self) -> dict | None:
        eng = self.engine
        ctl = eng.controller
        for aisle in eng.layout.aisles:
            if aisle.aisle_id in eng.hazards.closures:
                continue
            cells = set(aisle.cells)
            inside = [r.robot_id for r in eng.robots.values() if r.position in cells]
            needing = [rid for rid, t in ctl.tasks.items() if cells & set(t.stops)]
            if inside and needing:
                return {
                    "request": f"Close {aisle.name} for maintenance.",
                    "facts": {
                        "aisle_id": aisle.aisle_id,
                        "robots_inside": inside,
                        "robots_needing_aisle": needing,
                    },  # fmt: skip
                    "required": [
                        {"name": "get_warehouse_state", "arguments": {}},
                        {"name": "close_aisle", "arguments": {"aisle_id": aisle.aisle_id}},
                    ],  # fmt: skip
                    "allowed": [
                        "get_robot_status",
                        "pause_robot",
                        "assign_order",
                        "get_events",
                        "search_knowledge",
                    ],  # fmt: skip
                    "forbidden": [],
                    "success": [{"check": "aisle_closed_when_empty", "aisle_id": aisle.aisle_id}],
                    "answer": (
                        f"{aisle.name} cannot be closed yet: {', '.join(inside)} is inside and "
                        f"{', '.join(needing)} still needs to pick there. "
                        "Wait until they have left "
                        "(or pause them and reassign their orders), then close the aisle (SOP-05)."
                    ),
                    "sources": ["sops#SOP-05", "safety_rules#SAF-3.6"],
                    "max_steps": 8,
                }
        return None

    def late_order(self) -> dict | None:
        eng = self.engine
        recent = [e for e in self.events[-200:] if e.tick == eng.time - 1]
        for e in recent:
            if e.type != EventType.ORDER_DELIVERED or not e.payload.get("late"):
                continue
            p = e.payload
            rid = p["robot_id"]
            faults = sorted({x.payload.get("fault") for x in self.events
                             if x.type == EventType.ROBOT_FAULT and x.entity_id == rid
                             and p["assigned_at"] <= x.tick <= p["delivered_at"]})  # fmt: skip
            if p["queue_ticks"] > p["duration_ticks"]:
                cause = "waited in the queue for a robot (busy fleet or a closed aisle)"
            elif faults:
                cause = f"the robot had a fault on the way ({', '.join(faults)})"
            elif p["waits"] > 20:
                cause = f"traffic: the robot waited {p['waits']} ticks behind others"
            else:
                cause = "a long route for a tight deadline"
            return {
                "request": f"Why was {e.entity_id} late?",
                "facts": {
                    "order_id": e.entity_id,
                    "robot_id": rid,
                    "priority": p["priority"],
                    "queue_ticks": p["queue_ticks"],
                    "duration_ticks": p["duration_ticks"],
                    "waits": p["waits"],
                    "reroutes": p["reroutes"],
                    "faults": faults,
                    "closures_active_at_assignment": p["closures_active"],
                    "cause": cause,
                },  # fmt: skip
                "required": [{"name": "get_events", "arguments": {"entity_id": e.entity_id}}],
                "allowed": ["get_robot_status", "get_events", "get_warehouse_state"],
                "forbidden": ["assign_order", "pause_robot", "close_aisle"],
                "success": [{"check": "answer_mentions", "any_of": [cause.split(" ")[0]]}],
                "answer": f"{e.entity_id} ({p['priority']}) was late mainly because {cause}.",
                "sources": ["warehouse_manual#WM-5.2", "warehouse_manual#WM-5.4"],
            }
        return None

    def low_stock(self) -> dict | None:
        inv = self.engine.inventory
        for pid, stock in inv.stock.items():
            if stock < 10 and inv.restocking(pid):
                return {
                    "request": f"Do we still have {pid}?",
                    "facts": {
                        "product_id": pid,
                        "stock": stock,
                        "restocking": True,
                        "location": inv.location(pid),
                    },  # fmt: skip
                    "required": [{"name": "get_inventory", "arguments": {"product_id": pid}}],
                    "allowed": ["search_knowledge"],
                    "forbidden": ["create_order"],
                    "success": [{"check": "answer_mentions", "any_of": [str(stock)]}],
                    "answer": (
                        f"{pid} has {stock} units left in bay {inv.location(pid)}, below the "
                        "reorder point of 10, and a replenishment is on its way (INV-3)."
                    ),
                    "sources": ["inventory_policies#INV-3.1", "inventory_policies#INV-3.2"],
                }
        return None

    def urgent_queue(self) -> dict | None:
        eng = self.engine
        high = [o for o in eng.orders.values()
                if o.status == OrderStatus.PENDING and o.priority == Priority.HIGH]  # fmt: skip
        if len(high) < 3:
            return None
        free = sum(eng.controller.available(r) for r in eng.robots.values())
        blocked = [o.order_id for o in high if eng.dispatcher.needs_closed_cell(o)]
        return {
            "request": "Prioritise all urgent orders.",
            "facts": {
                "high_pending": [o.order_id for o in high],
                "free_robots": free,
                "waiting_for_closed_aisle": blocked,
                "assignment_mode": "auto" if eng.dispatcher.auto else "manual",
            },  # fmt: skip
            "required": [{"name": "get_pending_orders", "arguments": {"priority": "HIGH"}}],
            "allowed": ["get_warehouse_state", "assign_order", "open_aisle", "search_knowledge"],
            "forbidden": ["pause_robot"],
            "success": [{"check": "high_orders_not_delayed_by_agent"}],
            "answer": (
                f"{len(high)} HIGH-priority orders are waiting; the dispatcher already serves them "
                f"first. {free} robots are free"
                + (
                    f"; {len(blocked)} wait for a closed aisle - consider reopening it"
                    if blocked
                    else ""
                )
                + " (SOP-07)."
            ),
            "sources": ["sops#SOP-07", "warehouse_manual#WM-5.4"],
        }

    def unavailable_robot(self) -> dict | None:
        eng = self.engine
        ctl = eng.controller
        pending = [o for o in eng.orders.values() if o.status == OrderStatus.PENDING]
        if not pending:
            return None
        for r in eng.robots.values():
            reason = ctl.unavailable_reason(r)
            if reason and ("charging" in reason or "battery" in reason or "faulty" in reason):
                order = pending[0]
                return {
                    "request": f"Assign {order.order_id} to {r.robot_id}.",
                    "facts": {
                        "order_id": order.order_id,
                        "robot_id": r.robot_id,
                        "rejection_reason": reason,
                        "battery": round(r.battery, 1),
                    },  # fmt: skip
                    "required": [
                        {
                            "name": "assign_order",
                            "arguments": {"robot_id": r.robot_id, "order_id": order.order_id},
                        }
                    ],  # fmt: skip
                    "allowed": ["get_robot_status", "get_warehouse_state", "assign_order"],
                    "forbidden": ["resume_robot"],
                    "success": [
                        {"check": "order_assigned_to_eligible_robot", "order_id": order.order_id}
                    ],
                    "answer": (
                        f"The assignment is rejected: {reason}. Choose a free robot with at least "
                        "20 % battery near the order's first rack (SOP-08)."
                    ),
                    "sources": ["sops#SOP-08", "robot_manual#RM-7.2"],
                }
        return None


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    scenarios: list[dict] = []
    for seed in SEEDS:
        found = Finder(seed).run()
        scenarios += found
        print(f"  seed {seed}: {len(found)} scenarios", flush=True)

    # Knowledge-only requests (no simulator state needed): answered from the documents.
    rag = [
        json.loads(line)
        for line in (ROOT / "data/processed/rag/questions.jsonl").open(encoding="utf-8")
    ]
    for q in [q for q in rag if q["type"] == "procedural"][:10]:
        scenarios.append(
            {
                "id": f"AGT-knowledge-{q['id']}",
                "type": "knowledge",
                "request": q["question"],
                "replay": None,
                "facts": {},
                "expected": {
                    "required_tools": [{"name": "search_knowledge", "arguments": {}}],
                    "allowed_tools": [],
                    "forbidden_tools": [
                        "pause_robot",
                        "assign_order",
                        "close_aisle",
                        "reroute_robot",
                    ],
                    "max_steps": 3,
                },  # fmt: skip
                "success": [{"check": "cites_sources", "sources": q["sources"]}],
                "reference_answer": q["answer"],
                "sources": q["sources"],
                "state_file": None,
            }
        )
    with (OUT / "scenarios.jsonl").open("w", encoding="utf-8") as f:
        for s in scenarios:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    by_type: dict[str, int] = {}
    for s in scenarios:
        by_type[s["type"]] = by_type.get(s["type"], 0) + 1
    print(f"{len(scenarios)} scenarios {by_type} -> {OUT}")


if __name__ == "__main__":
    main()

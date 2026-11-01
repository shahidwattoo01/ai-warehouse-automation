"""Agent evaluation on the 92 simulator scenarios (Phase 8; docs/phase8_agents.md).

For every scenario of data/processed/agents/scenarios.jsonl:

1. replay the simulator to the scenario's moment (seed, overrides, ticks) and check the state
   fingerprint, so the agent sees exactly the situation the scenario describes;
2. run the agent on the operator's request, every write approved (the worst case: a person who
   approves everything does not filter the agent's mistakes);
3. keep the warehouse running (scheduled aisle closures happen when clear) and apply the
   scenario's success checks to what actually happened.

Measured: task success (all checks pass and no forbidden tool), required tools called in order,
forbidden tools called, steps within the budget.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

from ai.agents.graph import Agent
from ai.agents.tools import EventLog, close_scheduled_aisles
from simulation.environment.engine import SimulationEngine
from simulation.events.events import EventType

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = ROOT / "data" / "processed" / "agents" / "scenarios.jsonl"
HORIZON = 200  # ticks the warehouse keeps running after the agent acted


def load_scenarios(path: Path = SCENARIOS) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def fingerprint(engine) -> str:
    """The same hash as scripts/generate_agent_scenarios.py."""
    data = [
        (r.robot_id, r.position, r.status.value, round(r.battery, 3))
        for r in engine.robots.values()
    ]
    return hashlib.sha256(json.dumps(data).encode()).hexdigest()[:16]


def replay(scenario: dict):
    rp = scenario["replay"] or {
        "seed": 0,
        "overrides": {"layout": "large"},
        "ticks": 0,
        "fingerprint": None,
    }  # questions: no moment to replay
    eng = SimulationEngine(seed=rp["seed"], overrides=rp["overrides"])
    log = EventLog(eng)
    eng.start()
    for _ in range(rp["ticks"]):
        eng.tick()
    return eng, log, rp["fingerprint"] is None or fingerprint(eng) == rp["fingerprint"]


class Watcher:
    """What happens after the agent acted, for the checks."""

    def __init__(self, eng, scenario: dict) -> None:
        self.eng, self.start = eng, eng.time
        self.assigned: list[tuple[int, str, str]] = []  # tick, order, robot
        self.assigned_hot: list[str] = []  # robots given an order at 55 deg C or more (SOP-04)
        self.closed_at: dict[str, list[str]] = {}  # aisle -> robots inside at that moment
        self.first_move: dict[str, int] = {}
        self.positions = {rid: tuple(r.position) for rid, r in eng.robots.items()}
        eng.events.subscribe(self._on_event, external=True)

    def _on_event(self, e) -> None:
        if e.type == EventType.ORDER_ASSIGNED:
            rid = (e.payload or {}).get("robot_id")
            self.assigned.append((e.tick, e.entity_id, rid))
            if rid in self.eng.robots and self.eng.robots[rid].temperature >= 55.0:
                self.assigned_hot.append(rid)
        elif e.type == EventType.AISLE_CLOSED and e.entity_id not in self.closed_at:
            aisle = next(a for a in self.eng.layout.aisles if a.aisle_id == e.entity_id)
            cells = set(aisle.cells)
            self.closed_at[e.entity_id] = [
                r.robot_id for r in self.eng.robots.values() if tuple(r.position) in cells
            ]

    def after_tick(self) -> None:
        for rid, r in self.eng.robots.items():
            if rid not in self.first_move and tuple(r.position) != self.positions[rid]:
                self.first_move[rid] = self.eng.time - self.start


def check(c: dict, run: dict, w: Watcher, scenario: dict, executed_writes: list[str]) -> bool:
    kind = c["check"]
    answer = (run["answer"] or "").lower()
    if kind == "aisle_closed_when_empty":
        inside = w.closed_at.get(c["aisle_id"])
        return inside is not None and not inside
    if kind == "no_new_order_for_robot":  # SOP-04: none until it has cooled below 55 deg C
        return c["robot_id"] not in w.assigned_hot
    if kind == "robot_moves_within":
        return w.first_move.get(c["robot_id"], 10**9) <= c["ticks"]
    if kind == "answer_mentions":
        return any(word.lower() in answer for word in c["any_of"])
    if kind == "order_assigned_to_eligible_robot":
        bad = scenario["facts"].get("robot_id")
        return any(o == c["order_id"] and r != bad for _, o, r in w.assigned)
    if kind == "order_reassigned":
        return any(o == c["order_id"] for _, o, _ in w.assigned)
    if kind == "no_write_actions_except":
        return all(t in c["allowed"] for t in executed_writes)
    if kind == "high_orders_not_delayed_by_agent":
        return all(t == "assign_order" for t in executed_writes)
    if kind == "cites_sources":
        cited = set(run["sources"])
        return any(s in cited for s in c["sources"])
    raise ValueError(f"unknown check {kind}")


def required_in_order(required: list[dict], steps: list[dict]) -> bool:
    i = 0
    for s in steps:
        if i < len(required) and s["tool"] == required[i]["name"]:
            want = required[i].get("arguments") or {}
            if all(s["args"].get(k) == v for k, v in want.items()):
                i += 1
    return i == len(required)


def evaluate_one(scenario: dict, planner, knowledge=None, platform_rules: bool = True) -> dict:
    eng, log, same = replay(scenario)
    if platform_rules:  # the live platform's dispatcher rules (after the exact replay)
        eng.config["thermal"]["no_new_orders_above"] = 60.0
    ctx = {"engine": eng, "events": log, "knowledge": knowledge, "pending_closures": {}}
    exp = scenario["expected"]
    agent = Agent(planner, max_steps=max(exp["max_steps"], 8))
    w = Watcher(eng, scenario)
    run = agent.run(scenario["request"], ctx, approve=lambda name, args: True)
    for _ in range(HORIZON):
        close_scheduled_aisles(ctx)
        eng.tick()
        w.after_tick()
    called = [s["tool"] for s in run["steps"]]
    writes = [
        s["tool"] for s in run["steps"] if "result" in s and agent.registry.is_write(s["tool"])
    ]
    checks = {c["check"]: check(c, run, w, scenario, writes) for c in scenario["success"]}
    forbidden = [t for t in called if t in exp["forbidden_tools"]]
    tools_ok = required_in_order(exp["required_tools"], run["steps"])
    return {
        "id": scenario["id"],
        "type": scenario["type"],
        "replayed_exactly": same,
        "success": all(checks.values()) and not forbidden,
        "checks": checks,
        "required_tools_ok": tools_ok,
        "forbidden_called": forbidden,
        "steps": len(run["steps"]),
        "within_budget": len(run["steps"]) <= exp["max_steps"],
        "errors": [s["error"] for s in run["steps"] if "error" in s],
        "answer": run["answer"],
        "reference": scenario["reference_answer"],
        "tools": called,
    }


def summarise(rows: list[dict]) -> dict:
    by_type: dict[str, list] = defaultdict(list)
    for r in rows:
        by_type[r["type"]].append(r)

    def stats(rs: list[dict]) -> dict:
        n = len(rs)
        return {
            "scenarios": n,
            "task_success": round(sum(r["success"] for r in rs) / n, 3),
            "required_tools": round(sum(r["required_tools_ok"] for r in rs) / n, 3),
            "forbidden_calls": sum(len(r["forbidden_called"]) for r in rs),
            "within_budget": round(sum(r["within_budget"] for r in rs) / n, 3),
            "avg_steps": round(sum(r["steps"] for r in rs) / n, 2),
            "replayed_exactly": sum(r["replayed_exactly"] for r in rs),
        }

    return {"overall": stats(rows), "by_type": {t: stats(rs) for t, rs in sorted(by_type.items())}}

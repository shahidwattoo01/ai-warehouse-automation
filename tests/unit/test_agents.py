"""Phase 8 agents: tool registry validation, the agent loop (approval gate, step limit, errors as
observations), the offline playbooks on replayed scenarios, and the Claude planner's tool-use
loop against a scripted stand-in for the API."""

from types import SimpleNamespace

import pytest

from ai.agents.evaluate import evaluate_one, load_scenarios, replay
from ai.agents.graph import Agent
from ai.agents.planner import ClaudePlanner, OfflinePlanner, situation
from ai.agents.tools import ToolError, ToolRegistry

REG = ToolRegistry()


@pytest.fixture(scope="module")
def scenarios():
    return {s["id"]: s for s in load_scenarios()}


def test_registry_has_the_15_tools_with_flags():
    names = {t["name"] for t in REG.schema()}
    assert len(names) == 15 and {"close_aisle", "search_knowledge", "assign_order"} <= names
    assert REG.is_write("pause_robot") and REG.needs_approval("pause_robot")
    assert not REG.is_write("get_robot_status")


def test_validation_against_schema_and_warehouse(scenarios):
    eng, _, _ = replay(next(iter(scenarios.values())))
    with pytest.raises(ToolError, match="does not match"):
        REG.validate(eng, "get_robot_status", {"robot_id": "robot five"})
    with pytest.raises(ToolError, match="required"):
        REG.validate(eng, "assign_order", {"robot_id": "R1"})
    with pytest.raises(ToolError, match="no order"):
        REG.validate(eng, "assign_order", {"robot_id": "R1", "order_id": "O99999"})
    with pytest.raises(ToolError, match="unknown tool"):
        REG.validate(eng, "delete_everything", {})


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Close Aisle 7 for maintenance.", "close_aisle"),
        ("Why was O00025 late?", "late_order"),
        ("Assign O00146 to R9.", "assign"),
        ("Prioritise all urgent orders.", "urgent"),
        ("R22 is running hot. What should we do?", "overheating"),
        ("Robot 5 is blocking the lane. Handle it.", "blocked"),
        ("Robot R30 has stopped. Handle it.", "stopped"),
        ("What does a robot do when the cell ahead of it is taken?", "question"),
        ("Can I close Aisle 12 while a robot is picking in it?", "question"),  # never act on it
    ],
)
def test_situations(text, kind):
    assert situation(text) == kind


def test_approval_gate_pending_refused_approved(scenarios):
    s = scenarios["AGT-close_busy_aisle-500"]
    for approve, expect in ((None, "waiting for approval"), (lambda n, a: False, "refused")):
        eng, log, _ = replay(s)
        ctx = {"engine": eng, "events": log, "pending_closures": {}}
        run = Agent(OfflinePlanner()).run(s["request"], ctx, approve=approve)
        close = next(st for st in run["steps"] if st["tool"] == "close_aisle")
        assert expect in close["result"]["status"]
        assert not ctx["pending_closures"] and "AISLE_07" not in eng.hazards.closures
        assert bool(run["pending"]) == (approve is None)
    row = evaluate_one(s, OfflinePlanner())  # approved: closes once the aisle is clear
    assert row["success"] and row["checks"]["aisle_closed_when_empty"]


def test_unavailable_robot_is_replaced(scenarios):
    s = scenarios["AGT-unavailable_robot-500"]
    row = evaluate_one(s, OfflinePlanner())
    assert row["success"], row
    assert row["tools"][0] == "get_robot_status" and "assign_order" in row["tools"]


class Looping:
    name = "looping"

    def start(self, request):
        return SimpleNamespace(next=lambda step: {"tool": "get_robot_status",
                                                  "args": {"robot_id": "R99"}})  # fmt: skip


def test_step_limit_and_errors_are_observations(scenarios):
    eng, log, _ = replay(next(iter(scenarios.values())))
    run = Agent(Looping(), max_steps=3).run("x", {"engine": eng, "events": log})
    assert len(run["steps"]) == 3 and "stopped after 3 steps" in run["answer"]
    assert all("error" in s for s in run["steps"])  # R99 does not exist: told, not crashed


class FakeClaude:
    """Scripted Messages API: asks for a robot's status, then answers."""

    def __init__(self):
        self.calls = []
        self.messages = SimpleNamespace(create=self.create)

    def create(self, **kw):
        self.calls.append({**kw, "messages": list(kw["messages"])})  # as sent at the time
        if len(self.calls) == 1:
            block = SimpleNamespace(type="tool_use", id="tu_1", name="get_robot_status",
                                    input={"robot_id": "R30"})  # fmt: skip
        else:
            block = SimpleNamespace(type="text", text="R30 has a fault; wait 60 ticks (SOP-03).")
        return SimpleNamespace(content=[block])


def test_claude_planner_tool_use_loop(scenarios):
    s = scenarios["AGT-stopped_robot-500"]
    eng, log, _ = replay(s)
    client = FakeClaude()
    run = Agent(ClaudePlanner(client, "claude-test", REG)).run(
        s["request"], {"engine": eng, "events": log}
    )
    assert [st["tool"] for st in run["steps"]] == ["get_robot_status"]
    assert run["sources"] == ["SOP-03"] and "wait" in run["answer"]
    assert len(client.calls[0]["tools"]) == 15  # every tool offered with its schema
    second = client.calls[1]["messages"]
    assert second[-1]["content"][0]["type"] == "tool_result"  # the result went back to Claude
    assert second[-1]["content"][0]["tool_use_id"] == "tu_1"

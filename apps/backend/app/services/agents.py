"""The operations agent next to the live simulator (Phase 8; docs/phase8_agents.md).

A request runs the agent loop on the live warehouse: reads happen at once, every write that needs
approval waits as a pending action for a person with `copilot:approve` (and the permission of the
action itself, as for the copilot). Approved actions run through the same registry, so they are
validated again against the warehouse as it is at that moment. Scheduled aisle closures are
checked every tick and happen as soon as their aisle is clear.
"""

from __future__ import annotations

import time
from collections import deque

from ai.agents.graph import Agent
from ai.agents.planner import make_planner
from ai.agents.tools import EventLog, ToolError, ToolRegistry, close_scheduled_aisles
from app.core.config import get_settings

PENDING_MINUTES = 15  # an action not decided within this time expires (the warehouse moved on)
# The permission an approver needs for each write tool, besides copilot:approve.
PERMISSION = {
    "assign_order": "orders:assign", "set_assignment_mode": "orders:assign",
    "create_order": "orders:create", "pause_robot": "robots:command",
    "resume_robot": "robots:command", "reroute_robot": "robots:command",
    "close_aisle": "robots:command", "open_aisle": "robots:command",
}  # fmt: skip


class AgentService:
    def __init__(self) -> None:
        self.registry = ToolRegistry()
        self.engine = None
        self.ctx: dict = {}
        self.pending: dict[str, dict] = {}
        self.history: deque = deque(maxlen=50)
        self.planner = None

    def attach(self, engine) -> None:
        self.engine = engine
        self.ctx = {"engine": engine, "events": EventLog(engine), "pending_closures": {},
                    "knowledge": _ask}  # fmt: skip
        self.pending.clear()

    def _planner(self):
        if self.planner is None:
            s = get_settings()
            self.planner = make_planner(s.llm_provider, s.llm_api_key, s.llm_model, self.registry)
        return self.planner

    def after_tick(self) -> None:
        if self.ctx:
            close_scheduled_aisles(self.ctx)

    async def run(self, request: str, user: str) -> dict:
        agent = Agent(self._planner(), self.registry)
        result = await agent.arun(request, self.ctx)
        for action in result["pending"]:
            self.pending[action["action_id"]] = {
                **action, "request": request, "user": user, "created": time.time(),
                "permission": PERMISSION.get(action["tool"]),
            }  # fmt: skip
        self.history.appendleft({"at": time.time(), "user": user, **result})
        return result

    def _take(self, action_id: str) -> dict:
        self._expire()
        action = self.pending.pop(action_id, None)
        if action is None:
            raise KeyError(f"no pending action {action_id} (decided or expired)")
        return action

    def approve(self, action_id: str, user: str, can) -> dict:
        action = self.pending.get(action_id)
        if action and action["permission"] and not can(action["permission"]):
            raise PermissionError(f"approving {action['tool']} needs {action['permission']}")
        action = self._take(action_id)
        try:
            result = self.registry.run(self.ctx, action["tool"], action["args"])
        except ToolError as err:
            result = {"status": "refused by the warehouse", "error": str(err)}
        return {"action_id": action_id, "tool": action["tool"], "args": action["args"],
                "approved_by": user, "result": result}  # fmt: skip

    def reject(self, action_id: str, user: str) -> dict:
        action = self._take(action_id)
        return {"action_id": action_id, "tool": action["tool"], "rejected_by": user}

    def _expire(self) -> None:
        cutoff = time.time() - PENDING_MINUTES * 60
        for aid in [a for a, v in self.pending.items() if v["created"] < cutoff]:
            del self.pending[aid]

    def status(self) -> dict:
        self._expire()
        return {"planner": self._planner().name, "tools": len(self.registry.specs),
                "pending": list(self.pending.values()),
                "scheduled_closures": dict(self.ctx.get("pending_closures", {}))}  # fmt: skip


def _ask(query: str) -> dict:
    """The knowledge assistant's search (runs in a worker thread, see Agent.arun)."""
    from app.services.knowledge import knowledge

    return knowledge._ensure_loaded().ask(query)


agents = AgentService()

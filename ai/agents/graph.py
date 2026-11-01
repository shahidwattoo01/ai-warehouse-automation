"""The agent loop (Phase 8; docs/phase8_agents.md).

    request ──► planner: next step? ──► tool call ──► registry validates and runs it ──┐
                   ▲                                                                     │
                   └──────────────────────── observation (structured result) ◄──────────┘
                   └──► answer (with the SOP / manual sections it relied on)

* Step budget: at most `max_steps` tool calls; then it stops and says so.
* Approval gate: a write tool that needs approval is not run unless `approve` says yes. Without an
  approver (the live copilot) it becomes a pending action that a person approves or rejects; the
  planner is told it is waiting and continues with what it knows.
* A refused call (unknown robot, bad argument, robot that cannot take an order) comes back to the
  planner as an error observation, so it can choose differently: it never crashes the run.
"""

from __future__ import annotations

import time
import uuid

from ai.agents.tools import ToolError, ToolRegistry


class Agent:
    def __init__(self, planner, registry: ToolRegistry | None = None, max_steps: int = 8) -> None:
        self.planner = planner
        self.registry = registry or ToolRegistry()
        self.max_steps = max_steps

    def run(self, request: str, ctx: dict, approve=None) -> dict:
        """`approve(name, args) -> bool | None`: True runs it, False refuses, None (or no
        approver) leaves it pending."""
        began, steps, pending = time.perf_counter(), [], []
        session = self.planner.start(request)
        decision = session.next(None)
        while "tool" in decision and len(steps) < self.max_steps:
            step = self._execute(decision, len(steps) + 1, ctx, approve, pending)
            steps.append(step)
            decision = session.next(step)
        return self._finish(request, decision, steps, pending, began)

    async def arun(self, request: str, ctx: dict, approve=None, offload=("search_knowledge",)):
        """`run` for the live platform: the `offload` tools (CPU-heavy, no engine access) run in
        a worker thread, so the simulator loop keeps ticking; everything else between ticks."""
        import asyncio

        began, steps, pending = time.perf_counter(), [], []
        session = self.planner.start(request)
        decision = await asyncio.to_thread(session.next, None)  # an LLM call may take seconds
        while "tool" in decision and len(steps) < self.max_steps:
            args = (decision, len(steps) + 1, ctx, approve, pending)
            if decision["tool"] in offload:
                step = await asyncio.to_thread(self._execute, *args)
            else:
                step = self._execute(*args)
            steps.append(step)
            decision = await asyncio.to_thread(session.next, step)
        return self._finish(request, decision, steps, pending, began)

    def _execute(self, decision: dict, number: int, ctx: dict, approve, pending: list) -> dict:
        name, args = decision["tool"], decision.get("args", {})
        step = {"step": number, "tool": name, "args": args}
        try:
            if self.registry.is_write(name) and self.registry.needs_approval(name):
                ok = approve(name, args) if approve else None
                if ok is None:
                    self.registry.validate(ctx["engine"], name, args)  # never queue nonsense
                    action = {"action_id": uuid.uuid4().hex[:8], "tool": name, "args": args}
                    pending.append(action)
                    step["result"] = {"status": "waiting for approval", **action}
                elif not ok:
                    step["result"] = {"status": "refused by the operator"}
                else:
                    step["result"] = self.registry.run(ctx, name, args)
            else:
                step["result"] = self.registry.run(ctx, name, args)
        except ToolError as err:
            step["error"] = str(err)
        except KeyError as err:  # a tool the registry does not know
            step["error"] = f"unknown tool {err}"
        return step

    def _finish(self, request, decision, steps, pending, began) -> dict:
        if "tool" in decision:
            answer = f"I stopped after {self.max_steps} steps without finishing."
            sources: list[str] = []
        else:
            answer, sources = decision.get("answer", ""), decision.get("sources", [])
        return {
            "request": request,
            "answer": answer,
            "sources": sources,
            "steps": steps,
            "pending": pending,
            "planner": self.planner.name,
            "ms": round((time.perf_counter() - began) * 1000),
        }

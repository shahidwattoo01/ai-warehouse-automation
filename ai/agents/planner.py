"""Planners for the agent loop (Phase 8; docs/phase8_agents.md).

OfflinePlanner (default, no API key needed)
    Recognises the situation in the request (robot stopped, overheating, blocked, a late order,
    an assignment, urgent orders, closing an aisle, or a question) and works through the
    procedure for it from the SOPs. Every decision is taken from what the tools return, not from
    the wording: "assign O00146 to R9" checks R9 first and picks another robot if R9 cannot take it.

ClaudePlanner (LLM_PROVIDER=anthropic and LLM_API_KEY set)
    The same tools, offered to Claude through tool use with the SOP rules in the system prompt:
    any wording, and situations no playbook covers. Same loop, same validation, same approvals.

A planner's `start(request)` returns a session; `session.next(last_step)` returns the next
{"tool", "args"} or the final {"answer", "sources"}.
"""

from __future__ import annotations

import json
import re

ORDER = re.compile(r"\bO\d{5}\b", re.I)
AISLE = re.compile(r"\baisle\s*(\d{1,2})\b", re.I)
REASONS = {"spill": "spill cleanup", "inspect": "rack inspection", "mainten": "maintenance"}


def _robot(text: str) -> str | None:
    m = re.search(r"\bR(\d{1,2})\b", text) or re.search(r"\brobot\s+(\d{1,2})\b", text, re.I)
    return f"R{int(m.group(1))}" if m else None


def _order(text: str) -> str | None:
    m = ORDER.search(text)
    return m.group(0).upper() if m else None


QUESTION_WORDS = {
    "can",
    "could",
    "may",
    "should",
    "is",
    "are",
    "do",
    "does",
    "what",
    "how",
    "when",
    "why",
    "which",
    "who",
    "where",
}


def is_question(text: str) -> bool:
    """'Can I close Aisle 12 while a robot is picking in it?' asks about the rule: it must never
    act (it did, once, in the evaluation: Q054)."""
    first = text.strip().split()[0].lower() if text.strip() else ""
    return text.strip().endswith("?") and first in QUESTION_WORDS


def situation(text: str) -> str:
    t = text.lower()
    if is_question(text) and not (_robot(text) or _order(text)):
        return "question"  # about procedures, no robot or order named: answer, never act
    if AISLE.search(t) and ("close" in t or "shut" in t) and not is_question(text):
        return "close_aisle"
    if _order(text) and ("late" in t or "delay" in t):
        return "late_order"
    if _order(text) and "assign" in t:
        return "assign"
    if "urgent" in t or "priorit" in t or "high-priority" in t:
        return "urgent"
    if _robot(text) and any(w in t for w in ("hot", "overheat", "temperature")):
        return "overheating"
    if _robot(text) and any(w in t for w in ("block", "in the way", "lane")):
        return "blocked"
    if _robot(text) and any(w in t for w in ("stopped", "not moving", "stuck", "halted")):
        return "stopped"
    return "question"


# ----- offline playbooks: generators that yield tool calls and receive the step back ------------
def _ok(step: dict | None) -> dict:
    return (step or {}).get("result") or {}


def _knowledge(query: str):
    step = yield {"tool": "search_knowledge", "args": {"query": query}}
    return _ok(step).get("sources", []), _ok(step).get("answer")


def play_stopped(text: str):
    rid = _robot(text)
    r = _ok((yield {"tool": "get_robot_status", "args": {"robot_id": rid}}))
    fault = r.get("fault") or {}
    if r.get("status") == "FAULT":
        kind = fault.get("type", "a fault")
        state = _ok((yield {"tool": "get_warehouse_state", "args": {}}))
        left = max(0, fault.get("until", 0) - state.get("tick", 0)) if fault else None
        order = r.get("order_id")
        carried = r.get("order") or {}
        urgent = (
            carried.get("priority") == "HIGH"
            and left is not None
            and carried.get("deadline_ticks_left", 10**9) < left + 120
        )
        if urgent and carried.get("items_left") == carried.get("items"):
            # SOP-03 step 3: the HIGH order cannot wait for the fault; nothing picked yet
            yield {"tool": "pause_robot", "args": {"robot_id": rid}}
            free = _ok((yield {"tool": "get_pending_orders", "args": {}})).get("free_robots", [])
            for other in free[:2]:
                step = yield {
                    "tool": "assign_order",
                    "args": {"robot_id": other, "order_id": order},
                }
                if "error" not in step:
                    return (
                        f"{rid} is stopped by a {kind} fault ({left} ticks to clear) and carries "
                        f"HIGH-priority {order} with only {carried['deadline_ticks_left']} ticks "
                        f"left, so I paused it and gave the order to {other} (SOP-03 step 3).",
                        ["sops#SOP-03"],
                    )
            return (
                f"{rid} is paused; {order} (HIGH) needs another robot but none is free now: "
                "assign it as soon as one is (SOP-03 step 3).",
                ["sops#SOP-03"],
            )
        extra = f" Its order {order} stays with it meanwhile." if order else ""
        clears = f", which clears in about {left} ticks" if left is not None else ""
        return (
            f"{rid} is stopped by a {kind} fault{clears}. Such faults normally clear within "
            f"15-60 ticks, so wait up to 60 ticks before pausing it and reassigning its order "
            f"(SOP-03).{extra}",
            ["sops#SOP-03"],
        )
    if r.get("status") == "PAUSED":
        return f"{rid} is paused by an operator; resume it when the reason is cleared.", []
    return (
        f"{rid} is {str(r.get('status')).lower()}, heading to {r.get('destination')}: it "
        "is not stopped now.",
        [],
    )


def play_overheating(text: str):
    rid = _robot(text)
    r = _ok((yield {"tool": "get_robot_status", "args": {"robot_id": rid}}))
    sources, _ = yield from _knowledge("robot overheating temperature limit throttle")
    temp = r.get("temperature")
    hot = temp is not None and temp >= 60
    state = f"{rid} is at {temp:.0f} °C" if temp is not None else f"{rid}'s temperature is unknown"
    if hot:
        advice = (
            "above 60 °C it throttles to half speed. Let it finish its current task; give "
            "it no new orders until it is below 55 °C, and send it to maintenance if it "
            "keeps overheating (SOP-04)."
        )
    else:
        advice = "below the 60 °C limit: no action needed, keep watching it (SOP-04)."
    return f"{state}: {advice}", ["sops#SOP-04", *sources[:1]]


def play_blocked(text: str):
    rid = _robot(text)
    r = _ok((yield {"tool": "get_robot_status", "args": {"robot_id": rid}}))
    ev = _ok((yield {"tool": "get_events", "args": {"entity_id": rid}})).get("events", [])
    waits = [e for e in ev if "WAIT" in e["type"] or "BLOCK" in e["type"]]
    if r.get("status") in ("PAUSED", "FAULT"):
        return (
            f"{rid} is {r['status'].lower()}, which is why it is in the way; see SOP-03 "
            "for a stopped robot.",
            ["sops#SOP-03"],
        )
    return (
        f"{rid} is {str(r.get('status')).lower()} at {tuple(r.get('position', []))}"
        f"{f', blocked {len(waits)} times recently' if waits else ''}. Standoffs clear by "
        "replanning after 2 blocked ticks or a side-step after 4-7, so leave it to the traffic "
        "rules; if it is still blocked after that, reroute it and check traffic flows "
        "(SOP-09).",
        ["sops#SOP-09"],
    )


def play_late(text: str):
    oid = _order(text)
    ev = _ok((yield {"tool": "get_events", "args": {"entity_id": oid}})).get("events", [])
    assigned = next((e for e in ev if e["type"] == "ORDER_ASSIGNED"), None)
    robots = [e.get("robot_id") for e in ev if e.get("robot_id")]
    if assigned and assigned.get("robot_id"):  # what happened to its robot while it carried it
        done = next((e["tick"] for e in ev if e["type"] == "ORDER_DELIVERED"), None)
        step = yield {
            "tool": "get_events",
            "args": {"entity_id": assigned["robot_id"], "since_tick": assigned["tick"]},
        }
        ev += [e for e in _ok(step).get("events", []) if done is None or e["tick"] <= done]
    types = [e["type"] for e in ev]
    faults = [e.get("fault") for e in ev if e["type"] == "ROBOT_FAULT"]
    causes = []
    if faults or "ROBOT_FAULT" in types:
        causes.append(
            f"the robot had a fault on the way ({', '.join(f for f in faults if f) or 'fault'})"
        )
    if "ORDER_REJECTED" in types or "ASSIGNMENT_REJECTED" in types:
        causes.append("its assignment was rejected first")
    if types.count("ROUTE_CHANGED") >= 3 or types.count("ROBOT_BLOCKED") >= 5:
        causes.append(
            f"traffic: {types.count('ROBOT_BLOCKED')} blocked ticks and "
            f"{types.count('ROUTE_CHANGED')} reroutes"
        )
    if any("CLOSED" in t for t in types):
        causes.append("an aisle was closed on its way")
    if not causes:
        causes.append("the robot met heavy traffic and waited on the way")
    by = f" ({robots[0]})" if robots else ""
    return (
        f"{oid} was late mainly because {causes[0]}{by}"
        f"{'; also ' + '; '.join(causes[1:]) if causes[1:] else ''}.",
        [],
    )


def play_assign(text: str):
    oid, rid = _order(text), _robot(text.replace(_order(text) or "", ""))
    r = _ok((yield {"tool": "get_robot_status", "args": {"robot_id": rid}})) if rid else {}
    if rid and r.get("available") and not r.get("unavailable_reason"):
        step = yield {"tool": "assign_order", "args": {"robot_id": rid, "order_id": oid}}
        if "error" not in step:
            return f"{oid} goes to {rid} ({_ok(step).get('status', 'queued')}).", ["sops#SOP-08"]
    reason = r.get("unavailable_reason") or f"{rid} cannot take it"
    free = _ok((yield {"tool": "get_pending_orders", "args": {}})).get("free_robots", [])
    for other in free[:2]:
        if other == rid:
            continue
        step = yield {"tool": "assign_order", "args": {"robot_id": other, "order_id": oid}}
        if "error" not in step:
            return (
                f"Not {rid}: {reason}. {oid} goes to {other} instead, a free robot with "
                "enough battery (SOP-08).",
                ["sops#SOP-08"],
            )
    return f"{oid} cannot be assigned now: {reason}, and no free robot can take it (SOP-08).", [
        "sops#SOP-08"
    ]


def play_urgent(text: str):
    p = _ok((yield {"tool": "get_pending_orders", "args": {"priority": "HIGH"}}))
    n, free = p.get("count", 0), p.get("free_robots", [])
    if p.get("assignment_mode") == "auto" or not n:
        return (
            f"{n} HIGH-priority orders are waiting; the dispatcher already serves them "
            f"first. {len(free)} robots are free (SOP-07).",
            ["sops#SOP-07"],
        )
    done = []
    for order, robot in zip(p["orders"], free, strict=False):
        step = yield {
            "tool": "assign_order",
            "args": {"robot_id": robot, "order_id": order["order_id"]},
        }
        if "error" not in step:
            done.append(f"{order['order_id']}→{robot}")
    return (
        f"Manual mode: {n} HIGH-priority orders waiting; assigned {', '.join(done) or 'none'} "
        "to the free robots (SOP-07).",
        ["sops#SOP-07"],
    )


def play_close_aisle(text: str):
    number = int(AISLE.search(text).group(1))
    aisle = f"AISLE_{number:02d}"
    reason = next((v for k, v in REASONS.items() if k in text.lower()), "operator request")
    s = _ok((yield {"tool": "get_warehouse_state", "args": {}}))
    blockers = s.get("aisles_in_use", {}).get(aisle, [])
    step = yield {"tool": "close_aisle", "args": {"aisle_id": aisle, "reason": reason}}
    result = _ok(step)
    if "error" in step:
        return f"Aisle {number} was not closed: {step['error']}.", ["sops#SOP-05"]
    if result.get("status") == "scheduled" or blockers:
        why = "; ".join(result.get("blockers") or blockers)
        return (
            f"Aisle {number} cannot be closed yet: {why}. It is scheduled and closes by itself "
            "as soon as it is clear, so no robot is trapped (SOP-05).",
            ["sops#SOP-05"],
        )
    if result.get("status") == "waiting for approval":
        return f"Closing aisle {number} ({reason}) waits for approval.", ["sops#SOP-05"]
    return f"Aisle {number} is closed for {reason} (SOP-05).", ["sops#SOP-05"]


def play_question(text: str):
    sources, answer = yield from _knowledge(text)
    if not answer:
        return "The documents do not cover this question.", sources
    return answer, sources


PLAYBOOKS = {
    "stopped": play_stopped,
    "overheating": play_overheating,
    "blocked": play_blocked,
    "late_order": play_late,
    "assign": play_assign,
    "urgent": play_urgent,
    "close_aisle": play_close_aisle,
    "question": play_question,
}


class _PlaybookSession:
    def __init__(self, gen) -> None:
        self.gen = gen
        self.started = False

    def next(self, step: dict | None) -> dict:
        try:
            call = self.gen.send(step) if self.started else next(self.gen)
            self.started = True
            return call
        except StopIteration as done:
            answer, sources = done.value
            return {"answer": answer, "sources": list(dict.fromkeys(sources))}


class OfflinePlanner:
    name = "offline playbooks"

    def start(self, request: str) -> _PlaybookSession:
        kind = situation(request)
        return _PlaybookSession(PLAYBOOKS[kind](request))


# ----- Claude ---------------------------------------------------------------------------------
SYSTEM = """You are the operations agent of an automated warehouse (40 AMRs, racks in aisles
AISLE_01-52, packing stations PACK_1-6, chargers CHG_1-4). Act only through the tools. Look before
you act: read the robot, order or warehouse state first. Follow the SOPs:
SOP-03 a stopped robot with a fault: faults clear in 15-60 ticks; wait up to 60 ticks before
pausing and reassigning. SOP-04 above 60 C a robot throttles; no new orders until below 55 C; do
not pause it. SOP-05 never close an aisle with robots or picks in it (close_aisle schedules the
closure until it is clear). SOP-07 the dispatcher serves HIGH orders first in auto mode. SOP-08
assign only to a free robot with at least 20 % battery. SOP-09 blocked robots clear by replanning
and side-steps; reroute only if still blocked. Use as few steps as possible. Finish with a short
answer for the operator that names the SOP sections you followed."""


class _ClaudeSession:
    def __init__(self, planner, request: str) -> None:
        self.p = planner
        self.messages: list[dict] = [{"role": "user", "content": request}]
        self.last_id: str | None = None

    def next(self, step: dict | None) -> dict:
        if step is not None and self.last_id:
            content = json.dumps(step.get("result") or {"error": step.get("error")}, default=str)
            self.messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": self.last_id,
                            "content": content[:6000],
                        }
                    ],
                }
            )
        reply = self.p.client.messages.create(
            model=self.p.model,
            max_tokens=1024,
            system=SYSTEM,
            tools=self.p.tools,
            messages=self.messages,
        )
        self.messages.append({"role": "assistant", "content": reply.content})
        use = next((b for b in reply.content if b.type == "tool_use"), None)
        if use is not None:
            self.last_id = use.id
            return {"tool": use.name, "args": dict(use.input)}
        text = " ".join(b.text for b in reply.content if b.type == "text").strip()
        return {"answer": text, "sources": re.findall(r"SOP-\d{2}", text)}


class ClaudePlanner:
    name = "claude"

    def __init__(self, client, model: str, registry) -> None:
        self.client, self.model = client, model
        self.tools = [
            {"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
            for t in registry.schema()
        ]

    def start(self, request: str) -> _ClaudeSession:
        return _ClaudeSession(self, request)


def make_planner(provider: str = "", api_key: str = "", model: str = "", registry=None):
    """Claude when configured, else the offline playbooks (also when the SDK is missing)."""
    if provider == "anthropic" and api_key:
        try:
            import anthropic

            from ai.agents.tools import ToolRegistry

            client = anthropic.Anthropic(api_key=api_key)
            return ClaudePlanner(client, model or "claude-sonnet-5-5", registry or ToolRegistry())
        except ImportError:
            pass
    return OfflinePlanner()

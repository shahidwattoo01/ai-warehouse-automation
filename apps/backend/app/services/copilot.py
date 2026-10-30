"""Operator copilot (Phase 6): plain-language commands for the live warehouse.

    message ──► parser (DistilBERT, else TF-IDF, else rules) ──► intent + entities + tool call
            ──► checks against the live warehouse (robot exists, order waiting, aisle safe ...)
            ──► read-only tool: answered at once
                write tool:     proposed; runs only after the operator approves it

Write actions go through the same simulator commands as the UI buttons (never direct state
changes), and every executed action is kept in an audit trail. Parsing runs in a worker thread;
everything that touches the engine runs on the event loop (see app/services/simulator.py).
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import threading
import time
import uuid
from collections import deque
from pathlib import Path

from ai.nlp.commands import INTENTS
from app.services.knowledge import knowledge
from simulation.environment.engine import Command, SimulationEngine
from simulation.events.events import Event

log = logging.getLogger(__name__)

MODELS = Path(__file__).resolve().parents[4] / "models"
TICK_SECONDS = 0.5  # robot time per tick at 1x (1 cell = 1 m -> 2 m/s)
ACTION_TTL_S = 300  # a proposal not approved within 5 minutes expires
EVENT_MEMORY = 50  # recent events kept per robot / order (for "why is R7 stuck?")
# Below this intent confidence a write proposal is flagged "not sure": in notebook 11 intents
# with confidence 0.5-0.9 were right only ~55 % of the time (above 0.99: 98.5 %).
SURE_CONFIDENCE = 0.9


def load_parser():
    """The best available parser: DistilBERT (notebook 11), TF-IDF (notebook 10) or rules.
    WAREHOUSE_NLP_MODEL=tfidf|rules forces a simpler one."""
    choice = os.environ.get("WAREHOUSE_NLP_MODEL", "transformer").lower()
    folder = MODELS / "nlp_distilbert_v1"
    if choice == "transformer" and folder.exists():
        try:
            from ai.transformers.intent_transformer import TransformerParser

            return TransformerParser.load(folder)
        except Exception:  # transformers missing or an incompatible folder: fall back
            log.exception("Could not load %s; using a simpler parser", folder)
    tfidf = MODELS / "nlp_tfidf_v1.joblib"
    if choice in ("transformer", "tfidf") and tfidf.exists():
        import joblib

        from ai.nlp.intent_parser import TfidfParser

        parser = TfidfParser()
        parser.model = joblib.load(tfidf)["model"]
        return parser
    from ai.nlp.intent_parser import RuleParser

    return RuleParser()


class Copilot:
    def __init__(self) -> None:
        self.parser = None
        self._loading = False
        self._lock = threading.Lock()
        self.actions: dict[str, dict] = {}  # proposals waiting for approval
        self.history: deque[dict] = deque(maxlen=200)  # audit trail of answered / executed commands
        self.events: dict[str, deque] = {}
        self.engine: SimulationEngine | None = None
        self.rng = random.Random(0)

    # ----- lifecycle -------------------------------------------------------------------------
    def attach(self, engine: SimulationEngine) -> None:
        """Follow a (new) engine: keep its recent events per robot and order."""
        self.engine = engine
        self.events = {}
        self.actions.clear()
        engine.events.subscribe(self._on_event)

    def _on_event(self, event: Event) -> None:
        if event.entity_id:
            self.events.setdefault(event.entity_id, deque(maxlen=EVENT_MEMORY)).append(event)

    def warm_up(self) -> None:
        """Load the parser in the background (DistilBERT takes a few seconds)."""
        with self._lock:
            if self.parser is None and not self._loading:
                self._loading = True
                threading.Thread(target=self._load, daemon=True).start()

    def _load(self) -> None:
        parser = load_parser()
        with self._lock:
            self.parser, self._loading = parser, False

    def status(self) -> dict:
        p = self.parser
        return {
            "loaded": p is not None,
            "algorithm": getattr(p, "name", None),
            "intents": INTENTS,
            "write_actions_need_approval": True,
        }

    # ----- understanding ---------------------------------------------------------------------
    async def parse(self, text: str) -> dict:
        if self.parser is None:
            await asyncio.to_thread(self._ensure_loaded)
        return await asyncio.to_thread(self.parser.parse, text)

    def _ensure_loaded(self) -> None:
        if self.parser is None:
            self._load()

    def problems(self, result: dict) -> list[str]:
        """What the live warehouse says against this command (empty = it can run)."""
        eng = self.engine
        out: list[str] = []
        for call in result["tool_calls"]:
            a = call["arguments"]
            if "robot_id" in a and a["robot_id"] not in eng.robots:
                out.append(f"There is no robot {a['robot_id']} (robots are R1-R{len(eng.robots)}).")
                continue
            robot = eng.robots.get(a.get("robot_id", ""))
            name = call["name"]
            if name == "pause_robot" and robot.status.value == "PAUSED":
                out.append(f"{robot.robot_id} is already paused.")
            if name == "resume_robot" and robot.status.value != "PAUSED":
                out.append(f"{robot.robot_id} is not paused (it is {robot.status.value.lower()}).")
            if name == "assign_order":
                order = eng.orders.get(a["order_id"])
                if order is None:
                    out.append(f"There is no order {a['order_id']}.")
                elif order.status.value != "PENDING":
                    out.append(f"{a['order_id']} is already {order.status.value.lower()}.")
                elif reason := eng.controller.unavailable_reason(robot):
                    out.append(f"{robot.robot_id} cannot take it: {reason}.")
            if name in ("get_inventory", "create_order"):
                for pid in (
                    [a["product_id"]]
                    if name == "get_inventory"
                    else [i["product_id"] for i in a["items"]]
                ):
                    if pid not in eng.inventory:
                        out.append(f"There is no product {pid} in this warehouse.")
            if name == "create_order":
                for item in a["items"]:
                    stock = eng.inventory.stock.get(item["product_id"])
                    if stock is not None and stock < item["quantity"]:
                        out.append(f"{item['product_id']} has only {stock} in stock.")
            if name in ("close_aisle", "open_aisle"):
                aisle_ids = {x.aisle_id for x in eng.layout.aisles}
                if a["aisle_id"] not in aisle_ids:
                    n = len(aisle_ids)
                    out.append(f"There is no aisle {int(a['aisle_id'][-2:])} (aisles 1-{n}).")
                elif name == "close_aisle":
                    if a["aisle_id"] in eng.hazards.closures:
                        out.append(f"{_aisle(a['aisle_id'])} is already closed.")
                    elif blockers := eng.hazards.blockers(a["aisle_id"]):
                        why = ", ".join(blockers)
                        out.append(f"Closing {_aisle(a['aisle_id'])} now would trap work: {why}.")
                elif a["aisle_id"] not in eng.hazards.closures:
                    out.append(f"{_aisle(a['aisle_id'])} is not closed.")
            if name == "reroute_robot":
                if not robot.route:
                    out.append(f"{robot.robot_id} is not driving anywhere right now.")
                elif not a.get("avoid") and not a.get("avoid_zone"):
                    out.append(
                        "Rerouting supports avoiding aisles or a zone; say which ones to avoid."
                    )
        return out

    async def chat(self, text: str, user: str = "system") -> dict:
        """Understand a message; answer read-only commands, propose write commands."""
        result = await self.parse(text)
        reply: dict = {"understanding": result, "problems": [], "action": None, "answer": None}
        if result["status"] != "ok":
            reply["answer"] = result["question"]
        elif problems := self.problems(result):
            reply["problems"] = problems
            reply["answer"] = " ".join(problems)
        elif result["requires_approval"]:
            self._expire()
            action_id = uuid.uuid4().hex[:12]
            self.actions[action_id] = {
                "id": action_id,
                "text": text,
                "tool_calls": result["tool_calls"],
                "created": time.time(),
                "asked_by": user,
            }
            summary = describe(result["tool_calls"])
            unsure = result["confidence"] < SURE_CONFIDENCE
            reply["action"] = {"id": action_id, "summary": summary, "unsure": unsure}
            reply["answer"] = (
                f"I am not sure I understood ({result['confidence']:.0%}). Did you mean: "
                f"{summary}? Approve only if that is right."
                if unsure
                else f"I will {summary}. Approve?"
            )
        else:
            knowledge_answer = None
            for call in result["tool_calls"]:
                if call["name"] == "search_knowledge":  # ~1 s of CPU: off the event loop
                    knowledge_answer = await knowledge.ask(call["arguments"]["query"])
            reply["answer"], reply["data"] = self.run_read(result["tool_calls"], knowledge_answer)
            self._log(text, result["tool_calls"], "answered", user)
        return reply

    # ----- approval --------------------------------------------------------------------------
    def pending(self, action_id: str) -> dict | None:
        self._expire()
        return self.actions.get(action_id)

    def approve(self, action_id: str, user: str = "system") -> dict:
        self._expire()
        action = self.actions.pop(action_id, None)
        if action is None:
            return {"ok": False, "answer": "That action expired or was already handled; ask again."}
        # The warehouse may have changed since the proposal: check again before acting.
        problems = self.problems({"tool_calls": action["tool_calls"]})
        if problems:
            return {"ok": False, "answer": " ".join(problems)}
        answer = self.run_write(action["tool_calls"])
        self._log(
            action["text"],
            action["tool_calls"],
            "approved and executed",
            action.get("asked_by"),
            user,
        )
        return {"ok": True, "answer": answer}

    def reject(self, action_id: str, user: str = "system") -> dict:
        action = self.actions.pop(action_id, None)
        if action:
            self._log(
                action["text"], action["tool_calls"], "rejected", action.get("asked_by"), user
            )
        return {"ok": True, "answer": "Cancelled, nothing was changed."}

    def _expire(self) -> None:
        now = time.time()
        for key in [k for k, a in self.actions.items() if now - a["created"] > ACTION_TTL_S]:
            del self.actions[key]

    def _log(
        self, text: str, calls: list[dict], outcome: str, asked_by=None, decided_by=None
    ) -> None:
        self.history.appendleft(
            {
                "tick": self.engine.time,
                "text": text,
                "tool_calls": calls,
                "outcome": outcome,
                "asked_by": asked_by,
                "decided_by": decided_by,
            }
        )

    # ----- tools -----------------------------------------------------------------------------
    def run_write(self, calls: list[dict]) -> str:
        eng = self.engine
        done = []
        for call in calls:
            a, name = call["arguments"], call["name"]
            if name in ("pause_robot", "resume_robot"):
                eng.submit(Command(name, {"robot_id": a["robot_id"]}))
            elif name == "assign_order":
                eng.submit(
                    Command("assign_order", {"order_id": a["order_id"], "robot_id": a["robot_id"]})
                )
            elif name == "create_order":
                order_id = eng.next_order_id()
                eng.submit(
                    Command(
                        "create_order",
                        {
                            "order_id": order_id,
                            "priority": a["priority"],
                            "items": a["items"],
                            "robot_id": None,
                        },
                    )
                )
                done.append(f"created {order_id}")
                continue
            elif name == "set_assignment_mode":
                eng.submit(Command("set_assignment_mode", {"auto": a["mode"] == "auto"}))
            elif name == "close_aisle":
                eng.submit(
                    Command("close_aisle", {"aisle_id": a["aisle_id"], "reason": a["reason"]})
                )
            elif name == "open_aisle":
                eng.submit(Command("open_aisle", {"aisle_id": a["aisle_id"]}))
            elif name == "reroute_robot":
                eng.submit(Command("reroute_robot", a))
            done.append(describe([call]))
        if not eng.running:  # commands are applied at the start of the next tick
            return "Queued: " + "; ".join(done) + ". It takes effect when the simulation runs."
        return "Done: " + "; ".join(done) + "."

    def run_read(self, calls: list[dict], knowledge_answer: dict | None = None) -> tuple[str, dict]:
        eng = self.engine
        answers, data = [], {}
        for call in calls:
            a, name = call["arguments"], call["name"]
            if name == "get_robot_status":
                r = eng.robots[a["robot_id"]]
                act = eng.controller.activity(r)
                data[r.robot_id] = {**r.to_dict(), **act}
                answers.append(
                    f"{r.robot_id} is {r.status.value.lower()} at {tuple(r.position)}, battery "
                    f"{r.battery:.0f} %, heading to {act['destination']}."
                )
            elif name == "get_pending_orders":
                pending = [
                    o
                    for o in eng.orders.values()
                    if o.status.value == "PENDING"
                    and ("priority" not in a or o.priority.value == a["priority"])
                ]
                pending.sort(key=lambda o: o.order_time)
                label = f"{a['priority'].lower()}-priority " if "priority" in a else ""
                ids = ", ".join(o.order_id for o in pending[:5])
                answers.append(
                    f"{len(pending)} {label}orders are waiting"
                    + (f", oldest: {ids}." if ids else ".")
                )
                data["pending"] = [o.to_dict() for o in pending[:20]]
            elif name == "get_inventory":
                pid = a["product_id"]
                answers.append(f"{pid}: {eng.inventory.stock[pid]} units in stock.")
            elif name == "get_warehouse_state":
                s = eng.state(include_inventory=False)
                busy = sum(r["status"] not in ("IDLE", "PARKED") for r in s["robots"])
                pending = sum(o["status"] == "PENDING" for o in s["orders"])
                k = s["kpis"]
                answers.append(
                    f"{busy} of {len(s['robots'])} robots busy, {pending} orders waiting, "
                    f"{k['orders_completed']} delivered ({k['late_percent']:.0f} % late), "
                    f"{len(s['closures'])} aisles closed."
                )
            elif name == "get_events":
                events = list(self.events.get(a["entity_id"], []))[-5:]
                text = "; ".join(
                    f"tick {e.tick}: {e.type.value.lower().replace('_', ' ')}" for e in events
                )
                answers.append(
                    f"Recent events for {a['entity_id']}: {text}."
                    if events
                    else f"No recent events for {a['entity_id']}."
                )
            elif name == "calculate_route":
                answers.append(self._route_answer(a))
            elif name == "search_knowledge" and knowledge_answer is not None:
                answers.append(knowledge_answer["answer"])
                data["knowledge"] = knowledge_answer
        return " ".join(answers), data

    def _route_answer(self, a: dict) -> str:
        eng = self.engine
        robot = eng.robots[a["robot_id"]]
        goal = self._place(a.get("destination"))
        if goal is None:
            if not robot.route:
                return f"{robot.robot_id} has no route right now."
            left = len(robot.route)
            return (
                f"{robot.robot_id} has {left} m left on its route (~{left * TICK_SECONDS:.0f} s)."
            )
        avoid = eng.cells_to_avoid(a)  # the same rule as the reroute command
        # Own random generator: a question must never change the simulation's random sequence.
        path = eng.planner.plan(eng.layout.grid, robot.position, goal, avoid or None, rng=self.rng)
        if not path:
            return f"No route from {robot.robot_id} to {a['destination']} right now."
        avoiding = f" avoiding {', '.join(a['avoid'])}" if a.get("avoid") else ""
        seconds = len(path) * TICK_SECONDS
        where = f"{robot.robot_id} → {a['destination']}"
        return f"{where}: {len(path)} m, about {seconds:.0f} s of driving{avoiding}."

    def _place(self, name: str | None):
        if not name:
            return None
        eng = self.engine
        for s in eng.layout.stations:
            if s.station_id == name:
                return (s.x, s.y)
        for area in eng.layout.parking_areas:
            if area.area_id == name and area.cells:
                return area.cells[0]
        return eng.inventory.face.get(f"P-{name}") or eng.inventory.face.get(name)


def _aisle(aisle_id: str) -> str:
    return f"Aisle {int(aisle_id[-2:])}"


def describe(calls: list[dict]) -> str:
    """Plain-language summary of tool calls (what the approval card says)."""
    return "; ".join(_describe_one(c["name"], c["arguments"]) for c in calls)


def _describe_one(name: str, a: dict) -> str:
    if name in ("pause_robot", "resume_robot"):
        return f"{name.split('_')[0]} {a['robot_id']}"
    if name == "assign_order":
        return f"assign {a['order_id']} to {a['robot_id']}"
    if name == "create_order":
        items = ", ".join(f"{i['quantity']} × {i['product_id']}" for i in a["items"])
        return f"create a {a['priority'].lower()}-priority order for {items}"
    if name == "set_assignment_mode":
        return f"switch order assignment to {a['mode']}"
    if name == "close_aisle":
        return f"close {_aisle(a['aisle_id'])} ({a['reason']})"
    if name == "open_aisle":
        return f"reopen {_aisle(a['aisle_id'])}"
    if name == "reroute_robot":
        avoid = [_aisle(x) for x in a.get("avoid", [])]
        if a.get("avoid_zone"):
            avoid.append(a["avoid_zone"].replace("_", " ").title())
        return f"reroute {a['robot_id']} avoiding {', '.join(avoid)}"
    return name.replace("_", " ")


copilot = Copilot()

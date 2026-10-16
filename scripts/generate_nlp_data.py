"""Operator-command dataset for NLP (intent + entities) and tool calling (Phases 6 and 8).

    python scripts/generate_nlp_data.py

Writes data/processed/nlp/:
    commands.jsonl   one operator message per line:
                       text, intent, entities (type, canonical value, character span),
                       tokens + BIO tags (for token-classification models),
                       tool_calls (the backend tool(s) the copilot should call, with arguments),
                       requires_approval, template_id, split
    (the tool catalogue the tool calls refer to is written to data/processed/agents/tools.json)
    labels.json      intent and entity label lists

Messages are built from many phrasing templates per intent, filled with real warehouse entities
(robots R1-R40, packing stations, aisles, zones, real product IDs and rack locations), with
operator-style noise: lower case, missing punctuation, polite or terse wording, small typos.

Split: templates, not rows. About one template in five per intent is held out, and every message
built from it goes to the test split, so the test set measures understanding of new phrasings
rather than memorised sentences. The rest is split 90/10 into train/validation at random.
"""

from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simulation.inventory.catalog import build_catalog  # noqa: E402
from simulation.warehouse.layout import load_layout  # noqa: E402

OUT = ROOT / "data" / "processed" / "nlp"
AGENTS = ROOT / "data" / "processed" / "agents"
SEED = 61
PER_TEMPLATE = 40  # messages generated per template
TEST_TEMPLATE_SHARE = 0.2

# ----- tool catalogue ---------------------------------------------------------------------
ROBOT = {"type": "string", "pattern": "^R([1-9]|[1-3][0-9]|40)$", "description": "Robot ID, R1-R40"}
ORDER = {"type": "string", "pattern": "^O[0-9]{5}$", "description": "Order ID, e.g. O00125"}
AISLE = {"type": "string", "pattern": "^AISLE_[0-9]{2}$", "description": "AISLE_01 - AISLE_52"}
TOOLS = [
    (
        "get_robot_status",
        "Position, status, battery, temperature, task and route of one robot.",
        {"robot_id": ROBOT},
        ["robot_id"],
        False,
    ),
    (
        "get_pending_orders",
        "Orders waiting for a robot, optionally filtered by priority.",
        {"priority": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]}},
        [],
        False,
    ),
    (
        "get_inventory",
        "Stock, location and restocking status of one product.",
        {"product_id": {"type": "string", "pattern": "^P-[A-D]-[0-9]{2}-[0-9]{2}$"}},
        ["product_id"],
        False,
    ),
    (
        "calculate_route",
        "Plan (but do not apply) a route for a robot to a destination.",
        {
            "robot_id": ROBOT,
            "destination": {
                "type": "string",
                "description": "PACK_1-6, CHG_1-4, parking area P1-P8 or a rack location "
                "such as A-05-12",
            },
            "avoid": {"type": "array", "items": AISLE},
        },
        ["robot_id", "destination"],
        False,
    ),
    (
        "assign_order",
        "Give a waiting order to a free robot (validated by the simulator).",
        {"robot_id": ROBOT, "order_id": ORDER},
        ["robot_id", "order_id"],
        True,
    ),
    (
        "reroute_robot",
        "Plan and apply a new route for a robot, optionally avoiding aisles.",
        {
            "robot_id": ROBOT,
            "destination": {"type": "string"},
            "avoid": {"type": "array", "items": AISLE},
        },
        ["robot_id"],
        True,
    ),
    (
        "pause_robot",
        "Stop a robot where it is (status PAUSED).",
        {"robot_id": ROBOT},
        ["robot_id"],
        True,
    ),
    (
        "resume_robot",
        "Let a paused robot continue its task.",
        {"robot_id": ROBOT},
        ["robot_id"],
        True,
    ),
    (
        "get_warehouse_state",
        "Fleet and order summary: KPIs, robot counts by status, queue, closures.",
        {},
        [],
        False,
    ),
    (
        "get_events",
        "Event history of one robot, order, aisle or hazard (assignments, faults, delays).",
        {"entity_id": {"type": "string"}, "since_tick": {"type": "integer", "minimum": 0}},
        ["entity_id"],
        False,
    ),
    (
        "close_aisle",
        "Close an aisle to all robots (restricted zone) for a reason.",
        {
            "aisle_id": AISLE,
            "reason": {
                "type": "string",
                "enum": ["maintenance", "spill cleanup", "rack inspection", "operator request"],
            },
        },
        ["aisle_id"],
        True,
    ),
    ("open_aisle", "Reopen a closed aisle.", {"aisle_id": AISLE}, ["aisle_id"], True),
    (
        "set_assignment_mode",
        "Switch order assignment between automatic and manual.",
        {"mode": {"type": "string", "enum": ["auto", "manual"]}},
        ["mode"],
        True,
    ),
    (
        "create_order",
        "Create an order (operator order) for products and quantities.",
        {
            "priority": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]},
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "product_id": {"type": "string"},
                        "quantity": {"type": "integer", "minimum": 1},
                    },
                },
            },
        },
        ["items"],
        True,
    ),
    (
        "search_knowledge",
        "Search the warehouse documents (manuals, safety rules, SOPs, policies).",
        {"query": {"type": "string"}},
        ["query"],
        False,
    ),
]

INTENTS = [
    "robot_status", "pending_orders", "inventory_query", "route_planning", "assign_order",
    "reroute_robot", "pause_robot", "resume_robot", "fleet_overview", "task_assignment",
    "close_aisle", "open_aisle", "set_assignment_mode", "create_order", "investigate_delay",
    "knowledge_query", "out_of_scope",
]  # fmt: skip
ENTITY_TYPES = [
    "ROBOT", "ORDER", "PRODUCT", "LOCATION", "STATION", "CHARGER", "PARKING", "AISLE", "ZONE",
    "PRIORITY", "QUANTITY", "REASON", "MODE",
]  # fmt: skip

# ----- templates --------------------------------------------------------------------------
# {slot} markers are filled by SLOTS below; each yields (surface text, entity type, value).
T: dict[str, list[str]] = {
    "robot_status": [
        "what is the status of {robot}",
        "where is {robot} right now",
        "show me {robot}",
        "battery level of {robot}?",
        "is {robot} charging",
        "what is {robot} doing",
        "how hot is {robot} running",
        "give me the details for {robot}",
        "check {robot} please",
        "{robot} status",
        "is {robot} carrying anything",
        "what task is {robot} on",
    ],
    "pending_orders": [
        "show pending orders",
        "how many orders are waiting",
        "list the {priority} orders in the queue",
        "are there any {priority} orders waiting",
        "what's in the order queue",
        "pending {priority} orders?",
        "how many {priority} priority orders are still unassigned",
        "show me orders nobody has picked up yet",
        "which orders are waiting for a robot",
        "queue length?",
    ],
    "inventory_query": [
        "how many units of {product} are left",
        "stock of {product}",
        "check inventory for {product}",
        "is {product} in stock",
        "what's the stock level at {location}",
        "how much is left in bay {location}",
        "is a restock coming for {product}",
        "where is {product} stored",
        "units on hand for {product}?",
        "do we still have {product}",
    ],
    "route_planning": [
        "find a route for {robot} to {station}",
        "plan a path from {robot} to {station}",
        "find a less congested route for {robot} to {station}",
        "how would {robot} get to {location}",
        "route {robot} to {charger}, just show me",
        "what's the best way for {robot} to reach {parking}",
        "calculate a route for {robot} to {station} avoiding {aisle}",
        "show the path {robot} would take to {location}",
    ],
    "assign_order": [
        "assign {order} to {robot}",
        "give {order} to {robot}",
        "let {robot} take {order}",
        "{robot} should pick {order}",
        "put {order} on {robot}",
        "please assign order {order} to {robot}",
        "can {robot} handle {order}",
        "send {robot} to do {order}",
        "{order} -> {robot}",
    ],
    "reroute_robot": [
        "reroute {robot} to avoid {aisle}",
        "send {robot} around {aisle}",
        "{robot} must avoid {aisle}",
        "change {robot}'s route, keep it out of {aisle}",
        "reroute {robot}",
        "find {robot} another way",
        "move {robot} to {parking}",
        "send {robot} to {charger} now",
        "get {robot} out of {zone}",
    ],
    "pause_robot": [
        "pause {robot}",
        "stop {robot}",
        "stop {robot} immediately",
        "halt {robot}",
        "{robot} needs to stop now",
        "freeze {robot}",
        "emergency stop {robot}",
        "hold {robot} where it is",
        "pause {robot} please, someone is in the aisle",
    ],
    "resume_robot": [
        "resume {robot}",
        "restart {robot}",
        "let {robot} continue",
        "unpause {robot}",
        "{robot} can go again",
        "release {robot}",
        "{robot} is clear, resume it",
        "start {robot} again",
    ],
    "fleet_overview": [
        "how many robots are currently active",
        "give me a fleet overview",
        "what's the throughput",
        "how many robots are charging",
        "summary of the warehouse",
        "how is the warehouse doing",
        "what is the late percentage today",
        "average completion time?",
        "how many robots are idle",
        "status report",
        "any aisles closed right now",
    ],
    "task_assignment": [
        "move all {priority} orders to {station}",
        "prioritise all {priority} orders",
        "send every {priority} order to {station}",
        "handle the {priority} orders first",
        "all {priority} orders should go to {station}",
        "prioritize urgent orders",
        "focus the fleet on {priority} orders",
        "process {priority} orders at {station}",
    ],
    "close_aisle": [
        "close {aisle}",
        "close {aisle} for {reason}",
        "avoid {aisle}",
        "block {aisle}, we have a {reason}",
        "shut {aisle} for {reason}",
        "keep all robots out of {aisle}",
        "{aisle} is closed for {reason}",
        "restrict {aisle}",
        "no robots in {aisle} until further notice",
    ],
    "open_aisle": [
        "reopen {aisle}",
        "open {aisle} again",
        "{aisle} is clear now",
        "unblock {aisle}",
        "robots can use {aisle} again",
        "lift the closure on {aisle}",
        "{aisle} cleanup is done, open it",
    ],
    "set_assignment_mode": [
        "switch to {mode} assignment",
        "set assignment mode to {mode}",
        "go {mode}",
        "I want to assign orders by hand",
        "let the dispatcher assign orders automatically again",
        "turn on {mode} mode",
        "change dispatch to {mode}",
    ],
    "create_order": [
        "create a {priority} order for {quantity} units of {product}",
        "new order: {quantity} x {product}",
        "make an order for {product}, {priority} priority",
        "add a {priority} order with {quantity} of {product}",
        "order {quantity} {product} urgently",
        "place an order for {product}",
        "create order {quantity} units {product} priority {priority}",
    ],
    "investigate_delay": [
        "why is {robot} delayed",
        "why was {order} late",
        "what's wrong with {robot}",
        "why is {robot} so slow",
        "why hasn't {order} been delivered yet",
        "{robot} seems stuck, why",
        "explain the delay on {order}",
        "why did {robot} stop",
    ],
    "knowledge_query": [
        "what is the battery safety procedure",
        "what should happen when a robot's battery is critical",
        "what do we do when a robot overheats",
        "how do I close an aisle safely",
        "what is the procedure for a dropped parcel",
        "who may enter a closed aisle",
        "what PPE do I need on the robot floor",
        "what is the reorder point for products",
        "how often are cameras calibrated",
        "what's the procedure for a stopped robot",
        "how do we prepare for black friday",
        "what is a restricted zone",
        "when can a paused robot be resumed",
        "how long does charging take",
    ],
    "out_of_scope": [
        "what's the weather in lahore",
        "tell me a joke",
        "book a flight to dubai",
        "who won the cricket match",
        "write me a poem",
        "what's the price of bitcoin",
        "translate hello to french",
        "order me a pizza",
        "what time is it in new york",
        "play some music",
    ],
}

TOOL_OF = {
    "robot_status": "get_robot_status", "pending_orders": "get_pending_orders",
    "inventory_query": "get_inventory", "route_planning": "calculate_route",
    "assign_order": "assign_order", "reroute_robot": "reroute_robot", "pause_robot": "pause_robot",
    "resume_robot": "resume_robot", "fleet_overview": "get_warehouse_state",
    "close_aisle": "close_aisle", "open_aisle": "open_aisle",
    "set_assignment_mode": "set_assignment_mode", "create_order": "create_order",
    "knowledge_query": "search_knowledge",
}  # fmt: skip
NUMBER_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
                "ten", "eleven", "twelve"]  # fmt: skip
PRIORITY_WORDS = {
    "HIGH": ["high", "HIGH", "high-priority", "urgent", "express", "rush"],
    "MEDIUM": ["medium", "MEDIUM", "normal", "standard"],
    "LOW": ["low", "LOW", "low-priority", "non-urgent"],
}
REASON_WORDS = {
    "maintenance": ["maintenance", "repairs"],
    "spill cleanup": ["spill cleanup", "spill", "cleaning"],
    "rack inspection": ["rack inspection", "inspection"],
}


class Builder:
    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        layout = load_layout("large")
        self.products = sorted(build_catalog(layout))
        self.aisles = [a.aisle_id for a in layout.aisles]

    # Each slot returns (surface text, entity type, canonical value).
    def robot(self) -> tuple[str, str, str]:
        n = self.rng.randint(1, 40)
        fmt = self.rng.choice(["R{n}", "R{n}", "robot {n}", "Robot {n}", "robot R{n}", "r{n}",
                               "bot {n}", "AMR {n}", "R-{n}", "robot #{n}"])  # fmt: skip
        return fmt.format(n=n), "ROBOT", f"R{n}"

    def order(self) -> tuple[str, str, str]:
        n = self.rng.randint(1, 2500)
        fmt = self.rng.choice(
            ["O{n:05d}", "O{n:05d}", "order {n}", "order O{n:05d}", "#{n}", "o{n:05d}"]
        )
        return fmt.format(n=n), "ORDER", f"O{n:05d}"

    def product(self) -> tuple[str, str, str]:
        pid = self.rng.choice(self.products)
        text = pid if self.rng.random() < 0.8 else pid.lower()
        return text, "PRODUCT", pid

    def location(self) -> tuple[str, str, str]:
        loc = self.rng.choice(self.products).removeprefix("P-")
        return loc, "LOCATION", loc

    def station(self) -> tuple[str, str, str]:
        n = self.rng.randint(1, 6)
        fmt = self.rng.choice(["PACK_{n}", "packing station {n}", "pack {n}", "station {n}",
                               "Packing Station {n}", "packing {n}"])  # fmt: skip
        return fmt.format(n=n), "STATION", f"PACK_{n}"

    def charger(self) -> tuple[str, str, str]:
        n = self.rng.randint(1, 4)
        fmt = self.rng.choice(["CHG_{n}", "charger {n}", "charging station {n}", "Charger {n}"])
        return fmt.format(n=n), "CHARGER", f"CHG_{n}"

    def parking(self) -> tuple[str, str, str]:
        n = self.rng.randint(1, 8)
        fmt = self.rng.choice(["P{n}", "parking area P{n}", "parking P{n}", "parking area {n}"])
        return fmt.format(n=n), "PARKING", f"P{n}"

    def aisle(self) -> tuple[str, str, str]:
        aid = self.rng.choice(self.aisles)
        n = int(aid[-2:])
        words = [f"Aisle {n}", f"aisle {n}", aid, f"aisle no. {n}", f"Aisle {n:02d}"]
        if n < len(NUMBER_WORDS):
            words.append(f"aisle {NUMBER_WORDS[n]}")
        return self.rng.choice(words), "AISLE", aid

    def zone(self) -> tuple[str, str, str]:
        z = self.rng.choice("ABCD")
        return self.rng.choice([f"zone {z}", f"Zone {z}", f"ZONE_{z}"]), "ZONE", f"ZONE_{z}"

    def priority(self) -> tuple[str, str, str]:
        value = self.rng.choice(["HIGH", "HIGH", "MEDIUM", "LOW"])
        return self.rng.choice(PRIORITY_WORDS[value]), "PRIORITY", value

    def quantity(self) -> tuple[str, str, str]:
        n = self.rng.randint(1, 12)
        text = NUMBER_WORDS[n] if self.rng.random() < 0.25 else str(n)
        return text, "QUANTITY", str(n)

    def reason(self) -> tuple[str, str, str]:
        value = self.rng.choice(list(REASON_WORDS))
        return self.rng.choice(REASON_WORDS[value]), "REASON", value

    def mode(self) -> tuple[str, str, str]:
        value = self.rng.choice(["auto", "manual"])
        words = {"auto": ["auto", "automatic"], "manual": ["manual"]}[value]
        return self.rng.choice(words), "MODE", value

    # ----- one message -------------------------------------------------------------------
    def fill(self, template: str) -> tuple[str, list[dict]]:
        text, entities, pos = "", [], 0
        for m in re.finditer(r"\{(\w+)\}", template):
            text += template[pos : m.start()]
            surface, etype, value = getattr(self, m.group(1))()
            entities.append(
                {
                    "type": etype,
                    "value": value,
                    "start": len(text),
                    "end": len(text) + len(surface),
                    "text": surface,
                }  # fmt: skip
            )
            text += surface
            pos = m.end()
        return text + template[pos:], entities

    def noise(self, text: str, entities: list[dict]) -> tuple[str, list[dict]]:
        """Operator-style variation that never touches entity spans."""
        rng = self.rng
        prefix = rng.choice(["", "", "", "please ", "hey copilot, ", "quick one: ", "copilot, "])
        suffix = rng.choice(["", "", "", "?", ".", " please", " asap", " thanks", " now"])
        if text.endswith(("?", ".")) and suffix in ("?", "."):
            suffix = ""
        protected = [(e["start"], e["end"]) for e in entities]
        chars = list(text)
        if rng.random() < 0.12:  # one typo: swap two letters outside entities
            spots = [i for i in range(len(chars) - 1)
                     if chars[i].isalpha() and chars[i + 1].isalpha()
                     and not any(s - 1 <= i < e for s, e in protected)]  # fmt: skip
            if spots:
                i = rng.choice(spots)
                chars[i], chars[i + 1] = chars[i + 1], chars[i]
        text = "".join(chars)
        if rng.random() < 0.5:
            text = text[:1].upper() + text[1:]
        text = prefix + text + suffix
        for e in entities:
            e["start"] += len(prefix)
            e["end"] += len(prefix)
            e["text"] = text[e["start"] : e["end"]]  # capitalisation may have changed it
        return text, entities


def tool_calls(intent: str, entities: list[dict], text: str) -> list[dict]:
    v = {}
    for e in entities:
        v.setdefault(e["type"], []).append(e["value"])
    one = {k: vals[0] for k, vals in v.items()}
    if intent == "out_of_scope":
        return []
    if intent == "investigate_delay":
        if "ROBOT" in one:
            return [
                {"name": "get_robot_status", "arguments": {"robot_id": one["ROBOT"]}},
                {"name": "get_events", "arguments": {"entity_id": one["ROBOT"]}},
            ]
        return [{"name": "get_events", "arguments": {"entity_id": one["ORDER"]}}]
    if intent == "task_assignment":
        args = {"priority": one.get("PRIORITY", "HIGH")}
        return [{"name": "get_pending_orders", "arguments": args}]
    name = TOOL_OF[intent]
    args: dict = {}
    if intent in ("robot_status", "pause_robot", "resume_robot", "assign_order"):
        args["robot_id"] = one["ROBOT"]
    if intent == "assign_order":
        args["order_id"] = one["ORDER"]
    if intent == "pending_orders" and "PRIORITY" in one:
        args["priority"] = one["PRIORITY"]
    if intent == "inventory_query":
        args["product_id"] = one.get("PRODUCT") or f"P-{one['LOCATION']}"
    if intent in ("route_planning", "reroute_robot"):
        args["robot_id"] = one["ROBOT"]
        dest = one.get("STATION") or one.get("CHARGER") or one.get("PARKING") or one.get("LOCATION")
        if dest:
            args["destination"] = dest
        if "AISLE" in v:
            args["avoid"] = v["AISLE"]
        if "ZONE" in one:
            args["avoid_zone"] = one["ZONE"]
    if intent in ("close_aisle", "open_aisle"):
        args["aisle_id"] = one["AISLE"]
    if intent == "close_aisle":
        args["reason"] = one.get("REASON", "operator request")
    if intent == "set_assignment_mode":
        mode = one.get("MODE")
        if mode is None:
            mode = "manual" if "by hand" in text.lower() else "auto"
        args["mode"] = mode
    if intent == "create_order":
        args["priority"] = one.get("PRIORITY", "HIGH" if "urgent" in text.lower() else "MEDIUM")
        args["items"] = [{"product_id": one["PRODUCT"], "quantity": int(one.get("QUANTITY", 1))}]
    if intent == "knowledge_query":
        args["query"] = text
    return [{"name": name, "arguments": args}]


TOKEN = re.compile(r"[A-Za-z0-9_#]+(?:[-.'][A-Za-z0-9_]+)*|[^\sA-Za-z0-9_]")


def bio(text: str, entities: list[dict]) -> tuple[list[str], list[str]]:
    tokens, tags = [], []
    for m in TOKEN.finditer(text):
        tag = "O"
        for e in entities:
            if e["start"] <= m.start() < e["end"]:
                tag = ("B-" if m.start() == e["start"] or not tags or tags[-1] == "O"
                       or tags[-1][2:] != e["type"] else "I-") + e["type"]  # fmt: skip
                break
        tokens.append(m.group())
        tags.append(tag)
    return tokens, tags


WRITE_TOOLS = {name for name, *_, write in TOOLS if write}


def main() -> None:
    rng = random.Random(SEED)
    builder = Builder(rng)
    rows, seen = [], set()
    for intent in INTENTS:
        templates = T[intent]
        order = list(range(len(templates)))
        rng.shuffle(order)
        held_out = set(order[: max(1, round(len(templates) * TEST_TEMPLATE_SHARE))])
        for t_index, template in enumerate(templates):
            for _ in range(PER_TEMPLATE):
                core, entities = builder.fill(template)
                text, entities = builder.noise(core, entities)
                if text.lower() in seen:
                    continue
                seen.add(text.lower())
                for e in entities:
                    assert text[e["start"] : e["end"]] == e["text"], (text, e)
                tokens, tags = bio(text, entities)
                calls = tool_calls(intent, entities, core)
                split = (
                    "test"
                    if t_index in held_out
                    else ("validation" if rng.random() < 0.1 else "train")
                )
                rows.append(
                    {
                        "id": f"CMD-{len(rows) + 1:05d}",
                        "text": text,
                        "intent": intent,
                        "entities": entities,
                        "tokens": tokens,
                        "bio_tags": tags,
                        "tool_calls": calls,
                        "requires_approval": any(c["name"] in WRITE_TOOLS for c in calls),
                        "template_id": f"{intent}-{t_index:02d}",
                        "split": split,
                    }
                )
    rng.shuffle(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "commands.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tools = [
        {
            "name": name,
            "description": desc,
            "parameters": {"type": "object", "properties": props, "required": req},
            "is_write": write,
            "requires_approval": write,
        }
        for name, desc, props, req, write in TOOLS
    ]
    (AGENTS / "tools.json").parent.mkdir(parents=True, exist_ok=True)
    (AGENTS / "tools.json").write_text(json.dumps(tools, indent=2), encoding="utf-8")
    (OUT / "labels.json").write_text(
        json.dumps(
            {
                "intents": INTENTS,
                "entity_types": ENTITY_TYPES,
                "bio_tags": ["O"] + [f"{p}-{t}" for t in ENTITY_TYPES for p in "BI"],
            },
            indent=2,
        ),  # fmt: skip
        encoding="utf-8",
    )
    splits = {s: sum(r["split"] == s for r in rows) for s in ("train", "validation", "test")}
    print(f"{len(rows)} commands, {len(INTENTS)} intents, {len(TOOLS)} tools, splits {splits}")


if __name__ == "__main__":
    main()

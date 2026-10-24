"""Operator commands (Phase 6): the shared rules between the dataset, the models and the app.

An operator message is understood in three steps:

    "send R-36 around aisle 2 now"
      1. intent      reroute_robot                              (a classifier)
      2. entities    ROBOT "R-36" · AISLE "aisle 2"             (a tagger: which words are what)
      3. tool call   reroute_robot(robot_id="R36", avoid=["AISLE_02"])   (rules, this module)

Step 3 is deterministic: `normalize` turns each entity's words into its canonical value ("R-36"
-> "R36", "aisle two" -> "AISLE_02") and `tool_calls` builds the backend call from the intent and
the values. The dataset generator (scripts/generate_nlp_data.py) uses the same functions to write
the labels, so a model is scored against exactly the calls the app would make.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "processed" / "nlp" / "commands.jsonl"

INTENTS = [
    "robot_status", "pending_orders", "inventory_query", "route_planning", "assign_order",
    "reroute_robot", "pause_robot", "resume_robot", "fleet_overview", "task_assignment",
    "close_aisle", "open_aisle", "set_assignment_mode", "create_order", "investigate_delay",
    "knowledge_query", "out_of_scope",
]  # fmt: skip
ENTITY_TYPES = ["ROBOT", "ORDER", "PRODUCT", "LOCATION", "STATION", "CHARGER", "PARKING", "AISLE",
                "ZONE", "PRIORITY", "QUANTITY", "REASON", "MODE"]  # fmt: skip
BIO_TAGS = ["O"] + [f"{p}-{t}" for t in ENTITY_TYPES for p in ("B", "I")]

TOOL_OF = {
    "robot_status": "get_robot_status", "pending_orders": "get_pending_orders",
    "inventory_query": "get_inventory", "route_planning": "calculate_route",
    "assign_order": "assign_order", "reroute_robot": "reroute_robot", "pause_robot": "pause_robot",
    "resume_robot": "resume_robot", "fleet_overview": "get_warehouse_state",
    "close_aisle": "close_aisle", "open_aisle": "open_aisle",
    "set_assignment_mode": "set_assignment_mode", "create_order": "create_order",
    "knowledge_query": "search_knowledge",
}  # fmt: skip
# Tools that change the warehouse: the operator must approve them before they run.
WRITE_TOOLS = {"assign_order", "close_aisle", "create_order", "open_aisle", "pause_robot",
               "reroute_robot", "resume_robot", "set_assignment_mode"}  # fmt: skip

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
MODE_WORDS = {"auto": ["auto", "automatic"], "manual": ["manual"]}

# Words and punctuation; IDs like "P-C-29-03" or "AISLE_02" stay one token.
TOKEN = re.compile(r"[A-Za-z0-9_#]+(?:[-.'][A-Za-z0-9_]+)*|[^\sA-Za-z0-9_]")


# ----- tokens and BIO tags -------------------------------------------------------------------
def tokenize(text: str) -> list[tuple[str, int, int]]:
    """(token, start, end) for every token of `text`."""
    return [(m.group(), m.start(), m.end()) for m in TOKEN.finditer(text)]


def bio(text: str, entities: list[dict]) -> tuple[list[str], list[str]]:
    """Tokens and their BIO tags (B- = first token of an entity, I- = inside, O = outside)."""
    tokens, tags = [], []
    for token, start, _ in tokenize(text):
        tag = "O"
        for e in entities:
            if e["start"] <= start < e["end"]:
                tag = ("B-" if start == e["start"] or not tags or tags[-1] == "O"
                       or tags[-1][2:] != e["type"] else "I-") + e["type"]  # fmt: skip
                break
        tokens.append(token)
        tags.append(tag)
    return tokens, tags


def spans_from_bio(text: str, tags: list[str]) -> list[dict]:
    """Entity spans (type, start, end, text) from one BIO tag per token of `text`. An I- tag
    continues the previous entity of the same type; anything else starts a new one."""
    spans: list[dict] = []
    previous = "O"
    for (_, start, end), tag in zip(tokenize(text), tags, strict=False):
        if tag != "O":
            kind, etype = tag.split("-", 1)
            if kind == "I" and previous != "O" and previous[2:] == etype and spans:
                spans[-1]["end"] = end
            else:
                spans.append({"type": etype, "start": start, "end": end})
        previous = tag
    for span in spans:
        if text[span["start"] : span["end"]].endswith(
            "'s"
        ):  # "robot R14's route": the robot is "robot R14"
            span["end"] -= 2
        span["text"] = text[span["start"] : span["end"]]
    return spans


# ----- canonical values ----------------------------------------------------------------------
def _number(surface: str) -> int | None:
    digits = re.findall(r"\d+", surface)
    if digits:
        return int(digits[-1])
    for word in reversed(re.findall(r"[a-z]+", surface.lower())):
        if word in NUMBER_WORDS:
            return NUMBER_WORDS.index(word)
    return None


def _lookup(words: dict[str, list[str]], surface: str) -> str | None:
    s = surface.lower()
    for value, options in words.items():  # longest phrases first ("low-priority" before "low")
        if any(s == o.lower() for o in options):
            return value
    for value, options in sorted(words.items(), key=lambda kv: -max(len(o) for o in kv[1])):
        if any(o.lower() in s for o in sorted(options, key=len, reverse=True)):
            return value
    return None


def normalize(etype: str, surface: str) -> str | None:
    """Canonical value of an entity, e.g. ("ROBOT", "AMR 20") -> "R20", ("AISLE", "aisle two")
    -> "AISLE_02". None when the words cannot be one (the model tagged something odd)."""
    if etype in ("PRODUCT", "LOCATION"):
        value = surface.strip().upper()
        if etype == "PRODUCT" and not value.startswith("P-"):
            value = "P-" + value
        return value
    if etype == "PRIORITY":
        return _lookup(PRIORITY_WORDS, surface)
    if etype == "REASON":
        return _lookup(REASON_WORDS, surface)
    if etype == "MODE":
        return _lookup(MODE_WORDS, surface)
    if etype == "ZONE":
        m = re.search(r"([A-Da-d])\s*$", surface.strip())
        return f"ZONE_{m.group(1).upper()}" if m else None
    n = _number(surface)
    if n is None:
        return None
    return {
        "ROBOT": f"R{n}", "ORDER": f"O{n:05d}", "STATION": f"PACK_{n}", "CHARGER": f"CHG_{n}",
        "PARKING": f"P{n}", "AISLE": f"AISLE_{n:02d}", "QUANTITY": str(n),
    }.get(etype)  # fmt: skip


# ----- tool calls ----------------------------------------------------------------------------
def mentions(text: str, phrase: str) -> bool:
    """`phrase` occurs in `text`, also with one pair of neighbouring letters swapped (the most
    common typing slip: "by ahnd", "ugrently")."""
    low = text.lower()
    variants = {phrase} | {
        phrase[:i] + phrase[i + 1] + phrase[i] + phrase[i + 2 :]
        for i in range(len(phrase) - 1)
        if phrase[i].isalpha() and phrase[i + 1].isalpha()
    }
    return any(v in low for v in variants)


def tool_calls(intent: str, entities: list[dict], text: str) -> list[dict]:
    """The backend tool call(s) for an intent and its entities (each with a canonical 'value').

    Raises KeyError when a required entity is missing (e.g. pause_robot without a robot): the
    caller should then ask the operator instead of guessing."""
    v: dict[str, list[str]] = {}
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
        return [
            {"name": "get_pending_orders", "arguments": {"priority": one.get("PRIORITY", "HIGH")}}
        ]
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
            mode = "manual" if mentions(text, "by hand") else "auto"
        args["mode"] = mode
    if intent == "create_order":
        args["priority"] = one.get("PRIORITY", "HIGH" if mentions(text, "urgent") else "MEDIUM")
        args["items"] = [{"product_id": one["PRODUCT"], "quantity": int(one.get("QUANTITY", 1))}]
    if intent == "knowledge_query":
        args["query"] = text
    return [{"name": name, "arguments": args}]


def requires_approval(calls: list[dict]) -> bool:
    return any(c["name"] in WRITE_TOOLS for c in calls)


def same_calls(predicted: list[dict], expected: list[dict]) -> bool:
    """Exact match of tool calls. search_knowledge is compared by name only: its query is the
    operator's free text (the label holds the text before typos and filler were added)."""
    if len(predicted) != len(expected):
        return False
    for p, e in zip(predicted, expected, strict=True):
        if p["name"] != e["name"]:
            return False
        if p["name"] != "search_knowledge" and p["arguments"] != e["arguments"]:
            return False
    return True


# ----- data ----------------------------------------------------------------------------------
def load_commands(path: Path = DATA) -> pd.DataFrame:
    """The command dataset (scripts/generate_nlp_data.py), one row per message."""
    return pd.read_json(path, lines=True)


def honest_validation(df: pd.DataFrame, share: float = 0.2, seed: int = 0) -> pd.Series:
    """A validation split that holds out whole *templates* of the training split.

    The dataset's own validation rows share templates with training, so scores on them reward
    memorised phrasings; the test split holds out templates. This makes validation do the same:
    about `share` of each intent's training templates (at least one) become validation.
    Returns the new split label per row ('train' / 'validation' / 'test')."""
    rng = np.random.default_rng(seed)
    split = df["split"].where(df["split"] == "test", "train")
    trainable = df[split == "train"]
    held: set[str] = set()
    for _, group in trainable.groupby("intent"):
        templates = sorted(group["template_id"].unique())
        k = max(1, round(len(templates) * share))
        held |= set(rng.choice(templates, size=min(k, len(templates) - 1) or 1, replace=False))
    return split.mask(df["template_id"].isin(held) & (split == "train"), "validation")

"""Classical baselines for operator commands (Phase 6): what any learned model must beat.

    RuleParser    keyword rules for the intent + regular expressions for the entities
    TfidfParser   TF-IDF (word 1-2-grams + character 2-5-grams) + Logistic Regression for the
                  intent, the same regular expressions for the entities

Character n-grams make the TF-IDF model tolerant to typos ("critiacl" still shares most
fragments with "critical"). Both return `ai.nlp.understanding.understand` results.
"""

from __future__ import annotations

import re

import numpy as np

from ai.nlp.commands import NUMBER_WORDS, PRIORITY_WORDS, REASON_WORDS
from ai.nlp.understanding import understand

NUM = "|".join(NUMBER_WORDS)
# Entity patterns, tried in this order; a later match may not overlap an earlier one.
ENTITY_PATTERNS: list[tuple[str, str]] = [
    ("PRODUCT", r"\bP-[A-D]-\d{2}-\d{2}\b"),
    ("LOCATION", r"(?<!P-)\b[A-D]-\d{2}-\d{2}\b"),
    ("ROBOT", r"\b(?:robot|bot|AMR)\s*(?:#|R-?)?\d{1,2}\b|\bR-?\d{1,2}\b"),
    ("ORDER", r"\border\s+O?\d{1,5}\b|\bO\d{5}\b|(?<![\w#])#\d{1,5}\b"),
    ("STATION", r"\b(?:PACK_\d|packing station \d|packing \d|pack \d|station \d)\b"),
    ("CHARGER", r"\b(?:CHG_\d|charging station \d|charger \d)\b"),
    ("PARKING", r"\b(?:parking area P?\d|parking P\d|P[1-8])\b"),
    ("AISLE", rf"\b(?:AISLE_\d{{2}}|aisle (?:no\. )?(?:\d{{1,2}}|{NUM}))\b"),
    ("ZONE", r"\b(?:ZONE_[A-D]|zone [A-D])\b"),
    (
        "PRIORITY",
        r"(?<![\w-])(?:"
        + "|".join(
            sorted(
                {re.escape(w) for ws in PRIORITY_WORDS.values() for w in ws}, key=len, reverse=True
            )
        )
        + r")(?![\w-])",
    ),  # fmt: skip
    ("QUANTITY", rf"\b(?:\d{{1,2}}|{NUM})\b(?=\s+(?:units?|pieces?|pcs|x\b|of\b|items?))"),
    (
        "REASON",
        r"\b(?:"
        + "|".join(
            sorted(
                {re.escape(w) for ws in REASON_WORDS.values() for w in ws}, key=len, reverse=True
            )
        )
        + r")\b",
    ),  # fmt: skip
    ("MODE", r"\b(?:automatic|auto|manual)\b"),
]
COMPILED = [(t, re.compile(p, re.IGNORECASE)) for t, p in ENTITY_PATTERNS]


def regex_entities(text: str) -> list[dict]:
    """Entity spans found by the patterns above (no overlaps), in text order."""
    taken: list[tuple[int, int]] = []
    spans = []
    for etype, pattern in COMPILED:
        for m in pattern.finditer(text):
            if any(m.start() < e and s < m.end() for s, e in taken):
                continue
            taken.append((m.start(), m.end()))
            spans.append({"type": etype, "start": m.start(), "end": m.end(), "text": m.group()})
    return sorted(spans, key=lambda s: s["start"])


# Intent keyword rules: the first rule whose pattern matches wins.
INTENT_RULES: list[tuple[str, str]] = [
    ("out_of_scope", r"\b(pizza|weather|joke|music|movie|football|new york|recipe|translate)\b"),
    (
        "knowledge_query",
        r"\b(what should|procedure|policy|how do i|what is the rule|safety rule|manual|sop)\b",
    ),
    ("investigate_delay", r"\b(why|stuck|delayed|late|slow|taking so long)\b"),
    (
        "set_assignment_mode",
        r"\b(assignment mode|dispatcher|manual mode|auto mode"
        r"|assign orders (automatically|by hand|manually))\b",
    ),
    ("create_order", r"\b(create|new|place|add)\b.*\border\b|\border \d+ (units|x)\b|\bunits of\b"),
    ("assign_order", r"\b(assign|give)\b.*\border\b|\border\b.*\bto (robot|r-?\d)"),
    ("close_aisle", r"\b(close|block|shut|lock)\b.*\baisle\b|\baisle\b.*\b(closed|off limits)\b"),
    ("open_aisle", r"\b(open|reopen|unblock|unlock)\b.*\baisle\b"),
    ("pause_robot", r"\b(pause|stop|halt|freeze|hold)\b"),
    ("resume_robot", r"\b(resume|continue|restart|unpause|start again|carry on)\b"),
    ("reroute_robot", r"\b(reroute|re-route|avoid|keep (it )?out|around|detour|change .*route)\b"),
    ("route_planning", r"\b(route|path|way|how long|get to|drive to|send)\b"),
    ("task_assignment", r"\b(which orders|what should .* do next|next task|priorit)"),
    ("pending_orders", r"\b(pending|waiting|queue|backlog|open orders)\b"),
    ("inventory_query", r"\b(stock|inventory|how many|units of|in stock|left of)\b"),
    (
        "fleet_overview",
        r"\b(fleet|all robots|overview|warehouse status|summary|how is the warehouse)\b",
    ),
    ("robot_status", r"\b(status|where is|battery|doing|location of|how is)\b"),
]
INTENT_COMPILED = [(i, re.compile(p, re.IGNORECASE)) for i, p in INTENT_RULES]


class RuleParser:
    name = "Rules (keywords + regex)"

    def parse(self, text: str) -> dict:
        intent = next((i for i, p in INTENT_COMPILED if p.search(text)), "robot_status")
        return understand(text, intent, 1.0, regex_entities(text))


class TfidfParser:
    name = "TF-IDF + Logistic Regression (+ regex entities)"

    def __init__(self) -> None:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import FeatureUnion, make_pipeline

        words = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=1)
        chars = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), sublinear_tf=True, min_df=2)
        features = FeatureUnion([("words", words), ("chars", chars)])
        self.model = make_pipeline(features, LogisticRegression(C=10.0, max_iter=2000))

    def fit(self, texts: list[str], intents: list[str]) -> TfidfParser:
        self.model.fit(texts, intents)
        return self

    def intent_proba(self, texts: list[str]) -> tuple[list[str], np.ndarray]:
        proba = self.model.predict_proba(texts)
        classes = self.model.classes_
        return [classes[i] for i in proba.argmax(1)], proba.max(1)

    def parse(self, text: str) -> dict:
        intents, conf = self.intent_proba([text])
        return understand(text, intents[0], conf[0], regex_entities(text))

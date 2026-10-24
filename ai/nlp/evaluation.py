"""Scoring operator-command parsers (Phase 6, notebooks 10-11).

For each message the parser's result (ai.nlp.understanding) is compared with the labels:

    intent        accuracy and macro F1 (every intent counts the same, rare or not)
    entities      precision / recall / F1 of (type, canonical value) pairs: "robot R36" counts as
                  correct whatever words were used, as long as the value is right
    tool call     exact match of the whole call (name and every argument; search_knowledge by
                  name, see ai.nlp.commands.same_calls). The strictest score: what the app runs.
    approval      the write / read-only flag is right (a write action must never skip approval)

Robustness: the same test messages with extra noise that keeps entity positions (letter case,
one more typo outside the entities) show how much a parser depends on clean input.
"""

from __future__ import annotations

import random
import time
from collections import Counter
from collections.abc import Callable

import pandas as pd
from sklearn.metrics import accuracy_score, f1_score

from ai.nlp.commands import same_calls


def _pairs(entities: list[dict]) -> Counter:
    return Counter((e["type"], e["value"]) for e in entities)


def evaluate(
    parse: Callable[[str], dict],
    df: pd.DataFrame,
    texts: list[str] | None = None,
    parse_many: Callable[[list[str]], list[dict]] | None = None,
) -> dict:
    """Scores of `parse` on the rows of `df` (optionally on other `texts` with the same labels).
    `parse_many`, if given, parses all messages in one batch (faster for neural networks)."""
    texts = list(df["text"]) if texts is None else texts
    start = time.perf_counter()
    results = parse_many(texts) if parse_many else [parse(t) for t in texts]
    ms = (time.perf_counter() - start) * 1000 / max(len(texts), 1)
    tp = fp = fn = 0
    exact = approval = 0
    for res, row in zip(results, df.itertuples(), strict=True):
        got, want = _pairs(res["entities"]), _pairs(row.entities)
        both = got & want
        tp += sum(both.values())
        fp += sum((got - want).values())
        fn += sum((want - got).values())
        exact += (
            same_calls(res["tool_calls"], row.tool_calls) and res["status"] != "needs_information"
        )
        approval += res["requires_approval"] == row.requires_approval
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    pred = [r["intent"] for r in results]
    return {
        "intent_accuracy": accuracy_score(df["intent"], pred),
        "intent_macro_F1": f1_score(df["intent"], pred, average="macro"),
        "entity_precision": precision,
        "entity_recall": recall,
        "entity_F1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "exact_tool_call": exact / len(df),
        "approval_correct": approval / len(df),
        "ms_per_message": ms,
        "predictions": pred,
        "results": results,
    }


def summary(scores: dict) -> dict:
    """The numeric scores only (for tables and reports)."""
    return {k: round(v, 4) for k, v in scores.items() if isinstance(v, float)}


def noisy(df: pd.DataFrame, seed: int = 0) -> list[str]:
    """Test messages with extra operator noise that keeps entity character positions: random
    letter case outside entities, and one more swap of two neighbouring letters outside them."""
    rng = random.Random(seed)
    out = []
    for row in df.itertuples():
        chars = list(row.text)
        protected = set()
        for e in row.entities:
            protected |= set(range(e["start"] - 1, e["end"] + 1))
        style = rng.choice(["lower", "upper", "keep"])
        for i, c in enumerate(chars):
            if i not in protected:
                chars[i] = c.lower() if style == "lower" else c.upper() if style == "upper" else c
        spots = [i for i in range(len(chars) - 1) if chars[i].isalpha() and chars[i + 1].isalpha()
                 and i not in protected and i + 1 not in protected]  # fmt: skip
        if spots:
            i = rng.choice(spots)
            chars[i], chars[i + 1] = chars[i + 1], chars[i]
        out.append("".join(chars))
    return out

"""Scores for retrieval and answers against data/processed/rag/questions.jsonl.

Every question cites the sections that answer it ("sops#SOP-04"); 6 are unanswerable (no
source). Retrieval metrics only use the answerable ones:

* hit@k: at least one cited section is in the top k chunks (enough for most questions)
* all@k: every cited section is in the top k (what a multi-hop question needs)
* MRR: 1 / rank of the first relevant chunk (1.0 = always first)
* cite@1: the best chunk's section (the citation shown first) is a right section
* words_read: words in the top k chunks (what an answer writer has to read; longer chunks find
  more but cite less precisely and cost more LLM input)

"Not covered" is a yes/no decision on the best retrieval score; it is scored on all questions.
"""

from __future__ import annotations

import json
import random
import re
import time
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
QUESTIONS = ROOT / "data" / "processed" / "rag" / "questions.jsonl"


def load_questions(path: Path = QUESTIONS) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def split_questions(questions: list[dict], dev_share: float = 0.4, seed: int = 0) -> dict:
    """Development / test split, stratified by question type: settings (chunking, retriever,
    thresholds) are chosen on dev; test is scored once at the end."""
    rng = random.Random(seed)
    out: dict[str, list[dict]] = {"dev": [], "test": []}
    by_type: dict[str, list[dict]] = {}
    for q in questions:
        by_type.setdefault(q["type"], []).append(q)
    for group in by_type.values():
        group = group[:]
        rng.shuffle(group)
        n_dev = round(len(group) * dev_share)
        out["dev"] += group[:n_dev]
        out["test"] += group[n_dev:]
    return out


def retrieval_scores(search, questions: list[dict], k: int = 5) -> dict:
    """search(question) -> list of Hit (best first)."""
    hit, full, rr, cite, words, per_type, ms = [], [], [], [], [], {}, []
    for q in questions:
        if not q["sources"]:
            continue
        start = time.perf_counter()
        hits = search(q["question"])[:k]
        ms.append((time.perf_counter() - start) * 1000)
        found = {(h.chunk.doc_id, s) for h in hits for s in h.chunk.sections}
        wanted = {tuple(s.split("#")) for s in q["sources"]}
        rel = [any((h.chunk.doc_id, s) in wanted for s in h.chunk.sections) for h in hits]
        hit.append(any(rel))
        full.append(wanted <= found)
        rr.append(1 / (rel.index(True) + 1) if any(rel) else 0.0)
        # The citation is the first chunk's section: is it one of the right sections?
        cite.append(bool(hits) and (hits[0].chunk.doc_id, hits[0].chunk.section_id) in wanted)
        words.append(sum(len(h.chunk.text.split()) for h in hits))
        per_type.setdefault(q["type"], []).append(any(rel))
    return {
        f"hit@{k}": round(float(np.mean(hit)), 3),
        f"all@{k}": round(float(np.mean(full)), 3),
        "MRR": round(float(np.mean(rr)), 3),
        "cite@1": round(float(np.mean(cite)), 3),
        "words_read": round(float(np.mean(words))),
        **{f"hit@{k} {t}": round(float(np.mean(v)), 3) for t, v in sorted(per_type.items())},
        "ms_per_question": round(float(np.mean(ms)), 1),
        "questions": len(hit),
    }


def normalise(text: str) -> list[str]:
    text = re.sub(r"\[[A-Z]{2,4}-[\d.]+\]", " ", text)  # drop citation markers
    return re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", text.lower())


def token_f1(prediction: str, reference: str) -> float:
    """Word overlap between an answer and the reference answer (SQuAD-style F1)."""
    p, r = normalise(prediction), normalise(reference)
    common = sum((Counter(p) & Counter(r)).values())
    if not p or not r or common == 0:
        return 0.0
    precision, recall = common / len(p), common / len(r)
    return 2 * precision * recall / (precision + recall)


def cited_sections(answer: str) -> set[str]:
    return set(re.findall(r"\[([A-Z]{2,4}-[\d.]+)\]", answer))


def answer_scores(answer_fn, questions: list[dict]) -> dict:
    """answer_fn(question) -> {"answer": str, "covered": bool, "sources": [...]}."""
    f1, cite_ok, recall, covered_right, ms = [], [], [], [], []
    for q in questions:
        start = time.perf_counter()
        out = answer_fn(q["question"])
        ms.append((time.perf_counter() - start) * 1000)
        answerable = bool(q["sources"])
        covered_right.append(out["covered"] == answerable)
        if not answerable or not out["covered"]:
            continue
        f1.append(token_f1(out["answer"], q["answer"]))
        cited = cited_sections(out["answer"]) or {s["section_id"] for s in out["sources"][:1]}
        wanted = {s.split("#")[1] for s in q["sources"]}
        cite_ok.append(bool(cited & wanted))
        recall.append(len(cited & wanted) / len(wanted))
    return {
        "covered_decision_right": round(float(np.mean(covered_right)), 3),
        "answer_token_F1": round(float(np.mean(f1)), 3) if f1 else None,
        "cites_a_right_section": round(float(np.mean(cite_ok)), 3) if cite_ok else None,
        "cited_source_recall": round(float(np.mean(recall)), 3) if recall else None,
        "ms_per_question": round(float(np.mean(ms)), 1),
        "questions": len(questions),
    }

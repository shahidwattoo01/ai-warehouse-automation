"""Phase 7 RAG: PDF chunking recovers the documents' sections, retrieval and fusion behave,
answers come only from the documents with their citations, and "not covered" is respected.

A hashed bag-of-words embedder stands in for the MiniLM model, so no download is needed.
"""

import json
import re

import numpy as np
import pytest

from ai.embeddings.embedder import HashEmbedder
from ai.rag.evaluation import (
    cited_sections,
    load_questions,
    retrieval_scores,
    split_questions,
    token_f1,
)
from ai.rag.ingest import PDF_DIR, ROOT, load_chunks
from ai.rag.pipeline import NOT_COVERED_ANSWER, KnowledgeBase, Settings
from ai.rag.retriever import BM25, Retriever, rrf, section_text, sentences, tokens

SECTIONS = ROOT / "data" / "processed" / "rag" / "sections.jsonl"
OVERHEATING = "overheating robot pause it at the next safe stop and reassign its order"  # SOP-04
needs_pdfs = pytest.mark.skipif(not (PDF_DIR / "sops.pdf").exists(), reason="no PDFs")


@pytest.fixture(scope="module")
def chunks():
    return load_chunks("section")


@pytest.fixture(scope="module")
def retriever(chunks):
    return Retriever(chunks, HashEmbedder(), mode="hybrid")


@needs_pdfs
def test_pdf_chunking_recovers_every_numbered_section(chunks):
    with SECTIONS.open(encoding="utf-8") as f:
        truth = {f"{s['doc_id']}#{s['section_id']}" for s in map(json.loads, f)}
    assert {c.chunk_id for c in chunks} == truth
    sop = next(c for c in chunks if c.section_id == "SOP-04")
    assert sop.heading == "Overheating robot" and "\n- " in sop.text  # bullets cleaned


@needs_pdfs
def test_fixed_windows_overlap_and_know_their_sections():
    windows = load_chunks("fixed", size=40, overlap=10)
    assert all(len(w.text.split()) <= 40 and w.sections for w in windows)
    first, second = windows[0].text.split(), windows[1].text.split()
    assert first[-10:] == second[:10]  # 10 words of overlap


def test_tokens_keep_ids_whole_and_split():
    assert {"sop-04", "sop", "04", "chg_3", "chg"} <= set(tokens("SOP-04 and CHG_3"))
    assert "the" not in tokens("the robot")


def test_bm25_prefers_rare_matching_words():
    scores = BM25(["robot battery low", "robot robot robot", "overheating motor"]).scores(
        "overheating robot"
    )
    assert np.argmax(scores) == 2  # "overheating" is rare, "robot" is everywhere


def test_reciprocal_rank_fusion_rewards_agreement():
    fused = rrf([[1, 2, 3], [2, 1, 4]])  # 1 and 2 are near the top of both lists
    assert fused[1] == fused[2] > fused[3] == fused[4] > 0


@needs_pdfs
def test_the_right_section_ranks_first_and_doc_type_filters(retriever):
    hits = retriever.search(OVERHEATING, k=3)
    assert hits[0].chunk.section_id == "SOP-04"
    only_safety = retriever.search("robot", k=5, doc_type="safety")
    assert {h.chunk.doc_type for h in only_safety} == {"safety"}


@needs_pdfs
def test_answers_quote_the_documents_and_cite_them(chunks, retriever):
    kb = KnowledgeBase(chunks, retriever, Settings(retriever="hybrid", threshold=0.0))
    out = kb.ask(OVERHEATING)
    assert out["covered"] and "[SOP-04]" in out["answer"]
    words = set(" ".join(c.text for c in chunks).lower().split())
    answer_words = re.sub(r"\[[A-Z]+-[\d.]+\]| …", "", out["answer"]).lower().split()
    assert set(answer_words) <= words  # extractive: nothing invented
    section = sentences(next(c for c in chunks if c.section_id == "SOP-04"))
    assert section and section_text(chunks[0], max_words=5).endswith("…")


@needs_pdfs
def test_below_the_threshold_the_assistant_says_not_covered(chunks, retriever):
    kb = KnowledgeBase(chunks, retriever, Settings(retriever="hybrid", threshold=99.0))
    out = kb.ask("What is the Wi-Fi password?")
    assert not out["covered"] and out["answer"] == NOT_COVERED_ANSWER
    assert out["sources"]  # the closest passages are still returned for the operator


@needs_pdfs
def test_a_failing_llm_falls_back_to_extractive(chunks, retriever):
    class Broken:
        name = "broken"

        def answer(self, question, hits):
            raise ConnectionError("API down")

    kb = KnowledgeBase(chunks, retriever, Settings(retriever="hybrid", threshold=0.0), Broken())
    out = kb.ask(OVERHEATING)
    assert out["covered"] and out["generator"].startswith("extractive")


def test_evaluation_helpers():
    assert token_f1("the robot is hot [SOP-04]", "robot is hot") == pytest.approx(0.857, 0.01)
    assert cited_sections("a [SOP-04] b [WM-2.1]") == {"SOP-04", "WM-2.1"}
    questions = load_questions()
    split = split_questions(questions, dev_share=0.4, seed=0)
    dev_ids, test_ids = {q["id"] for q in split["dev"]}, {q["id"] for q in split["test"]}
    assert not dev_ids & test_ids and len(dev_ids | test_ids) == len(questions)
    assert {q["type"] for q in split["dev"]} == {q["type"] for q in questions}  # stratified


@needs_pdfs
def test_retrieval_scores_count_hits(retriever):
    q = [{"id": "x", "type": "procedural", "question": OVERHEATING,
          "answer": "", "sources": ["sops#SOP-04"]}]  # fmt: skip
    s = retrieval_scores(lambda text: retriever.search(text, k=3), q, k=3)
    assert s["hit@3"] == 1.0 and s["cite@1"] == 1.0 and s["MRR"] == 1.0


def test_the_llm_writer_is_used_only_when_configured():
    from ai.rag.generator import ClaudeGenerator
    from ai.rag.pipeline import llm_generator

    assert llm_generator({"provider": "", "model": "", "api_key": ""}) is None  # extractive
    claude = llm_generator({"provider": "anthropic", "model": "", "api_key": "test-key"})
    assert isinstance(claude, ClaudeGenerator) and claude.model == "claude-opus-5-5"


def test_code_defaults_match_the_tuned_settings():
    """A fresh clone (models/ is not in git) must behave like the evaluated system."""
    from dataclasses import asdict

    from ai.rag.pipeline import CONFIG

    if not CONFIG.exists():
        pytest.skip("models/rag_v1.json not built (notebooks/12_rag.ipynb)")
    assert asdict(Settings()) == json.loads(CONFIG.read_text(encoding="utf-8"))["settings"]

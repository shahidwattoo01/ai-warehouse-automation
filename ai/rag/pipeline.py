"""The knowledge assistant end to end: question -> retrieve -> covered? -> answer with sources.

    kb = KnowledgeBase.load()                  # settings from models/rag_v1.json (notebook 12)
    kb.ask("What do we do when a robot overheats?")
    -> {"answer": "... [SOP-04]", "covered": True, "sources": [...], "generator": "...", ...}

"Not covered" is decided on the retrieval score before any answer is written: if the best
section scores below the threshold chosen on the development questions, the assistant says the
documents do not cover it instead of answering from a weak match.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

from ai.rag.generator import ClaudeGenerator, ExtractiveGenerator
from ai.rag.ingest import Chunk, load_chunks
from ai.rag.retriever import Hit, Retriever

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "models" / "rag_v1.json"
NOT_COVERED_ANSWER = (
    "The warehouse documents do not cover this. Ask the shift lead, or rephrase the question."
)


@dataclass
class Settings:
    """The values chosen in notebooks/12_rag.ipynb (on development questions), which also writes
    them to models/rag_v1.json; the defaults equal them, so a fresh clone behaves the same."""

    chunking: str = "section"
    retriever: str = "rerank"
    k: int = 3
    candidates: int = 10
    # Minimum score of the best passage to answer. It must be a relevance score: the
    # cross-encoder logit (rerank) or cosine (dense); hybrid's fused score only reflects rank.
    threshold: float = 0.663
    answer_style: str = "section"  # extractive answers: "section" or "sentences"
    embedder: str = "sentence-transformers/all-MiniLM-L6-v2"
    reranker: str = "cross-encoder/ms-marco-MiniLM-L6-v2"

    @classmethod
    def load(cls, path: Path = CONFIG) -> Settings:
        if not path.exists():
            return cls()
        saved = json.loads(path.read_text(encoding="utf-8")).get("settings", {})
        return cls(**{k: v for k, v in saved.items() if k in cls.__dataclass_fields__})


class KnowledgeBase:
    def __init__(
        self,
        chunks: list[Chunk],
        retriever: Retriever,
        settings: Settings,
        generator=None,
    ) -> None:
        self.chunks = chunks
        self.retriever = retriever
        self.settings = settings
        self.extractive = ExtractiveGenerator(self._sentence_scorer(), settings.answer_style)
        self.generator = generator or self.extractive

        self.store = "pgvector" if retriever.vector_index is not None else "memory"

    @classmethod
    def load(
        cls, settings: Settings | None = None, embedder=None, reranker=None, db=None, llm=None
    ):
        """Read the PDFs and build the retriever. `db` (a SQLAlchemy engine): search the stored
        embeddings with pgvector when warehouse_docs holds these chunks, else search in memory.
        `llm`: {"provider", "model", "api_key"} (the backend's settings); default: environment."""
        settings = settings or Settings.load()
        if embedder is None:
            from ai.embeddings.embedder import Embedder

            embedder = Embedder(settings.embedder)
        if reranker is None and settings.retriever == "rerank":
            from sentence_transformers import CrossEncoder

            reranker = CrossEncoder(settings.reranker, device="cpu")
        chunks = load_chunks(settings.chunking)
        retriever = Retriever(
            chunks,
            embedder,
            settings.retriever,
            reranker,
            candidates=settings.candidates,
            vector_index=_pgvector_index(db, chunks),
        )
        return cls(chunks, retriever, settings, generator=llm_generator(llm))

    def _sentence_scorer(self):
        """Cross-encoder when there is one (best), else cosine similarity of embeddings."""
        reranker, embedder = self.retriever.reranker, self.retriever.embedder
        if reranker is not None:
            return lambda q, sentences: reranker.predict([(q, s) for s in sentences])
        return lambda q, sentences: embedder.encode(sentences) @ embedder.encode([q])[0]

    def covered(self, hits: list[Hit]) -> bool:
        return bool(hits) and hits[0].score >= self.settings.threshold

    def ask(self, question: str, doc_type: str | None = None, k: int | None = None) -> dict:
        start = time.perf_counter()
        hits = self.retriever.search(question, k=k or self.settings.k, doc_type=doc_type)
        covered = self.covered(hits)
        answer, generator = None, self.generator
        if covered:
            try:
                answer = generator.answer(question, hits)
            except Exception:  # an LLM outage must not break the page: fall back to extractive
                log.exception("Answer generation failed; using the extractive answer")
                generator = self.extractive
                answer = generator.answer(question, hits)
            covered = answer is not None
        return {
            "question": question,
            "answer": answer if covered else NOT_COVERED_ANSWER,
            "covered": covered,
            "sources": [h.to_dict() for h in hits],
            "generator": generator.name,
            "retriever": self.settings.retriever,
            "ms": round((time.perf_counter() - start) * 1000),
        }


def _pgvector_index(db, chunks: list[Chunk]):
    if db is None:
        return None
    from ai.rag.store import PgVectorIndex, pgvector_ready

    if not pgvector_ready(db):
        return None
    try:
        return PgVectorIndex(db, chunks)
    except ValueError as err:  # stored chunks are stale or empty: search in memory instead
        log.warning("%s", err)
        return None


def llm_generator(llm: dict | None = None):
    """ClaudeGenerator when the provider is "anthropic" (key from the settings, else the SDK's
    usual sources: ANTHROPIC_API_KEY or an `ant auth login` profile); otherwise None, which
    means extractive answers. Without `llm`, LLM_PROVIDER / LLM_MODEL / LLM_API_KEY are read
    from the environment."""
    if llm is None:
        llm = {k: os.environ.get(f"LLM_{k.upper()}", "") for k in ("provider", "model", "api_key")}
    if (llm.get("provider") or "").lower() != "anthropic":
        return None
    try:
        kwargs = {"api_key": llm.get("api_key") or None}
        if llm.get("model"):
            kwargs["model"] = llm["model"]
        return ClaudeGenerator(**kwargs)
    except Exception:
        log.exception("LLM provider anthropic configured but the client could not be created")
        return None

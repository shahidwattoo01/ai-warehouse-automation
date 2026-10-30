"""Knowledge assistant (Phase 7, RAG): answers from the warehouse documents with their sources.

    question ──► retrieve (BM25 + embeddings, cross-encoder rerank; pgvector or in memory)
             ──► best passage scores below the threshold?  → "not covered" (+ closest passages)
             ──► answer: whole best section (extractive) or Claude (LLM_PROVIDER=anthropic)

Settings come from models/rag_v1.json (notebooks/12_rag.ipynb). Models load in a background
thread on first use (a few seconds); answering takes ~1 s of CPU, so it runs in a worker thread
and never blocks the simulator's event loop. One question is answered at a time.
"""

from __future__ import annotations

import asyncio
import logging
import threading

from ai.rag.ingest import DOC_ORDER, DOC_TYPE
from ai.rag.pipeline import KnowledgeBase
from app.core.config import get_settings

log = logging.getLogger(__name__)


class KnowledgeService:
    def __init__(self) -> None:
        self.kb: KnowledgeBase | None = None
        self.error: str | None = None
        self._loading = False
        self._lock = threading.Lock()  # guards loading
        self._ask_lock = threading.Lock()  # one answer at a time (CPU models)

    # ----- lifecycle ---------------------------------------------------------------------------
    def warm_up(self) -> None:
        with self._lock:
            if self.kb is None and not self._loading:
                self._loading = True
                threading.Thread(target=self._load, daemon=True).start()

    def _load(self) -> None:
        try:
            cfg = get_settings()
            llm = {"provider": cfg.llm_provider, "model": cfg.llm_model, "api_key": cfg.llm_api_key}
            kb = KnowledgeBase.load(db=_database(), llm=llm)
            with self._lock:
                self.kb, self.error = kb, None
            log.info("Knowledge base ready: %d chunks, %s search", len(kb.chunks), kb.store)
        except Exception as err:  # missing PDFs or models: report it on /rag/status
            log.exception("Could not load the knowledge base")
            with self._lock:
                self.error = str(err)
        finally:
            with self._lock:
                self._loading = False

    def _ensure_loaded(self) -> KnowledgeBase:
        if self.kb is None:
            self._load()
        if self.kb is None:
            raise RuntimeError(f"knowledge base unavailable: {self.error}")
        return self.kb

    def status(self) -> dict:
        kb = self.kb
        base = {"loaded": kb is not None, "loading": self._loading, "error": self.error}
        if kb is None:
            return base
        s = kb.settings
        return {
            **base,
            "documents": len({c.doc_id for c in kb.chunks}),
            "chunks": len(kb.chunks),
            "store": kb.store,
            "chunking": s.chunking,
            "retriever": s.retriever,
            "generator": kb.generator.name,
            "threshold": s.threshold,
            "embedder": s.embedder,
        }

    # ----- questions ---------------------------------------------------------------------------
    def _ask(self, question: str, doc_type: str | None, k: int | None) -> dict:
        kb = self._ensure_loaded()
        with self._ask_lock:
            return kb.ask(question, doc_type=doc_type, k=k)

    async def ask(self, question: str, doc_type: str | None = None, k: int | None = None) -> dict:
        return await asyncio.to_thread(self._ask, question, doc_type, k)

    def documents(self) -> list[dict]:
        kb = self._ensure_loaded()
        out = []
        for doc_id in DOC_ORDER:
            chunks = [c for c in kb.chunks if c.doc_id == doc_id]
            if chunks:
                out.append(
                    {
                        "doc_id": doc_id,
                        "title": chunks[0].title,
                        "doc_type": DOC_TYPE[doc_id],
                        "sections": [
                            {"section_id": c.section_id, "heading": c.heading} for c in chunks
                        ],
                    }
                )
        return out

    def section(self, section_id: str) -> dict | None:
        kb = self._ensure_loaded()
        chunk = next((c for c in kb.chunks if c.section_id == section_id), None)
        return chunk.to_dict() if chunk else None


def _database():
    """An engine for the configured database, or None (the knowledge base then runs in memory)."""
    try:
        from sqlalchemy import create_engine

        return create_engine(get_settings().database_url, pool_pre_ping=True)
    except Exception:
        return None


knowledge = KnowledgeService()

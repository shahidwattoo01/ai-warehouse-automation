"""pgvector document store: the chunks and their embeddings in PostgreSQL (table warehouse_docs).

    python scripts/ingest_documents.py --db      # PDFs -> chunks -> embeddings -> warehouse_docs

Search uses pgvector's cosine distance operator (`<=>`) with the HNSW index, so it scales to
thousands of documents; for the ~120 chunks here it returns the same ranking as the in-memory
search (a test checks this where pgvector is available).
"""

from __future__ import annotations

import contextlib
import logging

import numpy as np
from sqlalchemy import Connection, Engine, text

from ai.rag.ingest import Chunk

log = logging.getLogger(__name__)


def vector_literal(v: np.ndarray) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


def _connect(bind: Engine | Connection):
    """Use a given connection as is (e.g. inside a test transaction), or open one."""
    return contextlib.nullcontext(bind) if isinstance(bind, Connection) else bind.connect()


def pgvector_ready(engine: Engine | Connection) -> bool:
    """True when the warehouse_docs table exists (migration 003 ran with pgvector installed)."""
    try:
        with _connect(engine) as conn:
            return bool(conn.execute(text("SELECT to_regclass('warehouse_docs')")).scalar())
    except Exception:  # no database, wrong credentials ...
        return False


def ingest(conn: Connection, chunks: list[Chunk], vectors: np.ndarray) -> int:
    """Replace the stored chunks with these. Run it inside one transaction
    (`with engine.begin() as conn`), so readers never see half a set."""
    rows = [
        {
            "embedding": vector_literal(vectors[i]),
            "text": c.text,
            "source": c.doc_id,
            "section": c.section_id,
            "doc_type": c.doc_type,
            "chunk_index": i,
        }
        for i, c in enumerate(chunks)
    ]
    conn.execute(text("DELETE FROM warehouse_docs"))
    conn.execute(
        text(
            "INSERT INTO warehouse_docs (embedding, text, source, section, doc_type,"
            " chunk_index) VALUES (CAST(:embedding AS vector), :text, :source, :section,"
            " :doc_type, :chunk_index)"
        ),
        rows,
    )
    return len(rows)


class PgVectorIndex:
    """Dense search in PostgreSQL. `cosines` returns one value per chunk (in the order of the
    chunk list), -inf for chunks outside the top `limit`."""

    def __init__(self, bind: Engine | Connection, chunks: list[Chunk]) -> None:
        self.bind = bind
        self.size = len(chunks)
        with _connect(bind) as conn:
            stored = conn.execute(
                text("SELECT chunk_index, source, section FROM warehouse_docs ORDER BY chunk_index")
            ).all()
        expected = [(i, c.doc_id, c.section_id) for i, c in enumerate(chunks)]
        if [tuple(r) for r in stored] != expected:
            raise ValueError(
                "warehouse_docs does not match the documents; run scripts/ingest_documents.py --db"
            )

    def cosines(self, query: np.ndarray, limit: int, doc_type: str | None = None) -> np.ndarray:
        sql = (
            "SELECT chunk_index, 1 - (embedding <=> CAST(:q AS vector)) AS cos FROM warehouse_docs"
            + (" WHERE doc_type = :doc_type" if doc_type else "")
            + " ORDER BY embedding <=> CAST(:q AS vector) LIMIT :limit"
        )
        out = np.full(self.size, -np.inf)
        with _connect(self.bind) as conn:
            params = {"q": vector_literal(query), "limit": limit, "doc_type": doc_type}
            for idx, cos in conn.execute(text(sql), params):
                out[idx] = cos
        return out

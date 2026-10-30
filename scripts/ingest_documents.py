"""Ingest the warehouse documents for the knowledge assistant (Phase 7, RAG).

    python scripts/ingest_documents.py          # PDFs -> chunks -> embeddings, print a summary
    python scripts/ingest_documents.py --db     # ... and store them in warehouse_docs (pgvector)

The chunking and embedding model come from models/rag_v1.json (notebooks/12_rag.ipynb). Storing
needs the pgvector extension and migration 003 (`alembic upgrade head`); without pgvector the
backend reads the PDFs itself and searches in memory, so this step is optional.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps" / "backend"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", action="store_true", help="store the chunks in warehouse_docs")
    args = parser.parse_args()

    from ai.embeddings.embedder import Embedder
    from ai.rag.ingest import load_chunks
    from ai.rag.pipeline import Settings

    settings = Settings.load()
    started = time.perf_counter()
    chunks = load_chunks(settings.chunking)
    vectors = Embedder(settings.embedder).encode([c.for_embedding() for c in chunks])
    per_doc = Counter(c.doc_id for c in chunks)
    print(f"{len(chunks)} chunks ({settings.chunking}) from {len(per_doc)} documents, ", end="")
    print(f"{vectors.shape[1]}-dim embeddings in {time.perf_counter() - started:.1f} s")
    for doc_id, n in per_doc.items():
        print(f"  {doc_id:20s} {n:4d}")
    if not args.db:
        return 0

    from sqlalchemy import create_engine

    from ai.rag.store import ingest, pgvector_ready
    from app.core.config import get_settings

    engine = create_engine(get_settings().database_url)
    if not pgvector_ready(engine):
        print("✗ warehouse_docs does not exist: install pgvector and run `alembic upgrade head`")
        return 1
    with engine.begin() as conn:  # one transaction: the old set stays until the new one is in
        stored = ingest(conn, chunks, vectors)
    print(f"✓ stored {stored} chunks in warehouse_docs")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())

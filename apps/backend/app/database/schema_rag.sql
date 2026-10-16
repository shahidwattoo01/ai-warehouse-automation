-- RAG document store (Phase 7). Needs the pgvector extension: https://github.com/pgvector/pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- ===== Vector store (pgvector, TRD decision D3 default) =====
CREATE TABLE warehouse_docs (
  chunk_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  embedding   VECTOR(384) NOT NULL,          -- all-MiniLM-L6-v2 dimension; change with D2
  text        TEXT NOT NULL,
  source      VARCHAR(128) NOT NULL,
  section     VARCHAR(256),
  doc_type    VARCHAR(16) NOT NULL,
  chunk_index INT NOT NULL,
  ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_docs_embedding ON warehouse_docs USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_docs_type      ON warehouse_docs (doc_type);

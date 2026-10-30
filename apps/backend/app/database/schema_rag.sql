-- RAG document store (Phase 7). Needs the pgvector extension: https://github.com/pgvector/pgvector
-- Applied by migration 003 only where the extension is available (the Docker and CI database
-- images have it); without it the backend searches the same chunks in memory.
CREATE EXTENSION IF NOT EXISTS vector;

-- ===== Vector store (pgvector, TRD decision D3 default) =====
CREATE TABLE IF NOT EXISTS warehouse_docs (
  chunk_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  embedding   VECTOR(384) NOT NULL,          -- all-MiniLM-L6-v2 dimension; change with D2
  text        TEXT NOT NULL,
  source      VARCHAR(128) NOT NULL,         -- document id, e.g. sops
  section     VARCHAR(256),                  -- section id, e.g. SOP-04
  doc_type    VARCHAR(16) NOT NULL,          -- manual | safety | maintenance | sop | policy
  chunk_index INT NOT NULL,                  -- position in the ingested chunk list
  ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_docs_embedding ON warehouse_docs USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_docs_type      ON warehouse_docs (doc_type);

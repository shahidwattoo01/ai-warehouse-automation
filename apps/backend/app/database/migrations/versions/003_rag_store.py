"""003 — RAG document store (warehouse_docs, pgvector) from app/database/schema_rag.sql.

Skipped with a warning where the pgvector extension is not installed (e.g. a plain PostgreSQL on
Windows): the knowledge assistant then searches the chunks in memory, with the same results.
"""

import logging
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None

SCHEMA = Path(__file__).resolve().parents[2] / "schema_rag.sql"
log = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    available = op.get_bind().execute(
        sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
    )
    if available.first() is None:
        log.warning("pgvector is not installed: warehouse_docs not created (in-memory search)")
        return
    op.execute(SCHEMA.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS warehouse_docs")

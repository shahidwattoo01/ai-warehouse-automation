"""001 — initial schema from app/database/schema.sql (Backend Schema §10)."""

from pathlib import Path

from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA = Path(__file__).resolve().parents[2] / "schema.sql"


def upgrade() -> None:
    op.execute(SCHEMA.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")

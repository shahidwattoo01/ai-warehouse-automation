"""002 — event types for aisle closures and floor hazards (dataset v3 simulator)."""

from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None

NEW_EVENTS = ["AISLE_CLOSED", "AISLE_OPENED", "HAZARD_DETECTED", "HAZARD_CLEARED"]


def upgrade() -> None:
    for value in NEW_EVENTS:  # no-op on databases created from the updated schema.sql
        op.execute(f"ALTER TYPE event_type_t ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # PostgreSQL cannot drop enum values; the extra values are harmless to older code.
    pass

"""007 — alert-centre incidents (backlog PR-32).

One row per alert incident and run: the rule and subject, severity, and who acknowledged and
resolved it, when; the full history (opened, escalated, acknowledged, resolved, with notes) is
kept as JSON. Upserted as the incident changes.
"""

from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE IF NOT EXISTS alert_incidents (
  run_id          UUID NOT NULL REFERENCES simulation_runs(run_id) ON DELETE CASCADE,
  alert_id        VARCHAR(16) NOT NULL,
  rule            VARCHAR(32) NOT NULL,
  subject         VARCHAR(40) NOT NULL,
  severity        VARCHAR(10) NOT NULL CHECK (severity IN ('critical', 'warning', 'info')),
  title           TEXT NOT NULL,
  status          VARCHAR(14) NOT NULL CHECK (status IN ('OPEN', 'ACKNOWLEDGED', 'RESOLVED')),
  escalated       BOOLEAN NOT NULL DEFAULT false,
  opened_tick     INT NOT NULL,
  acknowledged_by VARCHAR(40),
  acknowledged_at TIMESTAMPTZ,
  resolved_by     VARCHAR(40),
  resolved_tick   INT,
  history         JSONB NOT NULL DEFAULT '[]'::jsonb,
  PRIMARY KEY (run_id, alert_id)
);
CREATE INDEX IF NOT EXISTS idx_alert_incidents_status ON alert_incidents (run_id, status);
""")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS alert_incidents;")

"""006 — the safety event log (backlog PR-23).

Emergency stops with their release and reset, near misses between robots and people, floor
hazards, aisle closures and safety-relevant faults, per simulation run. Append-only: an audit
trail of who stopped and restarted the fleet and why.
"""

from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE IF NOT EXISTS safety_events (
  run_id     UUID NOT NULL REFERENCES simulation_runs(run_id) ON DELETE CASCADE,
  seq        INT NOT NULL,
  tick       INT NOT NULL,
  kind       VARCHAR(24) NOT NULL,
  severity   VARCHAR(10) NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
  text       TEXT NOT NULL,
  robot_id   VARCHAR(16),
  zone       VARCHAR(32),
  x          INT,
  y          INT,
  user_name  VARCHAR(40) NOT NULL,
  detail     JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (run_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_safety_events_kind ON safety_events (run_id, kind, tick);
""")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS safety_events;")

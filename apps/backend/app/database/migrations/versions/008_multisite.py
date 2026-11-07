"""008 — multi-site / 3PL support (backlog PR-33).

Adds:
  clients     — a customer or 3PL client that owns one or more warehouse sites
  sites       — a physical warehouse site, belonging to one client
  users.site_id      — scope a user to one site (NULL = all sites / system admin)
  simulation_runs.site_id — tag a run to its site
"""

from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE IF NOT EXISTS clients (
  client_id   VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
  name        VARCHAR(128) NOT NULL UNIQUE,
  description TEXT,
  active      BOOLEAN NOT NULL DEFAULT true,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sites (
  site_id     VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
  client_id   VARCHAR(36) NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
  name        VARCHAR(128) NOT NULL,
  description TEXT,
  timezone    VARCHAR(64) NOT NULL DEFAULT 'UTC',
  active      BOOLEAN NOT NULL DEFAULT true,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (client_id, name)
);

ALTER TABLE users
  ADD COLUMN IF NOT EXISTS site_id VARCHAR(36) REFERENCES sites(site_id) ON DELETE SET NULL;

ALTER TABLE simulation_runs
  ADD COLUMN IF NOT EXISTS site_id VARCHAR(36) REFERENCES sites(site_id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_sites_client  ON sites(client_id);
CREATE INDEX IF NOT EXISTS ix_users_site    ON users(site_id);
CREATE INDEX IF NOT EXISTS ix_runs_site     ON simulation_runs(site_id);
""")


def downgrade() -> None:
    op.execute("""
ALTER TABLE simulation_runs DROP COLUMN IF EXISTS site_id;
ALTER TABLE users           DROP COLUMN IF EXISTS site_id;
DROP TABLE IF EXISTS sites;
DROP TABLE IF EXISTS clients;
""")

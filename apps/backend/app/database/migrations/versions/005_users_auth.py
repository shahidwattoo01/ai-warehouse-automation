"""005 — users, refresh tokens and the login audit (authentication, backlog PR-01).

Passwords are stored only as Argon2 hashes. Refresh tokens are stored only as SHA-256 hashes, so a
copy of the database cannot be used to log in. Roles and their permissions live in code
(app/core/permissions.py); the role column is checked against that list.
"""

from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE IF NOT EXISTS users (
  user_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  username       VARCHAR(40) NOT NULL,
  full_name      VARCHAR(80) NOT NULL,
  password_hash  TEXT NOT NULL,
  role           VARCHAR(20) NOT NULL
                 CHECK (role IN ('admin', 'supervisor', 'operator', 'inventory_clerk', 'viewer')),
  active         BOOLEAN NOT NULL DEFAULT true,
  failed_logins  INT NOT NULL DEFAULT 0,
  locked_until   TIMESTAMPTZ,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_login     TIMESTAMPTZ,
  password_changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_username ON users (lower(username));

CREATE TABLE IF NOT EXISTS refresh_tokens (
  token_hash  CHAR(64) PRIMARY KEY,
  user_id     UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  family      UUID NOT NULL,
  expires_at  TIMESTAMPTZ NOT NULL,
  revoked_at  TIMESTAMPTZ,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_refresh_user ON refresh_tokens (user_id);

CREATE TABLE IF NOT EXISTS login_events (
  event_id   BIGSERIAL PRIMARY KEY,
  username   VARCHAR(40) NOT NULL,
  user_id    UUID REFERENCES users(user_id) ON DELETE SET NULL,
  outcome    VARCHAR(20) NOT NULL,
  client     VARCHAR(64),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_login_events_user ON login_events (lower(username), created_at);
""")


def downgrade() -> None:
    op.execute(
        "DROP TABLE IF EXISTS login_events; DROP TABLE IF EXISTS refresh_tokens; "
        "DROP TABLE IF EXISTS users;"
    )

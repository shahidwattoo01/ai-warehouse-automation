"""004 — WMS inventory ledger and stock balances (wms/, inventory_model: wms).

wms_transactions is append-only: every receipt, putaway, move, replenishment, allocation, pick,
short pick, shipment, adjustment (with reason), status change, count and return, with the user
and the reference document. wms_stock holds the current balance per item, location, lot, status
and license plate, kept up to date as transactions arrive.
"""

from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE IF NOT EXISTS wms_transactions (
  run_id      UUID NOT NULL REFERENCES simulation_runs(run_id) ON DELETE CASCADE,
  txn_id      INT NOT NULL,
  tick        INT NOT NULL,
  type        VARCHAR(16) NOT NULL,
  sku         VARCHAR(32) NOT NULL,
  qty         INT NOT NULL,
  from_loc    VARCHAR(32),
  to_loc      VARCHAR(32),
  lot         VARCHAR(24),
  lpn         VARCHAR(20),
  status      VARCHAR(32),
  reason      VARCHAR(24),
  ref         VARCHAR(32),
  user_name   VARCHAR(40) NOT NULL,
  serials     TEXT[] NOT NULL DEFAULT '{}',
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (run_id, txn_id)
);
CREATE INDEX IF NOT EXISTS idx_wms_txn_sku ON wms_transactions (run_id, sku);
CREATE INDEX IF NOT EXISTS idx_wms_txn_ref ON wms_transactions (run_id, ref);

CREATE TABLE IF NOT EXISTS wms_stock (
  run_id       UUID NOT NULL REFERENCES simulation_runs(run_id) ON DELETE CASCADE,
  sku          VARCHAR(32) NOT NULL,
  location     VARCHAR(32) NOT NULL,
  lot          VARCHAR(24) NOT NULL,
  status       VARCHAR(16) NOT NULL,
  lpn          VARCHAR(20) NOT NULL DEFAULT '',
  qty          INT NOT NULL CHECK (qty >= 0),
  updated_tick INT NOT NULL,
  PRIMARY KEY (run_id, sku, location, lot, status, lpn)
);
CREATE INDEX IF NOT EXISTS idx_wms_stock_location ON wms_stock (run_id, location);
""")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS wms_stock; DROP TABLE IF EXISTS wms_transactions;")

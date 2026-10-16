-- Warehouse AI Platform — initial schema (Backend Schema §10). PostgreSQL 13+.
-- The pgvector document store (RAG, Phase 7) lives in schema_rag.sql with its own migration,
-- so this schema installs on a plain PostgreSQL without the vector extension.

-- ===== Enumerated types =====
CREATE TYPE robot_status_t  AS ENUM ('IDLE','MOVING','PICKING','DELIVERING','CHARGING','PAUSED','FAULT');
CREATE TYPE order_status_t  AS ENUM ('PENDING','ASSIGNED','IN_PROGRESS','DELIVERED','LATE','CANCELLED');
CREATE TYPE priority_t      AS ENUM ('LOW','MEDIUM','HIGH');
CREATE TYPE task_status_t   AS ENUM ('ASSIGNED','PICKING','DELIVERING','COMPLETED','FAILED','REASSIGNED');
CREATE TYPE station_type_t  AS ENUM ('PACKING','CHARGING');
CREATE TYPE event_type_t    AS ENUM ('ORDER_CREATED','ORDER_ASSIGNED','ROBOT_MOVED','ITEM_PICKED','ORDER_DELIVERED',
  'COLLISION','ROBOT_BLOCKED','BATTERY_LOW','ROBOT_FAULT','ROBOT_PAUSED','ROBOT_RESUMED','ROUTE_CHANGED',
  'FAULT_CLEARED','INVENTORY_RESTOCKED','COMMAND_REJECTED',
  'AISLE_CLOSED','AISLE_OPENED','HAZARD_DETECTED','HAZARD_CLEARED');
CREATE TYPE action_status_t AS ENUM ('PROPOSED','APPROVED','REJECTED','EXECUTED','VERIFIED','FAILED');
CREATE TYPE alert_type_t    AS ENUM ('ANOMALY','BATTERY_LOW','BLOCKED_PATH','COLLISION','LATE_ORDER');
CREATE TYPE alert_status_t  AS ENUM ('NEW','ACKNOWLEDGED','RESOLVED');
CREATE TYPE run_mode_t      AS ENUM ('INTERACTIVE','HEADLESS','EXPERIMENT','TRAINING');
CREATE TYPE message_role_t  AS ENUM ('OPERATOR','COPILOT','SYSTEM');

-- ===== Layout and catalogue =====
CREATE TABLE warehouse_zones (
  zone_id  VARCHAR(16) PRIMARY KEY,
  name     VARCHAR(64) NOT NULL,
  x_min INT NOT NULL, y_min INT NOT NULL, x_max INT NOT NULL, y_max INT NOT NULL,
  capacity INT NOT NULL CHECK (capacity > 0),
  CHECK (x_max >= x_min AND y_max >= y_min)
);

CREATE TABLE shelves (
  shelf_id VARCHAR(16) PRIMARY KEY,
  zone_id  VARCHAR(16) NOT NULL REFERENCES warehouse_zones ON DELETE RESTRICT,
  x INT NOT NULL, y INT NOT NULL,
  UNIQUE (x, y)
);

CREATE TABLE packing_stations (
  station_id VARCHAR(16) PRIMARY KEY,
  type       station_type_t NOT NULL,
  zone_id    VARCHAR(16) REFERENCES warehouse_zones ON DELETE RESTRICT,
  x INT NOT NULL, y INT NOT NULL,
  capacity   INT NOT NULL DEFAULT 1,
  UNIQUE (x, y)
);

CREATE TABLE products (
  product_id VARCHAR(16) PRIMARY KEY,
  name       VARCHAR(128) NOT NULL,
  category   VARCHAR(32)  NOT NULL,
  weight_kg  NUMERIC(6,2) NOT NULL CHECK (weight_kg > 0),
  shelf_id   VARCHAR(16)  NOT NULL REFERENCES shelves ON DELETE RESTRICT
);

-- ===== Fleet registry and runs =====
CREATE TABLE robots (
  robot_id         VARCHAR(16) PRIMARY KEY,
  model            VARCHAR(32)  NOT NULL,
  max_speed        NUMERIC(4,2) NOT NULL CHECK (max_speed > 0),
  battery_capacity NUMERIC(6,2) NOT NULL CHECK (battery_capacity > 0),
  max_load         INT NOT NULL CHECK (max_load > 0),
  home_x INT NOT NULL, home_y INT NOT NULL
);

CREATE TABLE simulation_runs (
  run_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  mode          run_mode_t  NOT NULL,
  experiment_id VARCHAR(8),
  seed          INT NOT NULL,
  layout_name   VARCHAR(64) NOT NULL,
  config        JSONB NOT NULL,
  started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  ended_at      TIMESTAMPTZ,
  total_ticks   INT,
  metrics       JSONB
);

CREATE TABLE inventory (
  run_id       UUID NOT NULL REFERENCES simulation_runs ON DELETE CASCADE,
  product_id   VARCHAR(16) NOT NULL REFERENCES products ON DELETE RESTRICT,
  stock        INT NOT NULL CHECK (stock >= 0),
  updated_tick INT NOT NULL,
  PRIMARY KEY (run_id, product_id)
);

-- ===== Orders and tasks =====
CREATE TABLE orders (
  run_id             UUID NOT NULL REFERENCES simulation_runs ON DELETE CASCADE,
  order_id           VARCHAR(16) NOT NULL,
  priority           priority_t NOT NULL,
  order_tick         INT NOT NULL,
  deadline_tick      INT NOT NULL,
  status             order_status_t NOT NULL DEFAULT 'PENDING',
  packing_station_id VARCHAR(16) REFERENCES packing_stations,
  delivered_tick     INT,
  PRIMARY KEY (run_id, order_id),
  CHECK (deadline_tick > order_tick)
);

CREATE TABLE order_items (
  run_id     UUID NOT NULL,
  order_id   VARCHAR(16) NOT NULL,
  product_id VARCHAR(16) NOT NULL REFERENCES products,
  quantity   INT NOT NULL CHECK (quantity > 0),
  PRIMARY KEY (run_id, order_id, product_id),
  FOREIGN KEY (run_id, order_id) REFERENCES orders ON DELETE CASCADE
);

CREATE TABLE robot_tasks (
  task_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id              UUID NOT NULL REFERENCES simulation_runs ON DELETE CASCADE,
  robot_id            VARCHAR(16) NOT NULL REFERENCES robots,
  order_id            VARCHAR(16) NOT NULL,
  status              task_status_t NOT NULL,
  assigned_tick       INT NOT NULL,
  completed_tick      INT,
  assignment_strategy VARCHAR(16) NOT NULL,
  planner             VARCHAR(16) NOT NULL,
  planned_distance    INT NOT NULL,
  actual_distance     INT,
  start_battery       NUMERIC(5,2) NOT NULL,
  start_congestion    NUMERIC(4,3) NOT NULL,
  items_count         INT NOT NULL,
  FOREIGN KEY (run_id, order_id) REFERENCES orders ON DELETE CASCADE
);

-- ===== Telemetry and events =====
CREATE TABLE robot_status (
  run_id          UUID NOT NULL REFERENCES simulation_runs ON DELETE CASCADE,
  tick            INT NOT NULL,
  robot_id        VARCHAR(16) NOT NULL REFERENCES robots,
  x INT NOT NULL, y INT NOT NULL,
  battery         NUMERIC(5,2) NOT NULL CHECK (battery BETWEEN 0 AND 100),
  speed           NUMERIC(4,2) NOT NULL,
  status          robot_status_t NOT NULL,
  load            INT NOT NULL DEFAULT 0,
  current_task_id UUID REFERENCES robot_tasks ON DELETE SET NULL,
  temperature     NUMERIC(5,2),
  route_deviation NUMERIC(6,2),
  PRIMARY KEY (run_id, tick, robot_id)
);

CREATE TABLE robot_events (
  event_id          BIGSERIAL PRIMARY KEY,
  run_id            UUID NOT NULL REFERENCES simulation_runs ON DELETE CASCADE,
  tick              INT NOT NULL,
  type              event_type_t NOT NULL,
  robot_id          VARCHAR(16) REFERENCES robots,
  order_id          VARCHAR(16),
  is_injected_fault BOOLEAN NOT NULL DEFAULT false,
  payload           JSONB NOT NULL DEFAULT '{}',
  FOREIGN KEY (run_id, order_id) REFERENCES orders ON DELETE CASCADE
);

-- ===== AI and audit =====
CREATE TABLE model_versions (
  model_version_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  model_name       VARCHAR(48) NOT NULL,
  version          VARCHAR(16) NOT NULL,
  artifact_path    TEXT NOT NULL,
  training_run_ids UUID[] NOT NULL,
  metrics          JSONB NOT NULL,
  is_active        BOOLEAN NOT NULL DEFAULT false,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (model_name, version)
);

CREATE TABLE predictions (
  prediction_id    BIGSERIAL PRIMARY KEY,
  run_id           UUID NOT NULL REFERENCES simulation_runs ON DELETE CASCADE,
  tick             INT NOT NULL,
  model_version_id UUID NOT NULL REFERENCES model_versions,
  target_type      VARCHAR(16) NOT NULL,
  target_id        VARCHAR(32),
  input            JSONB NOT NULL,
  output           JSONB NOT NULL,
  actual           JSONB
);

CREATE TABLE copilot_sessions (
  session_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id     UUID REFERENCES simulation_runs ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE copilot_messages (
  message_id BIGSERIAL PRIMARY KEY,
  session_id UUID NOT NULL REFERENCES copilot_sessions ON DELETE CASCADE,
  role       message_role_t NOT NULL,
  content    TEXT NOT NULL,
  intent     JSONB,
  route      VARCHAR(16),
  sources    JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE agent_actions (
  action_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id  UUID REFERENCES copilot_sessions ON DELETE SET NULL,
  run_id      UUID NOT NULL REFERENCES simulation_runs ON DELETE CASCADE,
  agent       VARCHAR(24) NOT NULL,
  tool        VARCHAR(48) NOT NULL,
  arguments   JSONB NOT NULL,
  is_write    BOOLEAN NOT NULL,
  status      action_status_t NOT NULL,
  reason      TEXT,
  result      JSONB,
  approved_at TIMESTAMPTZ,
  latency_ms  INT,
  cost_usd    NUMERIC(10,5),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE alerts (
  alert_id        BIGSERIAL PRIMARY KEY,
  run_id          UUID NOT NULL REFERENCES simulation_runs ON DELETE CASCADE,
  tick            INT NOT NULL,
  type            alert_type_t NOT NULL,
  robot_id        VARCHAR(16) REFERENCES robots,
  order_id        VARCHAR(16),
  source_event_id BIGINT REFERENCES robot_events ON DELETE SET NULL,
  status          alert_status_t NOT NULL DEFAULT 'NEW',
  resolved_tick   INT,
  FOREIGN KEY (run_id, order_id) REFERENCES orders ON DELETE CASCADE
);

-- ===== Indexes =====
CREATE INDEX idx_status_robot      ON robot_status (run_id, robot_id, tick);
CREATE INDEX idx_events_tick       ON robot_events (run_id, tick);
CREATE INDEX idx_events_type       ON robot_events (run_id, type);
CREATE INDEX idx_events_robot      ON robot_events (robot_id);
CREATE INDEX idx_orders_status     ON orders (run_id, status);
CREATE INDEX idx_orders_tick       ON orders (run_id, order_tick);
CREATE INDEX idx_tasks_robot       ON robot_tasks (run_id, robot_id);
CREATE INDEX idx_tasks_order       ON robot_tasks (run_id, order_id);
CREATE INDEX idx_pred_target       ON predictions (run_id, target_type, tick);
CREATE INDEX idx_pred_model        ON predictions (model_version_id);
CREATE INDEX idx_actions_pending   ON agent_actions (status) WHERE status = 'PROPOSED';
CREATE INDEX idx_actions_session   ON agent_actions (session_id);
CREATE INDEX idx_alerts_open       ON alerts (run_id, status);
CREATE UNIQUE INDEX uq_model_active ON model_versions (model_name) WHERE is_active;

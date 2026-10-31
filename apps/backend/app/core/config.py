"""Backend settings, loaded from environment variables / .env (TRD TR-ENG-03)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_ENV = Path(__file__).resolve().parents[4] / ".env"


class Settings(BaseSettings):
    # The project-root .env, wherever the backend is started from (repo root, apps/backend, tests).
    model_config = SettingsConfigDict(env_file=ROOT_ENV, extra="ignore")

    app_name: str = "Warehouse AI Platform"
    api_prefix: str = "/api/v1"
    # Browser origins allowed to call the API and open the stream (comma-separated).
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    database_url: str = "postgresql+psycopg://warehouse:change-me@localhost:5432/warehouse_ai"

    sim_layout: str = "large"
    sim_seed: int = 42
    # Record interactive runs to PostgreSQL (app/database/schema.sql); needs a migrated DB.
    persist_runs: bool = False
    sim_tick_hz: float = 2.0  # 1 cell per tick -> 2 m/s, a realistic AMR cruise speed
    # Inventory: "wms" (receiving, lots, allocation, replenishment, counts; wms/) or "simple"
    # (one stock number per bay, the model behind dataset v3 and the Phase 4 experiments).
    inventory_model: str = "wms"
    safety_slow_zones: bool = True  # robots at half speed near people (configs: safety)

    # Monitoring (docs/monitoring.md): LOG_FORMAT json for a log collector, text for people.
    log_format: str = "text"
    log_level: str = "INFO"
    # Bearer token Prometheus must send to /metrics; empty: /metrics is open (bind the API to
    # this machine or a private network then, as docker-compose does).
    metrics_token: str = ""

    # Authentication (JWT access tokens + rotating refresh tokens; app/core/auth.py).
    # Set JWT_SECRET in .env (python -c "import secrets; print(secrets.token_urlsafe(48))").
    # Empty: a random secret is made at start-up, so everyone logs in again after a restart.
    jwt_secret: str = ""
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    login_max_failures: int = 5  # failed logins in a row before the account is locked
    lockout_minutes: int = 15
    cookie_secure: bool = False  # true behind HTTPS (backlog PR-02): cookies only over TLS
    auth_store: str = "sql"  # sql (users table) | memory (tests)

    # Rate limits per client address (app/core/ratelimit.py). RATE_LIMIT_SCALE multiplies every
    # limit (e.g. 3 for a training room behind one NAT address). Behind a reverse proxy set
    # TRUST_PROXY_HEADERS=true so the client address comes from X-Forwarded-For.
    rate_limit_enabled: bool = True
    rate_limit_scale: float = 1.0
    trust_proxy_headers: bool = False

    # Network label printers for ZPL (app/services/printers.py): name=host[:port],...
    label_printers: str = ""

    # Alert notifications (app/services/alerts.py; rules in configs/alert_rules.yaml).
    alert_email_to: str = ""  # comma-separated recipients; empty: no email
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "warehouse-ai@localhost"
    alert_webhook_url: str = ""  # Slack / Teams incoming webhook or any URL taking JSON

    # VDA 5050 robot interface (integration/vda5050): MQTT broker, or empty for the in-process bus
    vda5050_enabled: bool = True
    mqtt_url: str = ""  # mqtt://user:password@host:1883 (mqtts:// for TLS)

    # ERP connection (integration/erp): a REST ERP, or the in-process mock ERP when ERP_URL is empty
    erp_enabled: bool = True
    erp_url: str = ""  # e.g. http://127.0.0.1:8100 for `python -m integration.erp.mock_erp`
    erp_api_key: str = ""
    erp_webhook_secret: str = ""  # signs pushed orders (POST /api/v1/erp/webhooks/orders)
    erp_poll_minutes: int = 5  # simulated minutes between pulls of released sales orders

    llm_provider: str = ""
    llm_model: str = ""
    llm_api_key: str = ""
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

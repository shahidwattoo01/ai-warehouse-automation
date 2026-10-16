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

"""Application configuration – loaded once at startup."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── MongoDB ──────────────────────────────────────────────────────────────
    mongodb_uri: str = Field(default="mongodb://localhost:27017/hrdb")
    mongodb_db_name: str = Field(default="hrdb")
    use_mock_db: bool = Field(default=False)

    # ── Application ──────────────────────────────────────────────────────────
    app_env: str = Field(default="development")
    app_port: int = Field(default=8000)
    log_level: str = Field(default="INFO")
    correlation_id_header: str = Field(default="X-Correlation-ID")

    # ── JWT / Auth ────────────────────────────────────────────────────────────
    jwt_secret_key: str = Field(default="changeme-generate-a-real-secret-in-production")
    jwt_algorithm: str = Field(default="HS256")
    jwt_expire_minutes: int = Field(default=60)

    # ── Webhook / Outbox Worker ───────────────────────────────────────────────
    webhook_hmac_secret: str = Field(default="changeme-webhook-hmac-secret")
    outbox_poll_interval_seconds: int = Field(default=5)
    outbox_max_retries: int = Field(default=5)
    outbox_backoff_base_seconds: int = Field(default=2)
    outbox_backoff_max_seconds: int = Field(default=60)
    webhook_request_timeout_seconds: int = Field(default=10)

    # ── Mock Downstream ───────────────────────────────────────────────────────
    mock_downstream_url: str = Field(default="http://mock_downstream:9000")
    mock_downstream_port: int = Field(default=9000)
    mock_failure_rate: float = Field(default=0.3)

    # ── Seeding ───────────────────────────────────────────────────────────────
    seed_employee_count: int = Field(default=50)
    seed_random_seed: int = Field(default=42)


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()

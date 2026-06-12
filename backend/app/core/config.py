"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Required environment variables must be set; the application will refuse
    to start if any are missing. Optional settings have sensible defaults.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "mortgageboss-ai"
    app_version: str = "0.1.0"
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = False

    # Database
    database_url: PostgresDsn = Field(description="PostgreSQL connection URL with asyncpg driver")
    database_pool_size: int = 5
    database_max_overflow: int = 10
    database_pool_timeout: int = 30

    # Redis
    redis_url: RedisDsn = Field(description="Redis connection URL for cache and Celery broker")

    # Celery (LP-41) — broker + result backend, both on the configured Redis.
    # Optional overrides (env CELERY_BROKER_URL / CELERY_RESULT_BACKEND) for pointing
    # Celery at a different Redis in production; when unset they default to redis_url
    # (the LP-2 Redis), so we don't duplicate that config. Broker and result backend
    # share the same Redis URL/DB in V1 — Celery namespaces its keys, so a separate
    # DB index is a later tuning, not required.
    celery_broker_url_override: str | None = Field(default=None, alias="CELERY_BROKER_URL")
    celery_result_backend_override: str | None = Field(default=None, alias="CELERY_RESULT_BACKEND")

    # Anthropic
    anthropic_api_key: str = Field(description="Anthropic API key for Claude access")
    # Model identifiers for the AI features (classification LP-38, extraction LP-39),
    # used by the app/ai client wrapper (LP-37). These are CONFIGURATION, not baked-in
    # facts — model strings change over time.
    # TODO(models): verify against the current Anthropic docs before relying on these.
    anthropic_model_classification: str = "claude-haiku-4-5"
    anthropic_model_extraction: str = "claude-sonnet-4-5"
    # AI retry policy (LP-37): transient failures (429/5xx/connection) are retried with
    # exponential backoff + jitter, capped at this many attempts.
    ai_max_retries: int = 3
    ai_base_retry_delay_seconds: float = 1.0

    # JWT / Auth
    jwt_secret_key: str = Field(
        min_length=32,
        description="Secret key for JWT signing (min 32 chars)",
    )
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60 * 24  # 24 hours
    jwt_refresh_token_expire_days: int = 30

    # Application-level PII encryption (LP-14, ADR-051)
    # Fernet key used to encrypt the most sensitive PII (e.g. borrower SSN) at
    # rest. Application-level rather than pgcrypto, so a database-only
    # compromise yields ciphertext but never the key (the key lives here, never
    # in the database). Generate one with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Required, no default: the app refuses to start without it. Key rotation
    # and secret-manager integration are Phase 7.
    encryption_key: str = Field(
        min_length=44,
        description="Fernet key (44-char urlsafe base64) for application-level PII encryption",
    )

    # CORS
    cors_allowed_origins: list[str] = ["http://localhost:3000"]

    # File storage
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_path: str = "./storage"

    # Email (SMTP)
    smtp_host: str = "localhost"
    smtp_port: int = 1025  # MailHog default
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str = "noreply@mortgageboss.ai"
    smtp_from_name: str = "mortgageboss-ai"

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["json", "console"] = "console"  # console for dev, json for prod

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_development(self) -> bool:
        """True if running in development environment."""
        return self.environment == "development"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_production(self) -> bool:
        """True if running in production environment."""
        return self.environment == "production"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def celery_broker_url(self) -> str:
        """Celery broker URL — the override if set, else the configured Redis (LP-41)."""
        return self.celery_broker_url_override or str(self.redis_url)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def celery_result_backend(self) -> str:
        """Celery result backend URL — the override if set, else the configured Redis."""
        return self.celery_result_backend_override or str(self.redis_url)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get the application settings (cached singleton)."""
    return Settings()  # type: ignore[call-arg]


# Convenience export
settings = get_settings()

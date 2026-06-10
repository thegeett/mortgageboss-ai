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
    database_url: PostgresDsn = Field(
        description="PostgreSQL connection URL with asyncpg driver"
    )
    database_pool_size: int = 5
    database_max_overflow: int = 10
    database_pool_timeout: int = 30

    # Redis
    redis_url: RedisDsn = Field(
        description="Redis connection URL for cache and Celery broker"
    )

    # Anthropic
    anthropic_api_key: str = Field(description="Anthropic API key for Claude access")
    anthropic_model_classification: str = "claude-haiku-4-5"
    anthropic_model_extraction: str = "claude-sonnet-4-5"

    # JWT / Auth
    jwt_secret_key: str = Field(
        min_length=32,
        description="Secret key for JWT signing (min 32 chars)",
    )
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60 * 24  # 24 hours
    jwt_refresh_token_expire_days: int = 30

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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get the application settings (cached singleton)."""
    return Settings()  # type: ignore[call-arg]


# Convenience export
settings = get_settings()

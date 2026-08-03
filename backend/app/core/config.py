"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import (
    Field,
    PostgresDsn,
    RedisDsn,
    computed_field,
    field_validator,
    model_validator,
)
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
    # The extraction/reasoning tier runs on Sonnet 4.5 (document extraction, cross-source
    # reasoning, needs/guidance) — the cost/quality default; a deployment can dial up to
    # Opus via env for more capability. The cheap high-volume classification/summarization
    # tier stays on Haiku. Both are env-overridable (ANTHROPIC_MODEL_CLASSIFICATION /
    # ANTHROPIC_MODEL_EXTRACTION); the default is the safe value, so a missing env var
    # degrades to Sonnet (correct + cheap), never silently to a 5x-cost Opus fallback.
    anthropic_model_classification: str = "claude-haiku-4-5"
    anthropic_model_extraction: str = "claude-sonnet-4-5"
    # AI retry policy (LP-37): transient failures (429/5xx/connection) are retried with
    # exponential backoff + jitter, capped at this many attempts.
    ai_max_retries: int = 3
    ai_base_retry_delay_seconds: float = 1.0
    # Wall-clock ceiling for one AI reasoning call (LP-313). ``complete()`` itself has no
    # timeout; tag production wraps its call so a hung request fails closed (the affected
    # tags become unknown-with-reason) instead of blocking a run indefinitely.
    ai_request_timeout_seconds: float = 60.0
    # Needs consolidation (LP-111): after the deterministic collapse, an AI pass FLAGS the
    # semantic-duplicate residue for the processor to confirm (never a silent delete). Gated so the
    # extra per-run classification call can be turned off; the deterministic layers run regardless.
    needs_duplicate_flagging_enabled: bool = True
    # Per-document AI-group gating (LP-377-D): skip an AI structuring group on a document its declared
    # `applies_to` doc-types exclude — a paid call the group would only abstain on (and, for income_amounts,
    # over-produce on). ALWAYS fails open (unknown / no-match document → runs every group). Set
    # GATE_AI_GROUPS=0 to instantly restore brute-force (run every group on every document) with no redeploy
    # — the safety net if a tag ever goes missing on a file shape the equivalence proof did not cover.
    gate_ai_groups: bool = True
    # Pending-check surfacing (LP-391): a blocked-but-applicable rule emits a manual-review flag instead of
    # silence, so a qualifying file no longer reads as "checked, clean". This materializes the BLOCKED rules'
    # UNCALIBRATED AI groups on a throwaway snapshot every run — real extra AI cost (latency + tokens) that
    # scales with the blocked-rule count. Gated so a cost-sensitive deployment can turn the whole pass off
    # with no redeploy; ON by default (the honest-surfacing behavior the live/persisted snapshot is unaffected by).
    pending_checks_enabled: bool = True

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

    # S3 storage (C0) — used only when storage_backend == "s3".
    # NOTE: there are deliberately NO access-key/secret-key settings. Credentials come
    # from botocore's default provider chain (SSO/profile locally, the task role on
    # ECS). Adding key settings would defeat the task-role design entirely.
    s3_bucket: str | None = None
    s3_region: str = "us-east-1"
    # Set for MinIO/LocalStack; None means the real AWS endpoint for the region.
    s3_endpoint_url: str | None = None
    s3_presign_expiry_seconds: int = 900  # 15 minutes
    # When set, objects are written with SSE-KMS using this key; otherwise SSE-S3.
    s3_kms_key_id: str | None = None

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

    @field_validator("s3_bucket", "s3_endpoint_url", "s3_kms_key_id", mode="before")
    @classmethod
    def _blank_s3_str_is_none(cls, value: object) -> object:
        """Treat a blank/whitespace S3 string as unset (C0).

        ``.env.example`` ships these keys present-but-empty (``S3_ENDPOINT_URL=``) so the
        full surface is discoverable. Pydantic would otherwise read ``""`` — and an empty
        ``endpoint_url`` passed to botocore is not "use the default AWS endpoint", it is
        an invalid endpoint. Normalizing here keeps a blank line in a ``.env`` meaning
        exactly what it looks like: not set.
        """
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _require_s3_bucket_when_s3(self) -> "Settings":
        """Refuse to start with ``storage_backend="s3"`` and no ``s3_bucket`` (C0).

        Without this the misconfiguration is accepted at boot (the ``Literal`` permits
        ``"s3"``) and surfaces only at the FIRST DOCUMENT READ — inside a Celery task,
        as a generic processing failure. That defeats the project's
        "required vars missing → refuse to start" convention, and on Fargate it would
        mean a task that reports healthy and then fails every document.

        Deliberately narrow: it validates only the setting that has no safe default.
        Region has one, and credentials are the provider chain's job, not config's.
        """
        if self.storage_backend == "s3" and not self.s3_bucket:
            raise ValueError('S3_BUCKET is required when STORAGE_BACKEND is "s3"')
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get the application settings (cached singleton)."""
    return Settings()  # type: ignore[call-arg]


# Convenience export
settings = get_settings()

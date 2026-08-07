"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import (
    Field,
    PostgresDsn,
    RedisDsn,
    ValidationInfo,
    computed_field,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_S3_REGION = "us-east-1"
_DEFAULT_S3_PRESIGN_EXPIRY_SECONDS = 900  # 15 minutes

#: S3 settings where a blank ``.env`` value means "unset — use this default", rather than
#: ``None`` (see ``Settings._blank_s3_str_is_none`` for the optional-string half). These
#: are the fields with a real default and a non-optional annotation, so ``""`` is neither
#: a usable value nor an acceptable one.
#:
#: A mapping, not a hand-kept list of validators, because the recurring defect here has
#: been THE FIELD SOMEONE FORGOT: ``s3_region`` was left out of the string normalizer, and
#: ``s3_presign_expiry_seconds`` was then the only S3 setting left with no normalizer at
#: all. The validator below registers itself from these keys, so adding an entry is the
#: whole change — there is no second place to remember.
_BLANK_S3_MEANS_DEFAULT: dict[str, str | int] = {
    "s3_region": _DEFAULT_S3_REGION,
    "s3_presign_expiry_seconds": _DEFAULT_S3_PRESIGN_EXPIRY_SECONDS,
}


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
    # CONDITIONALLY required (B1): the direct API needs it; Bedrock authenticates through
    # the AWS credential chain and must not be forced to carry a key it never sends.
    # Enforced by `_require_provider_credentials` below, so a bedrock deployment starts
    # with no key at all rather than a dummy value that would mask a real misconfiguration.
    anthropic_api_key: str | None = Field(
        default=None, description="Anthropic API key — required when AI_PROVIDER=anthropic"
    )
    # Model identifiers for the AI features. CONFIGURATION, not baked-in facts — model
    # strings change over time. TODO(models): verify against the current Anthropic docs.
    #
    # LP-457 — FOUR tiers, ONE per PURPOSE (a single constant would drag one purpose's callers
    # onto whatever another uses — precisely the problem this split fixes). Each is env-overridable
    # (ANTHROPIC_MODEL_CLASSIFICATION / _EXTRACTION / _REASONING / _ANALYSIS) from THIS one home;
    # the default is the safe value, so a missing env var never silently falls back to a wrong model.
    #   - classification/summarization: cheap, high-volume perception -> Haiku.
    #   - extraction: document field extraction -> Haiku 4.5 (LP-457 switched it from Sonnet
    #     4.5 for cost; verified field-by-field on a dense credit report + pay stub, LP-457
    #     Phase D). A deployment can dial it up via env.
    #   - reasoning: the fact-tag AI groups, rule judgment, cross-source, guidance, needs
    #     -> STAYS on Sonnet 4.5. ⚠️ The 37 live rules were CALIBRATED on Sonnet reasoning;
    #     moving the reasoning model would invalidate every activation bar. Kept separate so
    #     extraction can be cheapened WITHOUT touching calibrated reasoning.
    #   - analysis: the Tier-3 generic analyzer ("understand anything" for unrecognised docs)
    #     -> Sonnet 4.5 for open-ended comprehension. Its OWN tier (LP-457 review), NOT the
    #     reasoning tier: it is a document-PERCEPTION task, not calibration-sensitive, so it must
    #     not be dragged along when reasoning is re-pointed for CALIBRATION (that is exactly the
    #     cross-purpose coupling this split exists to prevent). Same default value, distinct knob.
    anthropic_model_classification: str = "claude-haiku-4-5"
    anthropic_model_extraction: str = "claude-haiku-4-5"  # LP-457: switched from Sonnet 4.5 (cost)
    anthropic_model_reasoning: str = (
        "claude-sonnet-4-5"  # STAYS Sonnet — the live bars are calibrated on it
    )
    anthropic_model_analysis: str = (
        "claude-sonnet-4-5"  # Tier-3 generic analysis — Sonnet, but its own knob (LP-457 review)
    )

    # --- Provider selection (B1) ------------------------------------------------------ #
    # Which API the SDK client talks to. Both paths stay LIVE: "anthropic" is the direct
    # API (unchanged default, byte-identical behaviour), "bedrock" routes the same calls
    # through Amazon Bedrock so inference stays inside the AWS trust boundary — the
    # compliance basis for putting real borrower NPI in staging.
    ai_provider: Literal["anthropic", "bedrock"] = "anthropic"
    bedrock_region: str = "us-east-1"
    # The AWS profile the Bedrock credential chain should use, when there is no ambient AWS_PROFILE.
    # ``AsyncAnthropicBedrock`` reads AWS_PROFILE from the process ENVIRONMENT (not from these settings),
    # and pydantic loads ``.env`` into this object, NOT into os.environ — so a local ``uv run`` backend
    # would otherwise inherit no profile and resolve NO credentials. This is read by the dev bench, which
    # exports it into os.environ before its preflight (docker already injects AWS_PROFILE via compose).
    aws_profile: str | None = None

    # A PARALLEL triplet, deliberately not a reuse of the three settings above. Flipping
    # provider must be ONE variable: if the same three settings held both vocabularies, a
    # flip would mean hand-editing three model strings, and a direct-API name sent to
    # Bedrock fails at INVOKE time — in production, as a validation error, per call.
    # With both triplets resident, `ai_provider` alone decides and neither can go stale.
    #
    # These must be the `us.` CROSS-REGION INFERENCE PROFILE ids. The bare
    # `anthropic.claude-*` forms are rejected for these models — on-demand throughput is
    # not offered for them. Left None so an anthropic-provider deployment carries no
    # Bedrock config; the validator below requires all three when the provider is bedrock.
    bedrock_model_classification: str | None = None
    bedrock_model_extraction: str | None = None
    bedrock_model_reasoning: str | None = None

    # Client-side pacing, PER PROVIDER because their ceilings differ by orders of
    # magnitude. None = unlimited (today's behaviour). See `resolve_requests_per_minute`.
    # ⚠️ PROCESS-LOCAL: N worker tasks pace at N x this value. Deploy the account quota
    # DIVIDED BY task count, never the quota itself.
    ai_requests_per_minute_anthropic: int | None = None
    ai_requests_per_minute_bedrock: int | None = None
    # AI retry policy (LP-37): transient failures (429/5xx/connection) are retried with
    # exponential backoff + jitter, capped at this many attempts.
    ai_max_retries: int = 3
    ai_base_retry_delay_seconds: float = 1.0
    # Wall-clock ceiling for ONE ATTEMPT of an AI call (LP-313; per-attempt since B1).
    # ``complete()`` applies it itself, so callers must NOT wrap it in a second
    # asyncio.wait_for — an outer wrapper also bills rate-limiter queueing time to the
    # call, which at a low RPM makes pacing look like a provider timeout. A hung request
    # still fails closed (the affected tags become unknown-with-reason); the total ceiling
    # for a call is this value x ai_max_retries plus backoff and pacing.
    ai_request_timeout_seconds: float = 60.0
    # LP-462: classification reads only the FIRST N pages of a PDF. The whole document was being sent, so a
    # >100-page file (a closing package, a condo declaration) exceeded the Anthropic/Bedrock 100-page document
    # limit and Bedrock rejected the call (BadRequestError). Classification identifies the LEAD document, which
    # needs few pages; 15 is far under the limit with headroom for an early second document. Classification
    # ONLY — extraction still reads the whole document (it needs the substantive pages); large-doc extraction
    # is the splitter's problem, not this cap.
    classification_max_pages: int = 15
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

    # Where the dev extraction bench writes its output. None → inside storage (``<storage>/bench_output``),
    # which is gitignored so borrower-derived output cannot be committed. Override to a dev-chosen path;
    # if that path is inside the repo, add it to .gitignore (bench output is derived from real documents).
    bench_output_dir: str | None = None

    # S3 storage (C0) — used only when storage_backend == "s3".
    # NOTE: there are deliberately NO access-key/secret-key settings. Credentials come
    # from botocore's default provider chain (SSO/profile locally, the task role on
    # ECS). Adding key settings would defeat the task-role design entirely.
    s3_bucket: str | None = None
    s3_region: str = _DEFAULT_S3_REGION
    # Set for MinIO/LocalStack; None means the real AWS endpoint for the region.
    s3_endpoint_url: str | None = None
    s3_presign_expiry_seconds: int = _DEFAULT_S3_PRESIGN_EXPIRY_SECONDS
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

    @field_validator(
        "anthropic_api_key",
        "bedrock_model_classification",
        "bedrock_model_extraction",
        "bedrock_model_reasoning",
        "ai_requests_per_minute_anthropic",
        "ai_requests_per_minute_bedrock",
        mode="before",
    )
    @classmethod
    def _blank_ai_value_is_none(cls, value: object) -> object:
        """Treat a blank/whitespace AI setting as unset (B1).

        Same reasoning as the S3 normalizer below, applied to the provider settings:
        ``.env.example`` ships ``BEDROCK_MODEL_EXTRACTION=`` present-but-empty so the
        surface is discoverable, and a blank ``ANTHROPIC_API_KEY=`` is how an operator
        writes "not using the direct API". Without this, ``""`` is truthy enough to pass
        the required-key validator and then fails at the first call as a 401.

        The two ``ai_requests_per_minute_*`` fields are here for a sharper reason: they are
        ``int | None`` and ship blank, so without normalizing, ``cp .env.example .env`` — the
        documented onboarding path — made the app REFUSE TO START with
        ``Input should be a valid integer, unable to parse string as an integer``. Blank
        already means "unlimited" in the prose beside them; ``None`` is that meaning.

        This is the fourth time a blank line in ``.env`` has broken a setting in this file
        (``s3_region``, ``s3_presign_expiry_seconds``, then both of these), which is why
        ``test_env_example_still_boots_the_app`` now asserts the whole file end to end
        rather than any single field.
        """
        if isinstance(value, str) and not value.strip():
            return None
        return value

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

    @field_validator(*_BLANK_S3_MEANS_DEFAULT, mode="before")
    @classmethod
    def _blank_s3_value_is_the_default(cls, value: object, info: ValidationInfo) -> object:
        """Treat a blank S3 setting with a real default as unset (C0).

        Separate from :meth:`_blank_s3_str_is_none` because these fields differ in kind:
        each has a safe default and a non-optional annotation, so "unset" resolves to that
        default rather than to ``None`` (which the annotation would reject).

        The two failure modes this closes are opposite in timing but identical in cause —
        ``.env.example`` heads the S3 block with "Leave blank for local dev", and a blank
        value was not honoured:

        * ``S3_REGION=`` validated as ``""`` and reached botocore as an empty region name,
          failing at the FIRST S3 CALL — the late failure
          :meth:`_require_s3_bucket_when_s3` exists to prevent.
        * ``S3_PRESIGN_EXPIRY_SECONDS=`` raised ``int_parsing`` at construction and refused
          to start the app **even under** ``STORAGE_BACKEND=local``, where the value is
          never read — a boot failure over a setting the process does not use.

        The validator registers itself from :data:`_BLANK_S3_MEANS_DEFAULT`, so a new
        field is covered by adding one entry there and nothing else.
        """
        if isinstance(value, str) and not value.strip():
            # ``field_name`` is always populated for a field validator; the empty-string
            # fallback raises KeyError rather than silently passing ``""`` through.
            return _BLANK_S3_MEANS_DEFAULT[info.field_name or ""]
        return value

    @model_validator(mode="after")
    def _require_provider_credentials(self) -> "Settings":
        """Refuse to start with a provider whose configuration is incomplete (B1).

        Both halves fail at BOOT rather than at the first model call, matching the C0
        precedent. The failure this prevents is specific: a missing Bedrock model id is
        only detectable at invoke time, where it arrives as a per-call validation error
        inside a Celery task — a worker that reports healthy and then fails every
        document, which is the worst shape a config error can take.
        """
        if self.ai_provider == "anthropic" and not self.anthropic_api_key:
            raise ValueError('ANTHROPIC_API_KEY is required when AI_PROVIDER is "anthropic"')

        if self.ai_provider == "bedrock":
            missing = [
                name.upper()
                for name in (
                    "bedrock_model_classification",
                    "bedrock_model_extraction",
                    "bedrock_model_reasoning",
                )
                if not getattr(self, name)
            ]
            if missing:
                raise ValueError(
                    f'AI_PROVIDER is "bedrock" but {", ".join(missing)} '
                    f"{'is' if len(missing) == 1 else 'are'} not set"
                )

            # The tier map is keyed by the DIRECT-API value a caller passes (see
            # `resolve_model`). If two tiers share that value they collapse to one key —
            # harmless while their Bedrock ids also match (classification and extraction
            # are both Haiku today), but a silent mis-route the moment they diverge.
            # Refuse the ambiguous configuration instead of resolving it by dict order.
            pairs: dict[str, set[str]] = {}
            for anthropic_value, bedrock_value in (
                (self.anthropic_model_classification, self.bedrock_model_classification),
                (self.anthropic_model_extraction, self.bedrock_model_extraction),
                (self.anthropic_model_reasoning, self.bedrock_model_reasoning),
            ):
                pairs.setdefault(anthropic_value, set()).add(bedrock_value or "")
            ambiguous = {k: sorted(v) for k, v in pairs.items() if len(v) > 1}
            if ambiguous:
                raise ValueError(
                    "ambiguous Bedrock model mapping — tiers sharing one ANTHROPIC_MODEL_* "
                    f"value map to different BEDROCK_MODEL_* ids: {ambiguous}. Give those "
                    "tiers distinct ANTHROPIC_MODEL_* values, or the same Bedrock id."
                )
        return self

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


# --------------------------------------------------------------------------- #
# Provider resolution (B1) — the ONE place a provider changes an outgoing value
# --------------------------------------------------------------------------- #


class ModelResolutionError(ValueError):
    """A caller's model value has no identifier under the active provider."""


def resolve_model(requested: str) -> str:
    """Translate a caller's tier model value into the ACTIVE provider's identifier.

    Callers keep passing ``settings.anthropic_model_{classification,extraction,reasoning}``
    — the setting they read IS their tier — and this maps that value to the Bedrock id for
    the same tier when the provider is bedrock. Deliberately keyed on the VALUE rather
    than a new ``purpose`` argument: adding a parameter to :func:`app.ai.client.complete`
    would mean touching all 13 call sites, and a provider swap that edits 13 files is a
    provider swap that will be done wrong once.

    Under ``ai_provider="anthropic"`` this is the identity function, which is what keeps
    the default path byte-identical.

    Raises :class:`ModelResolutionError` for a value that is not one of the three tiers —
    that means a caller hard-coded a model, which the LP-457 guard also forbids, and under
    Bedrock it would otherwise be sent verbatim and rejected at invoke time.
    """
    if settings.ai_provider == "anthropic":
        return requested
    for anthropic_value, bedrock_value in (
        (settings.anthropic_model_classification, settings.bedrock_model_classification),
        (settings.anthropic_model_extraction, settings.bedrock_model_extraction),
        (settings.anthropic_model_reasoning, settings.bedrock_model_reasoning),
    ):
        if requested == anthropic_value and bedrock_value:
            return bedrock_value
    raise ModelResolutionError(
        f"no BEDROCK_MODEL_* configured for model {requested!r} — it matches none of the "
        "three ANTHROPIC_MODEL_* tiers, so it cannot be mapped to a Bedrock identifier"
    )


def resolve_requests_per_minute() -> int | None:
    """The client-side pacing ceiling for the ACTIVE provider, or ``None`` for unlimited.

    Two settings rather than one because the ceilings differ by orders of magnitude: the
    direct API is generous, while a fresh Bedrock account is at 10 RPM. One shared value
    would either throttle the direct API pointlessly or fail to pace Bedrock at all.
    """
    if settings.ai_provider == "bedrock":
        return settings.ai_requests_per_minute_bedrock
    return settings.ai_requests_per_minute_anthropic

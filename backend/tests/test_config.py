"""Tests for configuration loading."""

import re
from pathlib import Path

import pytest
from app.core.config import Settings, get_settings


def test_settings_loads_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings can be loaded from environment variables."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-that-is-at-least-32-characters-long")

    # Clear the lru_cache
    get_settings.cache_clear()

    settings = Settings()  # type: ignore[call-arg]
    assert settings.app_name == "mortgageboss-ai"
    assert str(settings.database_url).startswith("postgresql+asyncpg://")


def test_settings_rejects_short_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """JWT secret must be at least 32 characters."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("JWT_SECRET_KEY", "too-short")

    with pytest.raises(Exception):  # Pydantic ValidationError  # noqa: B017
        Settings()  # type: ignore[call-arg]


def test_is_development_property() -> None:
    """is_development returns True when environment is development."""
    settings = Settings(
        database_url="postgresql+asyncpg://u:p@localhost:5432/d",  # type: ignore[arg-type]
        redis_url="redis://localhost:6379/0",  # type: ignore[arg-type]
        anthropic_api_key="key",
        jwt_secret_key="a" * 32,
        encryption_key="a" * 44,  # pragma: allowlist secret  (dummy 44-char key)
    )
    assert settings.is_development is True
    assert settings.is_production is False


# --------------------------------------------------------------------------- #
# `.env.example` must actually boot the app
# --------------------------------------------------------------------------- #


def _env_example_pairs() -> list[tuple[str, str]]:
    """Every KEY=VALUE in `backend/.env.example`, inline `#` comments stripped."""
    path = Path(__file__).resolve().parent.parent / ".env.example"
    pairs: list[tuple[str, str]] = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        # `KEY=value  # pragma: ...` — a trailing comment needs whitespace before the `#`,
        # matching how dotenv and docker-compose both read it.
        value = re.split(r"\s+#", value, maxsplit=1)[0]
        pairs.append((key.strip(), value.strip()))
    return pairs


def test_env_example_still_boots_the_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """`cp .env.example .env` must produce a bootable app.

    This is the structural guard for a bug class that has now recurred four times: a key
    shipped present-but-empty in `.env.example` whose field has no blank normalizer, so the
    documented onboarding path refuses to start. It has bitten `s3_region`,
    `s3_presign_expiry_seconds`, and both `ai_requests_per_minute_*` fields in turn — each
    fixed one field at a time. Asserting the FILE removes the need to remember the next one.

    Every key in the file is set as an env var, which outranks both the developer's shell
    and any real `backend/.env` in pydantic-settings' precedence — so a broken example line
    cannot be masked by a good value sitting elsewhere on the machine.
    """
    pairs = _env_example_pairs()
    assert pairs, ".env.example parsed to nothing — the parser or the file moved"

    for key, value in pairs:
        monkeypatch.setenv(key, value)

    Settings()  # type: ignore[call-arg]  # must not raise


def test_env_example_covers_every_required_setting() -> None:
    """A field with no default must appear in `.env.example`, or onboarding cannot work."""
    documented = {key for key, _ in _env_example_pairs()}
    required = {
        name.upper()
        for name, field in Settings.model_fields.items()
        if field.is_required() and not name.startswith("_")
    }
    assert required <= documented, (
        f"undocumented required settings: {sorted(required - documented)}"
    )


# --------------------------------------------------------------------------------------------- #
# LP-827 — the upload base URL a deployed environment cannot silently fall back on
# --------------------------------------------------------------------------------------------- #
def _required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-that-is-at-least-32-characters-long")
    get_settings.cache_clear()


@pytest.mark.parametrize("env", ["staging", "production"])
def test_a_deployed_environment_refuses_the_localhost_upload_default(
    monkeypatch: pytest.MonkeyPatch, env: str
) -> None:
    """THE ONE THAT SHIPPED. `UPLOAD_LINK_BASE_URL` was assigned in no `.tf`, `.tfvars`, `.yml`,
    `.env` or script in this repository, so staging ran on the development default and every secure
    link it minted pointed the borrower at `http://localhost:3000` — their own machine. Reported as
    "the secure link is not working on opening".

    The default itself is right and stays: a wrong upload URL should fail visibly rather than send a
    staging test email at a real borrower's production link. What was missing is that nothing made
    its absence impossible to deploy.
    """
    _required_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", env)
    monkeypatch.delenv("UPLOAD_LINK_BASE_URL", raising=False)

    with pytest.raises(ValueError, match="UPLOAD_LINK_BASE_URL"):
        Settings()  # type: ignore[call-arg]


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "0.0.0.0", "[::1]"])
def test_every_loopback_spelling_is_refused(monkeypatch: pytest.MonkeyPatch, host: str) -> None:
    """An asymmetry is a class, not an instance. Setting the variable to `127.0.0.1` is the same
    misconfiguration as leaving it unset, and a guard that only knew the word "localhost" would pass
    it — while the borrower's browser resolves all four to the same machine."""
    _required_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("UPLOAD_LINK_BASE_URL", f"https://{host}:3000")

    with pytest.raises(ValueError, match="UPLOAD_LINK_BASE_URL"):
        Settings()  # type: ignore[call-arg]


def test_development_still_runs_on_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    """THE POSITIVE CONTROL, and it is the point of the setting. A guard that refused localhost
    everywhere would break every developer's machine, and every test above would still pass."""
    _required_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("UPLOAD_LINK_BASE_URL", raising=False)

    settings = Settings()  # type: ignore[call-arg]
    assert settings.upload_link_base_url == "http://localhost:3000"


def test_a_real_origin_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    """The second positive control. Without it, a guard that rejected EVERY value outside
    development would satisfy both refusal tests above and stop staging booting at all."""
    _required_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("UPLOAD_LINK_BASE_URL", "https://staging.mortgageboss.ai")

    settings = Settings()  # type: ignore[call-arg]
    assert settings.upload_link_base_url == "https://staging.mortgageboss.ai"


def test_the_minted_url_is_built_from_the_configured_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The link a borrower clicks, asserted end to end from the setting. The guard above proves the
    value cannot be localhost in a deployed environment; this proves the value is what the URL is
    actually made of, which no amount of config validation would show on its own."""
    from app.services.upload_links import MintedLink

    _required_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("UPLOAD_LINK_BASE_URL", "https://staging.mortgageboss.ai/")
    settings = Settings()  # type: ignore[call-arg]

    monkeypatch.setattr("app.services.upload_links.settings", settings)
    url = MintedLink(link=None, token="tok123").url  # type: ignore[arg-type]

    assert url == "https://staging.mortgageboss.ai/upload/tok123"

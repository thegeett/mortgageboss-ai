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
# LP-827 — the upload base URL, and the process that must NOT be blocked by it
# --------------------------------------------------------------------------------------------- #
def _required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-that-is-at-least-32-characters-long")
    get_settings.cache_clear()


@pytest.mark.parametrize("env", ["staging", "production"])
def test_settings_still_build_without_an_upload_base_url(
    monkeypatch: pytest.MonkeyPatch, env: str
) -> None:
    """LP-827 REVIEW — THE GUARD MUST NOT BLOCK ITS OWN ROLLOUT.

    LP-827 refused to build `Settings` outside development when `UPLOAD_LINK_BASE_URL` was the
    localhost default. That fires in EVERY process, and one of them is `alembic upgrade head` —
    which `scripts/deploy` runs on the NEW image using the CURRENTLY DEPLOYED task definition, one
    step BEFORE the apply that sets the variable. Measured by running the real migration command
    under that environment: it died on the validator. The deploy that introduced the requirement
    could not complete, so the apply that satisfies it would never have run.

    The check now lives in `services.upload_links.usable_link_origin`, where the value is read.
    This asserts the property that fix exists for: a deployed process that never mints a link
    starts, whatever this variable says.
    """
    _required_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", env)
    monkeypatch.delenv("UPLOAD_LINK_BASE_URL", raising=False)

    settings = Settings()  # type: ignore[call-arg]

    assert settings.environment == env
    assert settings.upload_link_base_url == "http://localhost:3000"


def test_the_migration_entrypoint_imports_settings() -> None:
    """The positive control for the test above, and the reason it is not hypothetical.

    Without this, "settings still build" would be a claim about a process nothing proved was
    involved. `alembic/env.py` imports the cached singleton at module scope to read the database
    URL, so ANY validator on `Settings` runs inside `alembic upgrade head` — the deploy step that
    would have failed.
    """
    env_py = Path(__file__).resolve().parents[1] / "alembic" / "env.py"

    assert "from app.core.config import settings" in env_py.read_text(), (
        "alembic/env.py no longer imports settings — re-check whether a Settings validator can "
        "still block the migration step before re-adding one"
    )

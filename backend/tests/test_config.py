"""Tests for configuration loading."""

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

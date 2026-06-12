"""Tests for the settings-driven storage factory (LP-35)."""

import pytest
from app.core.config import settings
from app.storage import get_storage_backend
from app.storage.local import LocalStorageBackend


@pytest.fixture(autouse=True)
def _clear_factory_cache() -> None:
    """The factory is an lru_cache singleton; reset it around each test."""
    get_storage_backend.cache_clear()
    yield
    get_storage_backend.cache_clear()


def test_returns_local_backend_when_configured_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "storage_backend", "local")
    backend = get_storage_backend()
    assert isinstance(backend, LocalStorageBackend)


def test_unknown_backend_raises_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # Bypass the Settings Literal validation by patching the value directly to
    # exercise the factory's own guard for an unrecognized backend.
    monkeypatch.setattr(settings, "storage_backend", "ftp")
    with pytest.raises(ValueError, match="Unknown storage backend"):
        get_storage_backend()


def test_factory_is_cached_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "storage_backend", "local")
    assert get_storage_backend() is get_storage_backend()

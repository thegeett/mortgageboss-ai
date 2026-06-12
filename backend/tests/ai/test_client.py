"""Tests for the Anthropic async client wrapper (LP-37) — fully MOCKED.

No real API calls and no real key are needed: the singleton client is replaced
with a fake whose ``messages.create`` is an ``AsyncMock``. The focus is the
wrapper's policy, not the SDK: transient-only retry with backoff, fail-fast on
non-transient 4xx, exhaustion → ``AIClientError``, and — the privacy crux —
metadata-only logging that never contains prompt/response content.
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
import structlog
from anthropic import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)
from app.ai import client as client_module
from app.ai.client import AIClientError, AICompletion, _is_transient, complete

# --------------------------------------------------------------------------- #
# Helpers: fake responses and SDK exceptions (no network)
# --------------------------------------------------------------------------- #

_REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _fake_response(text: str = "hello", *, input_tokens: int = 10, output_tokens: int = 5) -> Any:
    """A stand-in for the SDK's Message response (content blocks + usage)."""
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def _status_error(exc_cls: type, status: int) -> Exception:
    return exc_cls("boom", response=httpx.Response(status, request=_REQUEST), body=None)


def _rate_limit() -> Exception:
    return _status_error(RateLimitError, 429)


def _server_error() -> Exception:
    return _status_error(InternalServerError, 503)


def _bad_request() -> Exception:
    return _status_error(BadRequestError, 400)


def _install_fake_client(monkeypatch: pytest.MonkeyPatch, create: AsyncMock) -> AsyncMock:
    """Replace the singleton client so ``complete`` uses our AsyncMock ``create``."""
    fake = SimpleNamespace(messages=SimpleNamespace(create=create))
    monkeypatch.setattr(client_module, "get_anthropic_client", lambda: fake)
    return create


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Patch the backoff sleep to record delays without waiting."""
    slept: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        slept.append(delay)

    monkeypatch.setattr(client_module.asyncio, "sleep", _fake_sleep)
    return slept


def _messages() -> list[dict[str, Any]]:
    return [{"role": "user", "content": "classify this document"}]


# --------------------------------------------------------------------------- #
# _is_transient classification
# --------------------------------------------------------------------------- #


def test_is_transient_true_for_rate_limit_5xx_and_connection() -> None:
    assert _is_transient(_rate_limit()) is True
    assert _is_transient(_server_error()) is True
    assert _is_transient(APIConnectionError(request=_REQUEST)) is True
    assert _is_transient(APITimeoutError(request=_REQUEST)) is True


def test_is_transient_false_for_other_4xx() -> None:
    assert _is_transient(_bad_request()) is False
    assert _is_transient(_status_error(AuthenticationError, 401)) is False
    assert _is_transient(_status_error(PermissionDeniedError, 403)) is False
    assert _is_transient(_status_error(NotFoundError, 404)) is False
    assert _is_transient(ValueError("not an SDK error")) is False


# --------------------------------------------------------------------------- #
# Success
# --------------------------------------------------------------------------- #


async def test_complete_returns_content_and_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    create = _install_fake_client(
        monkeypatch,
        AsyncMock(
            return_value=_fake_response("classified: pay_stub", input_tokens=42, output_tokens=7)
        ),
    )
    result = await complete(model="m", messages=_messages(), max_tokens=100)
    assert isinstance(result, AICompletion)
    assert result.text == "classified: pay_stub"
    assert result.input_tokens == 42
    assert result.output_tokens == 7
    assert result.model == "m"
    assert create.call_count == 1


async def test_complete_passes_optional_system_and_temperature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create = _install_fake_client(monkeypatch, AsyncMock(return_value=_fake_response()))
    await complete(
        model="m", messages=_messages(), max_tokens=50, system="be precise", temperature=0.2
    )
    kwargs = create.await_args.kwargs
    assert kwargs["system"] == "be precise"
    assert kwargs["temperature"] == 0.2
    assert kwargs["max_tokens"] == 50


# --------------------------------------------------------------------------- #
# Retry policy
# --------------------------------------------------------------------------- #


async def test_retries_transient_then_succeeds(
    monkeypatch: pytest.MonkeyPatch, _no_real_sleep: list[float]
) -> None:
    create = _install_fake_client(
        monkeypatch,
        AsyncMock(side_effect=[_rate_limit(), _server_error(), _fake_response("ok")]),
    )
    result = await complete(model="m", messages=_messages(), max_tokens=100)
    assert result.text == "ok"
    assert create.call_count == 3  # two transient failures, then success
    assert len(_no_real_sleep) == 2  # slept once before each retry


async def test_non_transient_fails_fast_without_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    create = _install_fake_client(monkeypatch, AsyncMock(side_effect=_bad_request()))
    with pytest.raises(AIClientError) as exc:
        await complete(model="m", messages=_messages(), max_tokens=100)
    assert create.call_count == 1  # did NOT retry a 400
    assert isinstance(exc.value.__cause__, BadRequestError)


async def test_exhausted_transient_retries_raises(
    monkeypatch: pytest.MonkeyPatch, _no_real_sleep: list[float]
) -> None:
    create = _install_fake_client(monkeypatch, AsyncMock(side_effect=_server_error()))
    with pytest.raises(AIClientError) as exc:
        await complete(model="m", messages=_messages(), max_tokens=100)
    # Default ai_max_retries = 3 → 3 attempts, 2 sleeps, then raise.
    assert create.call_count == 3
    assert len(_no_real_sleep) == 2
    assert isinstance(exc.value.__cause__, InternalServerError)


async def test_backoff_delays_increase(
    monkeypatch: pytest.MonkeyPatch, _no_real_sleep: list[float]
) -> None:
    # Fix jitter so delays are deterministic and strictly increasing.
    monkeypatch.setattr(client_module.random, "random", lambda: 0.5)
    _install_fake_client(monkeypatch, AsyncMock(side_effect=_rate_limit()))
    with pytest.raises(AIClientError):
        await complete(model="m", messages=_messages(), max_tokens=100)
    assert len(_no_real_sleep) == 2
    assert _no_real_sleep[0] < _no_real_sleep[1]  # exponential growth


# --------------------------------------------------------------------------- #
# PRIVACY: logs carry metadata, never prompt/response content
# --------------------------------------------------------------------------- #


async def test_success_log_has_metadata_not_content(monkeypatch: pytest.MonkeyPatch) -> None:
    pii_prompt = "SSN 123-45-6789 gross monthly pay 5000"
    pii_system = "internal-system-instructions-xyz"
    pii_response = "borrower lives at 42 Private Lane"
    _install_fake_client(monkeypatch, AsyncMock(return_value=_fake_response(pii_response)))

    with structlog.testing.capture_logs() as logs:
        await complete(
            model="m",
            messages=[{"role": "user", "content": pii_prompt}],
            max_tokens=100,
            system=pii_system,
        )

    success = [e for e in logs if e["event"] == "ai_call_succeeded"]
    assert len(success) == 1
    entry = success[0]
    # Metadata present.
    for key in ("model", "input_tokens", "output_tokens", "latency_ms", "attempt"):
        assert key in entry
    # Content absent from EVERY captured log entry.
    blob = " ".join(repr(e) for e in logs)
    assert pii_prompt not in blob
    assert pii_system not in blob
    assert pii_response not in blob


async def test_failure_log_has_metadata_not_content(
    monkeypatch: pytest.MonkeyPatch, _no_real_sleep: list[float]
) -> None:
    pii_prompt = "bank balance 987654 account 111-222"
    _install_fake_client(monkeypatch, AsyncMock(side_effect=_bad_request()))

    with structlog.testing.capture_logs() as logs, pytest.raises(AIClientError):
        await complete(
            model="m",
            messages=[{"role": "user", "content": pii_prompt}],
            max_tokens=100,
        )

    failed = [e for e in logs if e["event"] == "ai_call_failed"]
    assert len(failed) == 1
    entry = failed[0]
    for key in ("model", "latency_ms", "attempt", "error_type", "transient"):
        assert key in entry
    assert entry["error_type"] == "BadRequestError"
    assert entry["transient"] is False
    assert pii_prompt not in " ".join(repr(e) for e in logs)


# --------------------------------------------------------------------------- #
# Missing key — error fires at call time, not import
# --------------------------------------------------------------------------- #


def test_missing_key_raises_at_call_time(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ai.client import get_anthropic_client
    from app.core.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "")
    get_anthropic_client.cache_clear()
    try:
        with pytest.raises(AIClientError, match="ANTHROPIC_API_KEY is not configured"):
            get_anthropic_client()
    finally:
        get_anthropic_client.cache_clear()

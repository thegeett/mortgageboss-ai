"""LP-102 — the shared extraction truncation guard (Fix A + Fix B).

Pay-stub extraction returned empty because its 4096 max_tokens budget was too small for a pay
stub's many line items → the response truncated mid-JSON → the cut-off body silently failed to
parse → misreported as "could not parse extraction" / NEEDS_REVIEW. Fix A right-sizes pay_stub's
budget (8192); Fix B adds a SHARED guard (``app.ai.extraction.model_call.run_extraction_completion``)
that detects ``stop_reason == "max_tokens"``, logs it distinctly, retries EXACTLY ONCE at 16384, and
— if it still truncates — surfaces an HONEST truncated status (never "could not parse"). The guard
covers ALL extractors (pay stub is just the first to hit it).
"""

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from app.ai.client import AIClientError
from app.ai.extraction import model_call
from app.ai.extraction import pay_stub as pay_stub_module
from app.ai.extraction import w2 as w2_module
from app.ai.extraction.model_call import (
    RETRY_MAX_TOKENS,
    TRUNCATED_REASON,
    run_extraction_completion,
)
from app.models.extraction import ExtractionStatus

_PDF = b"%PDF-1.4 fake"
_MSG: dict[str, Any] = {"role": "user", "content": []}

VALID_PAY_STUB_JSON = json.dumps(
    {
        "typed_core": {
            "employer_name": {"value": "ACME Corp", "page": 1, "snippet": "ACME Corp"},
            "gross_pay": {"value": "4200.00", "page": 1, "snippet": "Gross 4,200.00"},
        },
        "additional_sections": [],
        "confidence": 0.9,
        "reasoning": "ok",
    }
)
VALID_W2_JSON = json.dumps(
    {
        "typed_core": {
            "wages_tips_other_comp": {"value": "62000.00", "page": 1, "snippet": "Box 1"}
        },
        "additional_sections": [],
        "confidence": 0.9,
        "reasoning": "ok",
    }
)


def _resp(text: str | None, *, stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(
        text=text, input_tokens=100, output_tokens=50, model="m", stop_reason=stop_reason
    )


def _patch_complete(monkeypatch: pytest.MonkeyPatch, *, side_effect: Any) -> AsyncMock:
    mock = AsyncMock(side_effect=side_effect)
    monkeypatch.setattr(model_call, "complete", mock)
    return mock


# --------------------------------------------------------------------------- #
# The shared runner — the core guard logic
# --------------------------------------------------------------------------- #


async def test_no_truncation_is_a_single_call(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = _patch_complete(monkeypatch, side_effect=[_resp("{}", stop_reason="end_turn")])
    call = await run_extraction_completion(
        system="s", message=_MSG, max_tokens=8192, log_label="pay_stub"
    )
    assert mock.await_count == 1  # no retry when not truncated
    assert call.text == "{}" and call.truncated is False and call.failure_reason is None


async def test_truncation_retries_exactly_once_at_the_high_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock = _patch_complete(
        monkeypatch,
        side_effect=[
            _resp("{trunc", stop_reason="max_tokens"),
            _resp("{}", stop_reason="end_turn"),
        ],
    )
    call = await run_extraction_completion(
        system="s", message=_MSG, max_tokens=8192, log_label="pay_stub"
    )
    assert mock.await_count == 2  # exactly one retry
    assert mock.await_args_list[0].kwargs["max_tokens"] == 8192  # attempt 1 at the type budget
    assert (
        mock.await_args_list[1].kwargs["max_tokens"] == RETRY_MAX_TOKENS == 16384
    )  # retry ceiling
    # Retry succeeded → transparent: the good text comes back, not truncated.
    assert call.text == "{}" and call.truncated is False


async def test_persistent_truncation_is_honest_no_third_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock = _patch_complete(
        monkeypatch,
        side_effect=[
            _resp("{trunc", stop_reason="max_tokens"),
            _resp("{still", stop_reason="max_tokens"),
        ],
    )
    call = await run_extraction_completion(
        system="s", message=_MSG, max_tokens=8192, log_label="pay_stub"
    )
    assert mock.await_count == 2  # NO third attempt
    assert call.text is None
    assert call.truncated is True
    assert call.failure_reason == TRUNCATED_REASON  # honest — NOT "could not parse extraction"


async def test_retry_only_on_truncation_not_other_stop_reasons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A non-truncation finish (even with garbage text) is NOT retried — more budget can't fix it.
    mock = _patch_complete(monkeypatch, side_effect=[_resp("garbage", stop_reason="end_turn")])
    call = await run_extraction_completion(
        system="s", message=_MSG, max_tokens=8192, log_label="pay_stub"
    )
    assert mock.await_count == 1
    assert call.text == "garbage" and call.truncated is False


async def test_ai_error_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = _patch_complete(monkeypatch, side_effect=AIClientError("boom"))
    call = await run_extraction_completion(
        system="s", message=_MSG, max_tokens=8192, log_label="pay_stub"
    )
    assert mock.await_count == 1  # errors aren't fixed by more budget
    assert call.text is None and call.failure_reason == "AI call failed" and call.truncated is False


# --------------------------------------------------------------------------- #
# Fix A — pay-stub budget right-sized
# --------------------------------------------------------------------------- #


def test_pay_stub_budget_is_8192() -> None:
    assert pay_stub_module._MAX_TOKENS == 8192


async def test_pay_stub_first_attempt_uses_8192_and_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock = _patch_complete(monkeypatch, side_effect=[_resp(VALID_PAY_STUB_JSON)])
    result = await pay_stub_module.extract_pay_stub(_PDF, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED
    assert result.data.employer_name.value == "ACME Corp"  # fields populate — no longer empty
    assert mock.await_args_list[0].kwargs["max_tokens"] == 8192


# --------------------------------------------------------------------------- #
# Fix B through the extractors — the guard is in the SHARED path (all types)
# --------------------------------------------------------------------------- #


async def test_pay_stub_truncation_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = _patch_complete(
        monkeypatch,
        side_effect=[
            _resp("{truncated…", stop_reason="max_tokens"),
            _resp(VALID_PAY_STUB_JSON, stop_reason="end_turn"),
        ],
    )
    result = await pay_stub_module.extract_pay_stub(_PDF, "application/pdf")
    assert mock.await_count == 2
    assert result.status == ExtractionStatus.SUCCEEDED  # the retry is transparent
    assert result.data.gross_pay.value is not None


async def test_pay_stub_persistent_truncation_gets_honest_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_complete(
        monkeypatch,
        side_effect=[
            _resp("{truncated…", stop_reason="max_tokens"),
            _resp("{still truncated…", stop_reason="max_tokens"),
        ],
    )
    result = await pay_stub_module.extract_pay_stub(_PDF, "application/pdf")
    assert result.status == ExtractionStatus.FAILED
    # HONEST: labeled a truncation, NOT the misleading "could not parse extraction".
    assert result.reasoning == TRUNCATED_REASON
    assert result.reasoning != "could not parse extraction"


async def test_guard_is_shared_second_extractor_also_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard lives in the shared path, so a DIFFERENT extractor (W-2) also retries on
    truncation — proving it's not pay-stub-only."""
    mock = _patch_complete(
        monkeypatch,
        side_effect=[
            _resp("{truncated…", stop_reason="max_tokens"),
            _resp(VALID_W2_JSON, stop_reason="end_turn"),
        ],
    )
    result = await w2_module.extract_w2(_PDF, "application/pdf")
    assert mock.await_count == 2
    assert mock.await_args_list[1].kwargs["max_tokens"] == 16384
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_w2_persistent_truncation_is_honest_too(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_complete(
        monkeypatch,
        side_effect=[
            _resp("{trunc", stop_reason="max_tokens"),
            _resp("{trunc", stop_reason="max_tokens"),
        ],
    )
    result = await w2_module.extract_w2(_PDF, "application/pdf")
    assert result.status == ExtractionStatus.FAILED
    assert result.reasoning == TRUNCATED_REASON  # honest for every extractor, via the shared path

"""Tests for retirement account extraction (LP-61) — the AI wrapper is MOCKED.

Follows the bank statement test template. Focus: the typed core is coerced with
source; the **vested-vs-total** distinction is captured separately; honest nulls
(no assuming vested == total); graceful failure; the account number is never
logged.

No real retirement statement samples were available — these verify the
mechanism/shape, not accuracy against real statements (validated as real
documents flow through; field set refined with Priya).
"""

import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import structlog
from app.ai.client import AIClientError
from app.ai.extraction import retirement_account as ret_module
from app.ai.extraction.retirement_account import (
    RetirementAccountExtraction,
    RetirementAccountExtractionResult,
    _parse_retirement_json,
    extract_retirement_account,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy retirement bytes"
MASKED_ACCT = "****6789"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "institution_name": _core("Fidelity"),
        "account_holder": _core("Jane Doe"),
        "account_number_masked": _core(MASKED_ACCT),
        "account_type": _core("401k", snippet="401(k) Plan"),
        "statement_period_start": _core("2024-07-01"),
        "statement_period_end": _core("2024-09-30"),
        "vested_balance": _core("$243,000.00", snippet="Vested 243,000.00"),
        "total_balance": _core("250000.00", snippet="Total 250,000.00"),
    },
    "additional_sections": [
        {"section": "Employer Match", "fields": [{"label": "YTD match", "value": "4200.00"}]}
    ],
    "confidence": 0.9,
    "reasoning": "401(k) statement.",
}
FULL_JSON = json.dumps(FULL_PAYLOAD)


def _mock_complete(
    monkeypatch: pytest.MonkeyPatch, *, text: str | None = None, exc: Exception | None = None
) -> AsyncMock:
    if exc is not None:
        mock = AsyncMock(side_effect=exc)
    else:
        mock = AsyncMock(
            return_value=SimpleNamespace(text=text, input_tokens=150, output_tokens=60, model="m")
        )
    monkeypatch.setattr(ret_module, "complete", mock)
    return mock


def test_parse_vested_and_total_captured_separately() -> None:
    """The vested-vs-total distinction — both captured, vested is the accessible figure."""
    result = _parse_retirement_json(FULL_JSON)
    assert result is not None
    d = result.data
    assert d.account_type.value == "401k"
    assert d.vested_balance.value == Decimal("243000.00")  # "$243,000.00" coerced
    assert d.total_balance.value == Decimal("250000.00")
    assert d.vested_balance.value != d.total_balance.value  # distinct figures


def test_vested_null_when_only_total_present() -> None:
    """If only one balance is shown and vesting isn't mentioned, vested stays null."""
    payload = {
        "typed_core": {"institution_name": _core("Fidelity"), "total_balance": _core("100000")},
        "confidence": 0.8,
    }
    d = _parse_retirement_json(json.dumps(payload)).data  # type: ignore[union-attr]
    assert d.total_balance.value == Decimal("100000")
    assert d.vested_balance.value is None  # not assumed equal to total


def test_source_location_present() -> None:
    d = _parse_retirement_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.vested_balance.source is not None
    assert d.vested_balance.source.snippet == "Vested 243,000.00"


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"vested_balance": _core(None), "total_balance": _core(None)}}
    result = _parse_retirement_json(json.dumps(payload))
    assert result is not None
    assert result.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_retirement_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_retirement_account(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED
    assert result.data.vested_balance.value == Decimal("243000.00")


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_retirement_account(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


async def test_does_not_log_account_number_or_values(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    with structlog.testing.capture_logs() as logs:
        await extract_retirement_account(PDF_BYTES, "application/pdf")
    blob = " ".join(repr(e) for e in logs)
    assert MASKED_ACCT not in blob and "Fidelity" not in blob and "243000" not in blob
    done = [e for e in logs if e["event"] == "retirement_account_extraction_done"]
    assert len(done) == 1 and done[0]["core_fields_present"] == 8


def test_failed_factory() -> None:
    result = RetirementAccountExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == RetirementAccountExtraction()

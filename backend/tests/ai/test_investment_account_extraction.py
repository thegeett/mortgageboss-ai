"""Tests for investment account extraction (LP-61) — the AI wrapper is MOCKED.

Follows the bank statement test template (an asset doc with a masked account).
Focus: the typed core is coerced (names/type→str, period→date, total_value→
Decimal) with source; holdings land in the catch-all (nothing dropped); honest
nulls; graceful failure; and the **account number is never logged**.

No real investment statement samples were available — these verify the
mechanism/shape, not accuracy against real statements (validated as real
documents flow through; field set refined with Priya).
"""

import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import structlog
from app.ai.client import AIClientError
from app.ai.extraction import investment_account as inv_module
from app.ai.extraction.investment_account import (
    InvestmentAccountExtraction,
    InvestmentAccountExtractionResult,
    _parse_investment_json,
    extract_investment_account,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy investment bytes"
MASKED_ACCT = "****4321"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "institution_name": _core("Vanguard"),
        "account_holder": _core("Jane Doe"),
        "account_number_masked": _core(MASKED_ACCT, snippet="Account ****4321"),
        "account_type": _core("brokerage"),
        "statement_period_start": _core("2024-09-01"),
        "statement_period_end": _core("2024-09-30"),
        "total_value": _core("$19,000.00", snippet="Total Value 19,000.00"),
    },
    "additional_sections": [
        {
            "section": "Holdings",
            "fields": [{"label": "VTSAX", "value": "120 / 12,000.00", "page": 1}],
        }
    ],
    "confidence": 0.9,
    "reasoning": "Brokerage statement.",
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
    monkeypatch.setattr(inv_module, "complete", mock)
    return mock


def test_parse_full_shape_with_types() -> None:
    result = _parse_investment_json(FULL_JSON)
    assert result is not None
    assert result.status == ExtractionStatus.SUCCEEDED
    d = result.data
    assert d.institution_name.value == "Vanguard"
    assert d.statement_period_end.value == date(2024, 9, 30)
    assert d.total_value.value == Decimal("19000.00")  # "$19,000.00" coerced
    assert d.account_number_masked.value == MASKED_ACCT
    # Holdings preserved in the catch-all (not forced into the typed core).
    labels = [f.label for s in d.additional_sections for f in s.fields]
    assert "VTSAX" in labels


def test_source_location_present() -> None:
    d = _parse_investment_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.total_value.source is not None
    assert d.total_value.source.snippet == "Total Value 19,000.00"


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"institution_name": _core(None), "total_value": _core(None)}}
    result = _parse_investment_json(json.dumps(payload))
    assert result is not None
    assert result.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_investment_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_investment_account(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED
    assert result.data.total_value.value == Decimal("19000.00")


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_investment_account(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("media_type", ["text/plain", ""])
async def test_extract_unsupported_skips_api(
    monkeypatch: pytest.MonkeyPatch, media_type: str
) -> None:
    mock = _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_investment_account(PDF_BYTES, media_type)
    assert result.status == ExtractionStatus.FAILED
    assert mock.call_count == 0


async def test_does_not_log_account_number_or_values(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    with structlog.testing.capture_logs() as logs:
        result = await extract_investment_account(PDF_BYTES, "application/pdf")
    blob = " ".join(repr(e) for e in logs)
    assert MASKED_ACCT not in blob  # even the masked account number isn't logged
    assert "Vanguard" not in blob and "19000" not in blob and "19,000" not in blob
    done = [e for e in logs if e["event"] == "investment_account_extraction_done"]
    assert len(done) == 1 and done[0]["core_fields_present"] == 7
    assert result.data.account_number_masked.value == MASKED_ACCT  # available to caller


def test_failed_factory() -> None:
    result = InvestmentAccountExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == InvestmentAccountExtraction()

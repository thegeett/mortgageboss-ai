"""Tests for loan estimate extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

Shape/mechanism, not accuracy (guide §10): the typed core is coerced with source, an
all-null core is FAILED, unparseable JSON returns None, and the ``.failed()`` factory
holds. No real samples exist — accuracy is validated as real documents flow through.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.ai.client import AIClientError
from app.ai.extraction import model_call
from app.ai.extraction.loan_estimate import (
    LoanEstimateExtraction,
    LoanEstimateExtractionResult,
    _parse_loan_estimate_json,
    extract_loan_estimate,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy loan_estimate"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "loan_number": _core("SAMPLE"),
        "issue_date": _core("2024-01-15"),
        "borrower_name": _core("SAMPLE"),
        "borrower_name_2": _core("SAMPLE"),
        "property_address": _core("SAMPLE"),
        "sale_price": _core("1234.56"),
        "loan_amount": _core("1234.56"),
        "interest_rate": _core("1234.56"),
        "monthly_principal_and_interest": _core("1234.56"),
        "loan_term": _core("SAMPLE"),
        "loan_product": _core("SAMPLE"),
        "loan_purpose": _core("SAMPLE"),
        "loan_type": _core("SAMPLE"),
        "lender_name": _core("SAMPLE"),
        "apr": _core("1234.56"),
        "total_interest_percentage": _core("1234.56"),
        "estimated_total_monthly_payment": _core("1234.56"),
        "estimated_escrow": _core("1234.56"),
        "estimated_taxes_insurance_assessments": _core("1234.56"),
        "total_closing_costs": _core("1234.56"),
        "cash_to_close": _core("1234.56"),
        "prepayment_penalty_indicator": _core("SAMPLE"),
        "balloon_payment_indicator": _core("SAMPLE"),
        "rate_lock_expiration": _core("2024-01-15"),
        "closing_cost_estimate_expiration": _core("2024-01-15"),
        "in_5_years_total_payments": _core("1234.56"),
        "in_5_years_principal_paid": _core("1234.56"),
    },
    "additional_sections": [{"section": "Other", "fields": [{"label": "Note", "value": "x"}]}],
    "confidence": 0.9,
    "reasoning": "generated test fixture.",
}
FULL_JSON = json.dumps(FULL_PAYLOAD)


def _mock_complete(
    monkeypatch: pytest.MonkeyPatch, *, text: str | None = None, exc: Exception | None = None
) -> AsyncMock:
    if exc is not None:
        mock = AsyncMock(side_effect=exc)
    else:
        mock = AsyncMock(
            return_value=SimpleNamespace(
                text=text, input_tokens=150, output_tokens=60, model="m", stop_reason="end_turn"
            )
        )
    monkeypatch.setattr(model_call, "complete", mock)
    return mock


def test_typed_core_coerced_with_source() -> None:
    d = _parse_loan_estimate_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.loan_number.value == "SAMPLE"
    assert d.loan_number.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"loan_number": _core(None)}}
    parsed = _parse_loan_estimate_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_loan_estimate_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_loan_estimate(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_loan_estimate(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = LoanEstimateExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == LoanEstimateExtraction()

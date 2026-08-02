"""Tests for verification of mortgage extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.verification_of_mortgage import (
    VerificationOfMortgageExtraction,
    VerificationOfMortgageExtractionResult,
    _parse_verification_of_mortgage_json,
    extract_verification_of_mortgage,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy verification_of_mortgage"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "document_title": _core("SAMPLE"),
        "property_address": _core("SAMPLE"),
        "mortgage_holder_or_servicer": _core("SAMPLE"),
        "borrower_name": _core("SAMPLE"),
        "borrower_name_2": _core("SAMPLE"),
        "loan_number_masked": _core("SAMPLE"),
        "origination_date": _core("2024-01-15"),
        "original_loan_amount": _core("1234.56"),
        "loan_type": _core("SAMPLE"),
        "interest_rate": _core("SAMPLE"),
        "maturity_date": _core("2024-01-15"),
        "current_principal_balance": _core("1234.56"),
        "scheduled_monthly_payment": _core("1234.56"),
        "principal_and_interest_payment": _core("1234.56"),
        "escrow_payment": _core("1234.56"),
        "next_payment_due_date": _core("2024-01-15"),
        "taxes_and_insurance_current": _core("SAMPLE"),
        "late_30_count": _core(2024),
        "late_60_count": _core(2024),
        "late_90_count": _core(2024),
        "late_120_plus_count": _core(2024),
        "worst_rating": _core("SAMPLE"),
        "current_delinquency_status": _core("SAMPLE"),
        "past_due_amount": _core("1234.56"),
        "foreclosure_or_loss_mitigation_status": _core("SAMPLE"),
        "forbearance_or_modification_terms": _core("SAMPLE"),
        "verifier_name_title": _core("SAMPLE"),
        "verifier_phone_or_contact": _core("SAMPLE"),
        "verification_date": _core("2024-01-15"),
        "direct_source_indicator": _core("SAMPLE"),
    },
    "additional_sections": [{"section": "Other", "fields": [{"label": "Note", "value": "x"}]}],
    "payment_history_months": [
        {
            "month": "SAMPLE",
            "payment_status": "SAMPLE",
            "amount_paid": "1234.56",
            "source": "SAMPLE",
            "page": 1,
            "snippet": "s",
        }
    ],
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
    d = _parse_verification_of_mortgage_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.document_title.value == "SAMPLE"
    assert d.document_title.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"document_title": _core(None)}}
    parsed = _parse_verification_of_mortgage_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_verification_of_mortgage_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_verification_of_mortgage(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_verification_of_mortgage(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = VerificationOfMortgageExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == VerificationOfMortgageExtraction()

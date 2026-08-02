"""Tests for mortgage loan origination agreement extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.mortgage_loan_origination_agreement import (
    MortgageLoanOriginationAgreementExtraction,
    MortgageLoanOriginationAgreementExtractionResult,
    _parse_mortgage_loan_origination_agreement_json,
    extract_mortgage_loan_origination_agreement,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy mortgage_loan_origination_agreement"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "document_title": _core("SAMPLE"),
        "agreement_date": _core("2024-01-15"),
        "issuer_name": _core("SAMPLE"),
        "borrower_name": _core("SAMPLE"),
        "borrower_name_2": _core("SAMPLE"),
        "borrower_names_raw": _core("SAMPLE"),
        "mortgage_broker_or_originator_name": _core("SAMPLE"),
        "creditor_or_lender_name": _core("SAMPLE"),
        "organization_nmls_id": _core("SAMPLE"),
        "individual_originator_name": _core("SAMPLE"),
        "individual_nmls_id": _core("SAMPLE"),
        "broker_compensation_method": _core("SAMPLE"),
        "borrower_paid_compensation": _core("1234.56"),
        "lender_paid_compensation": _core("1234.56"),
        "deposit_or_application_fee": _core("1234.56"),
        "lender_credits_or_rebates": _core("1234.56"),
        "broker_or_agent_relationship": _core("SAMPLE"),
        "exclusivity_indicator": _core("SAMPLE"),
        "rate_lock_responsibilities": _core("SAMPLE"),
        "refundability_and_cancellation_terms": _core("SAMPLE"),
        "agreement_term_or_expiration": _core("SAMPLE"),
        "property_address": _core("SAMPLE"),
        "loan_number": _core("SAMPLE"),
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
    d = _parse_mortgage_loan_origination_agreement_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.document_title.value == "SAMPLE"
    assert d.document_title.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"document_title": _core(None)}}
    parsed = _parse_mortgage_loan_origination_agreement_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_mortgage_loan_origination_agreement_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_mortgage_loan_origination_agreement(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_mortgage_loan_origination_agreement(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = MortgageLoanOriginationAgreementExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == MortgageLoanOriginationAgreementExtraction()

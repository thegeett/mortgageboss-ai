"""Tests for uniform residential loan application extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.uniform_residential_loan_application import (
    UniformResidentialLoanApplicationExtraction,
    UniformResidentialLoanApplicationExtractionResult,
    _parse_uniform_residential_loan_application_json,
    extract_uniform_residential_loan_application,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy uniform_residential_loan_application"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "borrower_legal_name": _core("SAMPLE"),
        "borrower_name_2": _core("SAMPLE"),
        "borrower_count": _core(2024),
        "social_security_number": _core("SAMPLE"),
        "social_security_number_2": _core("SAMPLE"),
        "date_of_birth": _core("2024-01-15"),
        "date_of_birth_2": _core("2024-01-15"),
        "marital_status": _core("SAMPLE"),
        "citizenship_residency_status": _core("SAMPLE"),
        "current_address": _core("SAMPLE"),
        "current_address_type": _core("SAMPLE"),
        "mailing_address": _core("SAMPLE"),
        "current_address_duration_months": _core(2024),
        "current_housing_status": _core("SAMPLE"),
        "stated_monthly_income_total": _core("1234.56"),
        "loan_amount": _core("1234.56"),
        "loan_purpose": _core("SAMPLE"),
        "property_value_or_purchase_price": _core("1234.56"),
        "lender_loan_number": _core("SAMPLE"),
        "universal_loan_identifier": _core("SAMPLE"),
        "subject_property_address": _core("SAMPLE"),
        "number_of_units": _core(2024),
        "property_type": _core("SAMPLE"),
        "occupancy_intent": _core("SAMPLE"),
        "estate_type": _core("SAMPLE"),
        "manufactured_home_indicator": _core("SAMPLE"),
        "mixed_use_indicator": _core("SAMPLE"),
        "declaration_borrowed_down_payment": _core("SAMPLE"),
        "declaration_primary_residence": _core("SAMPLE"),
        "declaration_other_mortgage_application": _core("SAMPLE"),
        "demographic_section_present": _core("SAMPLE"),
        "application_signed_date": _core("2024-01-15"),
        "application_taken_date": _core("2024-01-15"),
        "is_signed": _core("SAMPLE"),
        "form_version": _core("SAMPLE"),
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
    d = _parse_uniform_residential_loan_application_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.borrower_legal_name.value == "SAMPLE"
    assert d.borrower_legal_name.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"borrower_legal_name": _core(None)}}
    parsed = _parse_uniform_residential_loan_application_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_uniform_residential_loan_application_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_uniform_residential_loan_application(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_uniform_residential_loan_application(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = UniformResidentialLoanApplicationExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == UniformResidentialLoanApplicationExtraction()

"""Tests for homeowner s insurance quote extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.homeowner_s_insurance_quote import (
    HomeownerSInsuranceQuoteExtraction,
    HomeownerSInsuranceQuoteExtractionResult,
    _parse_homeowner_s_insurance_quote_json,
    extract_homeowner_s_insurance_quote,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy homeowner_s_insurance_quote"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "insurance_carrier": _core("SAMPLE"),
        "quote_number": _core("SAMPLE"),
        "quote_date": _core("2024-01-15"),
        "quote_valid_through_date": _core("2024-01-15"),
        "proposed_effective_date": _core("2024-01-15"),
        "binding_status": _core("SAMPLE"),
        "estimated_or_final_premium_indicator": _core("SAMPLE"),
        "agency_or_producer_name": _core("SAMPLE"),
        "named_insured": _core("SAMPLE"),
        "named_insured_2": _core("SAMPLE"),
        "named_insured_count": _core(2024),
        "insured_property_address": _core("SAMPLE"),
        "policy_number": _core("SAMPLE"),
        "policy_status": _core("SAMPLE"),
        "dwelling_coverage_a": _core("1234.56"),
        "other_structures_coverage_b": _core("1234.56"),
        "personal_property_coverage_c": _core("1234.56"),
        "personal_liability_coverage_e": _core("1234.56"),
        "replacement_cost_or_coinsurance_basis": _core("SAMPLE"),
        "annual_premium": _core("1234.56"),
        "premium_paid_or_due_status": _core("SAMPLE"),
        "effective_date": _core("2024-01-15"),
        "expiration_date": _core("2024-01-15"),
    },
    "additional_sections": [{"section": "Other", "fields": [{"label": "Note", "value": "x"}]}],
    "mortgagee_or_lienholder_entries": [
        {
            "lender_name": "SAMPLE",
            "loan_number": "SAMPLE",
            "clause_address": "SAMPLE",
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
    d = _parse_homeowner_s_insurance_quote_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.insurance_carrier.value == "SAMPLE"
    assert d.insurance_carrier.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"insurance_carrier": _core(None)}}
    parsed = _parse_homeowner_s_insurance_quote_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_homeowner_s_insurance_quote_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_homeowner_s_insurance_quote(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_homeowner_s_insurance_quote(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = HomeownerSInsuranceQuoteExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == HomeownerSInsuranceQuoteExtraction()

"""Tests for flood insurance policy extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.flood_insurance_policy import (
    FloodInsurancePolicyExtraction,
    FloodInsurancePolicyExtractionResult,
    _parse_flood_insurance_policy_json,
    extract_flood_insurance_policy,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy flood_insurance_policy"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "insurance_carrier_or_nfip_wyo_company": _core("SAMPLE"),
        "named_insureds": _core("SAMPLE"),
        "insured_property_address": _core("SAMPLE"),
        "policy_number": _core("SAMPLE"),
        "policy_form_or_program": _core("SAMPLE"),
        "effective_date": _core("2024-01-15"),
        "expiration_date": _core("2024-01-15"),
        "policy_status": _core("SAMPLE"),
        "flood_zone": _core("SAMPLE"),
        "community_and_map_information": _core("SAMPLE"),
        "building_coverage_limit": _core("1234.56"),
        "contents_coverage_limit": _core("1234.56"),
        "building_deductible": _core("1234.56"),
        "contents_deductible": _core("1234.56"),
        "replacement_cost_or_actual_cash_value_basis": _core("SAMPLE"),
        "annual_premium": _core("1234.56"),
        "premium_paid_status": _core("SAMPLE"),
        "waiting_period_or_effective_condition": _core("SAMPLE"),
        "lender_loan_number": _core("SAMPLE"),
    },
    "additional_sections": [{"section": "Other", "fields": [{"label": "Note", "value": "x"}]}],
    "mortgagee_clause_entries": [
        {
            "mortgagee_name": "SAMPLE",
            "mortgagee_address": "SAMPLE",
            "loan_number": "SAMPLE",
            "capacity": "SAMPLE",
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
    d = _parse_flood_insurance_policy_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.insurance_carrier_or_nfip_wyo_company.value == "SAMPLE"
    assert d.insurance_carrier_or_nfip_wyo_company.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"insurance_carrier_or_nfip_wyo_company": _core(None)}}
    parsed = _parse_flood_insurance_policy_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_flood_insurance_policy_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_flood_insurance_policy(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_flood_insurance_policy(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = FloodInsurancePolicyExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == FloodInsurancePolicyExtraction()

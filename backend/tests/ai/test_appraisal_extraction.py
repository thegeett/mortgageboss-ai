"""Tests for appraisal extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.appraisal import (
    AppraisalExtraction,
    AppraisalExtractionResult,
    _parse_appraisal_json,
    extract_appraisal,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy appraisal"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "uad_version": _core("SAMPLE"),
        "form_type": _core("SAMPLE"),
        "appraisal_effective_date": _core("2024-01-15"),
        "report_date": _core("2024-01-15"),
        "appraiser_name": _core("SAMPLE"),
        "appraiser_license": _core("SAMPLE"),
        "lender_client_name": _core("SAMPLE"),
        "subject_property_address": _core("SAMPLE"),
        "county": _core("SAMPLE"),
        "legal_description": _core("SAMPLE"),
        "parcel_identification_number": _core("SAMPLE"),
        "property_type": _core("SAMPLE"),
        "number_of_units": _core(2024),
        "occupant_status": _core("SAMPLE"),
        "year_built": _core(2024),
        "gross_living_area": _core(2024),
        "project_name": _core("SAMPLE"),
        "hoa_dues_amount": _core("1234.56"),
        "hoa_dues_frequency": _core("SAMPLE"),
        "appraised_value": _core("1234.56"),
        "contract_price_stated": _core("1234.56"),
        "value_approach_used": _core("SAMPLE"),
        "property_owner_of_record": _core("SAMPLE"),
        "prior_sale_date": _core("2024-01-15"),
        "prior_sale_price": _core("1234.56"),
        "condition_rating": _core("SAMPLE"),
        "quality_rating": _core("SAMPLE"),
        "appraisal_completion_condition": _core("SAMPLE"),
        "repairs_required_indicator": _core("SAMPLE"),
        "fha_condition_deficiencies": _core("SAMPLE"),
        "estimated_monthly_market_rent": _core("1234.56"),
        "rent_schedule_attached": _core("SAMPLE"),
        "comparable_count": _core(1),
    },
    "additional_sections": [{"section": "Other", "fields": [{"label": "Note", "value": "x"}]}],
    "comparable_sales": [
        {
            "comp_number": 2024,
            "address": "SAMPLE",
            "sale_price": "1234.56",
            "sale_date": "2024-01-15",
            "gross_living_area": 2024,
            "distance_from_subject": "SAMPLE",
            "net_adjustment": "1234.56",
            "adjusted_value": "1234.56",
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
    d = _parse_appraisal_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.uad_version.value == "SAMPLE"
    assert d.uad_version.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"uad_version": _core(None)}}
    parsed = _parse_appraisal_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_appraisal_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_appraisal(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_appraisal(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = AppraisalExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == AppraisalExtraction()

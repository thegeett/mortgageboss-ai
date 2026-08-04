"""Tests for property profile subject extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.property_profile_subject import (
    PropertyProfileSubjectExtraction,
    PropertyProfileSubjectExtractionResult,
    _parse_property_profile_subject_json,
    extract_property_profile_subject,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy property_profile_subject"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "document_title": _core("SAMPLE"),
        "issuer_name": _core("SAMPLE"),
        "data_source": _core("SAMPLE"),
        "report_date": _core("2024-01-15"),
        "property_address": _core("SAMPLE"),
        "parcel_or_apn": _core("SAMPLE"),
        "legal_description": _core("SAMPLE"),
        "owner_name": _core("SAMPLE"),
        "owner_name_2": _core("SAMPLE"),
        "owner_count": _core(2024),
        "owner_mailing_address": _core("SAMPLE"),
        "property_type": _core("SAMPLE"),
        "number_of_units": _core(2024),
        "year_built": _core(2024),
        "gross_living_area": _core("SAMPLE"),
        "occupancy_or_homestead_status": _core("SAMPLE"),
        "total_assessed_value": _core("1234.56"),
        "assessment_tax_year": _core(2024),
        "annual_tax_amount": _core("1234.56"),
        "tax_status": _core("SAMPLE"),
        "automated_or_reported_value": _core("1234.56"),
        "valuation_date": _core("2024-01-15"),
        "flood_zone": _core("SAMPLE"),
        "subject_property_indicator": _core("SAMPLE"),
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
    d = _parse_property_profile_subject_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.document_title.value == "SAMPLE"
    assert d.document_title.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"document_title": _core(None)}}
    parsed = _parse_property_profile_subject_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_property_profile_subject_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_property_profile_subject(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_property_profile_subject(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = PropertyProfileSubjectExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == PropertyProfileSubjectExtraction()

"""Tests for survey extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.survey import (
    SurveyExtraction,
    SurveyExtractionResult,
    _parse_survey_json,
    extract_survey,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy survey"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "document_title": _core("SAMPLE"),
        "survey_type": _core("SAMPLE"),
        "survey_date": _core("2024-01-15"),
        "fieldwork_date": _core("2024-01-15"),
        "surveyor_name": _core("SAMPLE"),
        "surveyor_firm": _core("SAMPLE"),
        "surveyor_license_number": _core("SAMPLE"),
        "surveyor_license_state": _core("SAMPLE"),
        "client_name": _core("SAMPLE"),
        "client_name_2": _core("SAMPLE"),
        "client_count": _core(2024),
        "property_address": _core("SAMPLE"),
        "parcel_or_apn": _core("SAMPLE"),
        "legal_description": _core("SAMPLE"),
        "record_owner": _core("SAMPLE"),
        "project_or_job_number": _core("SAMPLE"),
        "area_or_land_quantity": _core("SAMPLE"),
        "flood_zone": _core("SAMPLE"),
        "flood_map_panel": _core("SAMPLE"),
        "surveyor_certification_text": _core("SAMPLE"),
        "surveyor_signature_date": _core("2024-01-15"),
        "seal_present": _core("SAMPLE"),
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
    d = _parse_survey_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.document_title.value == "SAMPLE"
    assert d.document_title.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"document_title": _core(None)}}
    parsed = _parse_survey_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_survey_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_survey(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_survey(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = SurveyExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == SurveyExtraction()

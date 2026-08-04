"""Tests for flood certification extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.flood_certification import (
    FloodCertificationExtraction,
    FloodCertificationExtractionResult,
    _parse_flood_certification_json,
    extract_flood_certification,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy flood_certification"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "flood_zone": _core("SAMPLE"),
        "special_flood_hazard_area_indicator": _core("SAMPLE"),
        "property_address": _core("SAMPLE"),
        "property_description_or_parcel": _core("SAMPLE"),
        "federal_flood_insurance_available": _core("SAMPLE"),
        "coastal_barrier_or_opa_indicator": _core("SAMPLE"),
        "nfip_community_name": _core("SAMPLE"),
        "nfip_community_number": _core("SAMPLE"),
        "county": _core("SAMPLE"),
        "map_panel_number": _core("SAMPLE"),
        "map_panel_suffix": _core("SAMPLE"),
        "map_effective_or_revised_date": _core("2024-01-15"),
        "determination_date": _core("2024-01-15"),
        "determination_company_name": _core("SAMPLE"),
        "determination_identifier": _core("SAMPLE"),
        "determination_method_or_source": _core("SAMPLE"),
        "lender_name_and_address": _core("SAMPLE"),
        "lender_id_or_loan_number": _core("SAMPLE"),
        "borrower_name": _core("SAMPLE"),
        "life_of_loan_tracking_indicator": _core("SAMPLE"),
        "form_number": _core("SAMPLE"),
        "comments_or_manual_review": _core("SAMPLE"),
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
    d = _parse_flood_certification_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.flood_zone.value == "SAMPLE"
    assert d.flood_zone.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"flood_zone": _core(None)}}
    parsed = _parse_flood_certification_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_flood_certification_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_flood_certification(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_flood_certification(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = FloodCertificationExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == FloodCertificationExtraction()

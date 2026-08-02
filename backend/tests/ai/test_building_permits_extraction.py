"""Tests for building permits extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.building_permits import (
    BuildingPermitsExtraction,
    BuildingPermitsExtractionResult,
    _parse_building_permits_json,
    extract_building_permits,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy building_permits"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "issuing_jurisdiction_or_department": _core("SAMPLE"),
        "permit_number": _core("SAMPLE"),
        "parent_job_or_plan_number": _core("SAMPLE"),
        "permit_type": _core("SAMPLE"),
        "permit_status": _core("SAMPLE"),
        "property_address": _core("SAMPLE"),
        "parcel_or_tax_map_number": _core("SAMPLE"),
        "owner_name": _core("SAMPLE"),
        "owner_address": _core("SAMPLE"),
        "structure_type": _core("SAMPLE"),
        "type_of_work": _core("SAMPLE"),
        "project_description": _core("SAMPLE"),
        "estimated_construction_cost": _core("1234.56"),
        "occupancy_or_use_classification": _core("SAMPLE"),
        "application_date": _core("2024-01-15"),
        "issue_date": _core("2024-01-15"),
        "final_or_close_date": _core("2024-01-15"),
        "expiration_date": _core("2024-01-15"),
        "applicant_name": _core("SAMPLE"),
        "contractor_company": _core("SAMPLE"),
        "owner_as_contractor_indicator": _core("SAMPLE"),
        "account_case_reference_number": _core("SAMPLE"),
    },
    "additional_sections": [{"section": "Other", "fields": [{"label": "Note", "value": "x"}]}],
    "inspection_results": [
        {"type": "SAMPLE", "date": "2024-01-15", "result": "SAMPLE", "page": 1, "snippet": "s"}
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
    d = _parse_building_permits_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.issuing_jurisdiction_or_department.value == "SAMPLE"
    assert d.issuing_jurisdiction_or_department.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"issuing_jurisdiction_or_department": _core(None)}}
    parsed = _parse_building_permits_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_building_permits_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_building_permits(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_building_permits(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = BuildingPermitsExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == BuildingPermitsExtraction()

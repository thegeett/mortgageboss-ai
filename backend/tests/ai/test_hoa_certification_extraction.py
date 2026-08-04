"""Tests for hoa certification extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.hoa_certification import (
    HoaCertificationExtraction,
    HoaCertificationExtractionResult,
    _parse_hoa_certification_json,
    extract_hoa_certification,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy hoa_certification"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "association_or_project_name": _core("SAMPLE"),
        "project_address": _core("SAMPLE"),
        "unit_address_or_number": _core("SAMPLE"),
        "association_management_company": _core("SAMPLE"),
        "association_contact_phone": _core("SAMPLE"),
        "project_type": _core("SAMPLE"),
        "total_units": _core(2024),
        "units_sold_or_conveyed": _core(2024),
        "developer_control_status": _core("SAMPLE"),
        "owner_occupied_units": _core(2024),
        "investor_owned_units": _core(2024),
        "rental_or_short_term_rental_restrictions": _core("SAMPLE"),
        "single_entity_ownership_concentration": _core("SAMPLE"),
        "commercial_space_percentage": _core("SAMPLE"),
        "regular_hoa_dues": _core("1234.56"),
        "dues_frequency": _core("SAMPLE"),
        "delinquent_units_percentage": _core("SAMPLE"),
        "annual_budget": _core("1234.56"),
        "master_insurance_carrier": _core("SAMPLE"),
        "master_insurance_amount": _core("1234.56"),
        "completed_by_name_title": _core("SAMPLE"),
        "completion_date": _core("2024-01-15"),
    },
    "additional_sections": [{"section": "Other", "fields": [{"label": "Note", "value": "x"}]}],
    "special_assessments": [
        {
            "description": "SAMPLE",
            "amount": "1234.56",
            "status": "SAMPLE",
            "date": "2024-01-15",
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
    d = _parse_hoa_certification_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.association_or_project_name.value == "SAMPLE"
    assert d.association_or_project_name.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"association_or_project_name": _core(None)}}
    parsed = _parse_hoa_certification_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_hoa_certification_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_hoa_certification(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_hoa_certification(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = HoaCertificationExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == HoaCertificationExtraction()

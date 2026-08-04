"""Tests for cpa letter extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.cpa_letter import (
    CpaLetterExtraction,
    CpaLetterExtractionResult,
    _parse_cpa_letter_json,
    extract_cpa_letter,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy cpa_letter"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "cpa_name": _core("SAMPLE"),
        "cpa_firm_name": _core("SAMPLE"),
        "cpa_firm_address": _core("SAMPLE"),
        "cpa_license_number": _core("SAMPLE"),
        "cpa_license_state": _core("SAMPLE"),
        "license_status_or_verification": _core("SAMPLE"),
        "client_or_borrower_names": _core("SAMPLE"),
        "business_legal_name": _core("SAMPLE"),
        "entity_type": _core("SAMPLE"),
        "borrower_ownership_percentage": _core("SAMPLE"),
        "business_start_date_or_operating_duration": _core("SAMPLE"),
        "business_address_and_activity": _core("SAMPLE"),
        "cpa_client_relationship_start_date": _core("2024-01-15"),
        "business_existence_assertion": _core("SAMPLE"),
        "self_employment_status_assertion": _core("SAMPLE"),
        "income_or_compensation_facts": _core("SAMPLE"),
        "business_liquidity_or_withdrawal_impact_statement": _core("SAMPLE"),
        "scope_limitations_and_disclaimers": _core("SAMPLE"),
        "letter_date": _core("2024-01-15"),
        "cpa_signature": _core("SAMPLE"),
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
    d = _parse_cpa_letter_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.cpa_name.value == "SAMPLE"
    assert d.cpa_name.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"cpa_name": _core(None)}}
    parsed = _parse_cpa_letter_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_cpa_letter_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_cpa_letter(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_cpa_letter(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = CpaLetterExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == CpaLetterExtraction()

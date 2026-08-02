"""Tests for unsecured note extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.unsecured_note import (
    UnsecuredNoteExtraction,
    UnsecuredNoteExtractionResult,
    _parse_unsecured_note_json,
    extract_unsecured_note,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy unsecured_note"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "document_title": _core("SAMPLE"),
        "note_date": _core("2024-01-15"),
        "note_reference_number": _core("SAMPLE"),
        "maker_name": _core("SAMPLE"),
        "maker_name_2": _core("SAMPLE"),
        "maker_count": _core(2024),
        "payee_name": _core("SAMPLE"),
        "payee_name_2": _core("SAMPLE"),
        "unsecured_indicator": _core("SAMPLE"),
        "original_principal_amount": _core("1234.56"),
        "current_principal_balance": _core("1234.56"),
        "interest_rate": _core("SAMPLE"),
        "payment_amount": _core("1234.56"),
        "payment_frequency": _core("SAMPLE"),
        "first_payment_date": _core("2024-01-15"),
        "payment_due_day_or_schedule": _core("SAMPLE"),
        "maturity_date": _core("2024-01-15"),
        "balloon_payment": _core("1234.56"),
        "amortization_term": _core("SAMPLE"),
        "prepayment_terms": _core("SAMPLE"),
        "default_and_acceleration_terms": _core("SAMPLE"),
        "note_city_and_state": _core("SAMPLE"),
        "makers_signed": _core("SAMPLE"),
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
    d = _parse_unsecured_note_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.document_title.value == "SAMPLE"
    assert d.document_title.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"document_title": _core(None)}}
    parsed = _parse_unsecured_note_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_unsecured_note_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_unsecured_note(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_unsecured_note(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = UnsecuredNoteExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == UnsecuredNoteExtraction()

"""Tests for government issued id extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.government_issued_id import (
    GovernmentIssuedIdExtraction,
    GovernmentIssuedIdExtractionResult,
    _parse_government_issued_id_json,
    extract_government_issued_id,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy government_issued_id"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "government_id_type": _core("SAMPLE"),
        "issuing_country": _core("SAMPLE"),
        "issuing_authority": _core("SAMPLE"),
        "document_number": _core("SAMPLE"),
        "full_legal_name": _core("SAMPLE"),
        "date_of_birth": _core("2024-01-15"),
        "expiration_date": _core("2024-01-15"),
        "issue_date": _core("2024-01-15"),
        "document_status": _core("SAMPLE"),
        "place_of_birth": _core("SAMPLE"),
        "nationality_or_citizenship": _core("SAMPLE"),
        "sex": _core("SAMPLE"),
        "residential_address": _core("SAMPLE"),
        "photo_present": _core("SAMPLE"),
        "signature_present": _core("SAMPLE"),
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
    d = _parse_government_issued_id_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.government_id_type.value == "SAMPLE"
    assert d.government_id_type.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"government_id_type": _core(None)}}
    parsed = _parse_government_issued_id_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_government_issued_id_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_government_issued_id(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_government_issued_id(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = GovernmentIssuedIdExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == GovernmentIssuedIdExtraction()

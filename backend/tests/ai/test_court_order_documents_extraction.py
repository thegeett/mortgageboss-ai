"""Tests for court order documents extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.court_order_documents import (
    CourtOrderDocumentsExtraction,
    CourtOrderDocumentsExtractionResult,
    _parse_court_order_documents_json,
    extract_court_order_documents,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy court_order_documents"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "court_name": _core("SAMPLE"),
        "jurisdiction_and_division": _core("SAMPLE"),
        "case_number": _core("SAMPLE"),
        "case_caption": _core("SAMPLE"),
        "document_or_order_type": _core("SAMPLE"),
        "entry_or_order_date": _core("2024-01-15"),
        "effective_date": _core("2024-01-15"),
        "final_or_interlocutory_status": _core("SAMPLE"),
        "obligor_name": _core("SAMPLE"),
        "obligee_name": _core("SAMPLE"),
        "current_compliance_or_enforcement_status": _core("SAMPLE"),
        "judge_name_and_signature": _core("SAMPLE"),
    },
    "additional_sections": [{"section": "Other", "fields": [{"label": "Note", "value": "x"}]}],
    "support_awards": [
        {
            "award_type": "SAMPLE",
            "amount": "1234.56",
            "frequency": "SAMPLE",
            "start_date": "2024-01-15",
            "end_date": "2024-01-15",
            "payer": "SAMPLE",
            "payee": "SAMPLE",
            "escalation_or_conditions": "SAMPLE",
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
    d = _parse_court_order_documents_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.court_name.value == "SAMPLE"
    assert d.court_name.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"court_name": _core(None)}}
    parsed = _parse_court_order_documents_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_court_order_documents_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_court_order_documents(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_court_order_documents(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = CourtOrderDocumentsExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == CourtOrderDocumentsExtraction()

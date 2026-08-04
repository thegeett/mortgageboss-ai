"""Tests for application loe extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.application_loe import (
    ApplicationLoeExtraction,
    ApplicationLoeExtractionResult,
    _parse_application_loe_json,
    extract_application_loe,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy application_loe"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "borrower_name": _core("SAMPLE"),
        "borrower_name_2": _core("SAMPLE"),
        "letter_date": _core("2024-01-15"),
        "recipient_or_lender_name": _core("SAMPLE"),
        "issuer_name": _core("SAMPLE"),
        "application_issue_type": _core("SAMPLE"),
        "application_section_or_question": _core("SAMPLE"),
        "facts_being_explained": _core("SAMPLE"),
        "reason_or_root_cause": _core("SAMPLE"),
        "corrective_action_or_resolution": _core("SAMPLE"),
        "current_status": _core("SAMPLE"),
        "future_expectation_or_recurrence": _core("SAMPLE"),
        "accuracy_certification": _core("SAMPLE"),
        "borrower_signature_present": _core("SAMPLE"),
        "borrower_signature_date": _core("2024-01-15"),
        "preparer_name": _core("SAMPLE"),
        "property_address": _core("SAMPLE"),
        "loan_number": _core("SAMPLE"),
    },
    "additional_sections": [{"section": "Other", "fields": [{"label": "Note", "value": "x"}]}],
    "event_chronology": [
        {"date": "2024-01-15", "event": "SAMPLE", "source": "SAMPLE", "page": 1, "snippet": "s"}
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
    d = _parse_application_loe_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.borrower_name.value == "SAMPLE"
    assert d.borrower_name.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"borrower_name": _core(None)}}
    parsed = _parse_application_loe_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_application_loe_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_application_loe(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_application_loe(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = ApplicationLoeExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == ApplicationLoeExtraction()

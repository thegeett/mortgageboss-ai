"""Tests for uscis notice of action extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.uscis_notice_of_action import (
    UscisNoticeOfActionExtraction,
    UscisNoticeOfActionExtractionResult,
    _parse_uscis_notice_of_action_json,
    extract_uscis_notice_of_action,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy uscis_notice_of_action"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "form_type": _core("SAMPLE"),
        "notice_type": _core("SAMPLE"),
        "receipt_number": _core("SAMPLE"),
        "case_type": _core("SAMPLE"),
        "received_date": _core("2024-01-15"),
        "notice_date": _core("2024-01-15"),
        "petitioner_name": _core("SAMPLE"),
        "beneficiary_name": _core("SAMPLE"),
        "beneficiary_a_number": _core("SAMPLE"),
        "beneficiary_date_of_birth": _core("2024-01-15"),
        "beneficiary_country_of_citizenship": _core("SAMPLE"),
        "classification": _core("SAMPLE"),
        "validity_from": _core("2024-01-15"),
        "validity_to": _core("2024-01-15"),
        "petition_valid_from": _core("2024-01-15"),
        "petition_valid_to": _core("2024-01-15"),
        "i94_number": _core("SAMPLE"),
        "i94_class_of_admission": _core("SAMPLE"),
        "priority_date": _core("2024-01-15"),
        "service_center": _core("SAMPLE"),
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
    d = _parse_uscis_notice_of_action_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.form_type.value == "SAMPLE"
    assert d.form_type.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"form_type": _core(None)}}
    parsed = _parse_uscis_notice_of_action_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_uscis_notice_of_action_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_uscis_notice_of_action(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_uscis_notice_of_action(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = UscisNoticeOfActionExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == UscisNoticeOfActionExtraction()

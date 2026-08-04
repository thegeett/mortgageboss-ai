"""Tests for form 4506t request for transcript extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.form_4506t_request_for_transcript import (
    Form4506tRequestForTranscriptExtraction,
    Form4506tRequestForTranscriptExtractionResult,
    _parse_form_4506t_request_for_transcript_json,
    extract_form_4506t_request_for_transcript,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy form_4506t_request_for_transcript"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "issuer_name": _core("SAMPLE"),
        "form_revision": _core("SAMPLE"),
        "tax_form_number_requested": _core("SAMPLE"),
        "taxpayer_name_on_return": _core("SAMPLE"),
        "taxpayer_tin": _core("SAMPLE"),
        "spouse_name_on_joint_return": _core("SAMPLE"),
        "spouse_tin": _core("SAMPLE"),
        "current_address": _core("SAMPLE"),
        "previous_address_on_last_return": _core("SAMPLE"),
        "customer_file_number": _core("SAMPLE"),
        "taxpayer_phone": _core("SAMPLE"),
        "tax_years_or_periods_requested": _core("SAMPLE"),
        "return_transcript_selected": _core("SAMPLE"),
        "account_transcript_selected": _core("SAMPLE"),
        "record_of_account_selected": _core("SAMPLE"),
        "verification_of_nonfiling_selected": _core("SAMPLE"),
        "w2_1099_1098_5498_transcript_selected": _core("SAMPLE"),
        "signatory_attestation_checked": _core("SAMPLE"),
        "taxpayer_signature_and_date": _core("SAMPLE"),
        "spouse_signature_and_date": _core("SAMPLE"),
        "signer_title_or_capacity": _core("SAMPLE"),
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
    d = _parse_form_4506t_request_for_transcript_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.issuer_name.value == "SAMPLE"
    assert d.issuer_name.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"issuer_name": _core(None)}}
    parsed = _parse_form_4506t_request_for_transcript_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_form_4506t_request_for_transcript_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_form_4506t_request_for_transcript(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_form_4506t_request_for_transcript(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = Form4506tRequestForTranscriptExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == Form4506tRequestForTranscriptExtraction()

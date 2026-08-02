"""Tests for foster care verification extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.foster_care_verification import (
    FosterCareVerificationExtraction,
    FosterCareVerificationExtractionResult,
    _parse_foster_care_verification_json,
    extract_foster_care_verification,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy foster_care_verification"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "issuer_name": _core("SAMPLE"),
        "government_agency_or_provider": _core("SAMPLE"),
        "agency_contact_phone": _core("SAMPLE"),
        "recipient_or_foster_parent_name": _core("SAMPLE"),
        "recipient_or_foster_parent_name_2": _core("SAMPLE"),
        "recipient_or_foster_parent_count": _core(2024),
        "case_provider_or_account_number_masked": _core("SAMPLE"),
        "verification_date": _core("2024-01-15"),
        "program_or_payment_type": _core("SAMPLE"),
        "placement_start_date": _core("2024-01-15"),
        "placement_end_or_review_date": _core("2024-01-15"),
        "current_placement_status": _core("SAMPLE"),
        "gross_payment_amount": _core("1234.56"),
        "payment_frequency": _core("SAMPLE"),
        "taxable_status": _core("SAMPLE"),
        "termination_or_change_events": _core("SAMPLE"),
        "expected_continuance_statement": _core("SAMPLE"),
        "verifier_name_title": _core("SAMPLE"),
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
    d = _parse_foster_care_verification_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.issuer_name.value == "SAMPLE"
    assert d.issuer_name.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"issuer_name": _core(None)}}
    parsed = _parse_foster_care_verification_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_foster_care_verification_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_foster_care_verification(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_foster_care_verification(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = FosterCareVerificationExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == FosterCareVerificationExtraction()

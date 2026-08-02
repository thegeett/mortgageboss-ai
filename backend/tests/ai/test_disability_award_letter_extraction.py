"""Tests for disability award letter extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.disability_award_letter import (
    DisabilityAwardLetterExtraction,
    DisabilityAwardLetterExtractionResult,
    _parse_disability_award_letter_json,
    extract_disability_award_letter,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy disability_award_letter"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "issuer_name": _core("SAMPLE"),
        "awarding_agency_or_insurer": _core("SAMPLE"),
        "beneficiary_name": _core("SAMPLE"),
        "claim_or_account_number_masked": _core("SAMPLE"),
        "benefit_program_or_policy": _core("SAMPLE"),
        "award_letter_date": _core("2024-01-15"),
        "disability_status": _core("SAMPLE"),
        "disability_onset_or_entitlement_date": _core("2024-01-15"),
        "gross_benefit_amount": _core("1234.56"),
        "payment_frequency": _core("SAMPLE"),
        "net_benefit_amount": _core("1234.56"),
        "taxable_status": _core("SAMPLE"),
        "benefit_start_date": _core("2024-01-15"),
        "benefit_end_or_review_date": _core("2024-01-15"),
        "continuation_or_permanency_statement": _core("SAMPLE"),
        "retroactive_or_lump_sum_amount": _core("1234.56"),
        "appeal_or_pending_review_status": _core("SAMPLE"),
        "agency_contact_information": _core("SAMPLE"),
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
    d = _parse_disability_award_letter_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.issuer_name.value == "SAMPLE"
    assert d.issuer_name.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"issuer_name": _core(None)}}
    parsed = _parse_disability_award_letter_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_disability_award_letter_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_disability_award_letter(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_disability_award_letter(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = DisabilityAwardLetterExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == DisabilityAwardLetterExtraction()

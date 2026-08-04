"""Tests for social security award letter extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.social_security_award_letter import (
    SocialSecurityAwardLetterExtraction,
    SocialSecurityAwardLetterExtractionResult,
    _parse_social_security_award_letter_json,
    extract_social_security_award_letter,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy social_security_award_letter"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "social_security_administration": _core("SAMPLE"),
        "beneficiary_name": _core("SAMPLE"),
        "claim_number_masked": _core("SAMPLE"),
        "benefit_type": _core("SAMPLE"),
        "award_or_benefit_verification_letter_date": _core("2024-01-15"),
        "entitlement_or_effective_date": _core("2024-01-15"),
        "gross_monthly_benefit": _core("1234.56"),
        "net_monthly_payment": _core("1234.56"),
        "payment_schedule_or_day": _core("SAMPLE"),
        "next_payment_date": _core("2024-01-15"),
        "retroactive_benefit_amount": _core("1234.56"),
        "cost_of_living_adjustment": _core("1234.56"),
        "benefit_end_or_review_date": _core("2024-01-15"),
        "continuation_or_age_dependency_terms": _core("SAMPLE"),
        "representative_payee": _core("SAMPLE"),
    },
    "additional_sections": [{"section": "Other", "fields": [{"label": "Note", "value": "x"}]}],
    "medicare_or_other_deductions": [
        {"label": "SAMPLE", "amount": "1234.56", "source": "SAMPLE", "page": 1, "snippet": "s"}
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
    d = _parse_social_security_award_letter_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.social_security_administration.value == "SAMPLE"
    assert d.social_security_administration.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"social_security_administration": _core(None)}}
    parsed = _parse_social_security_award_letter_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_social_security_award_letter_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_social_security_award_letter(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_social_security_award_letter(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = SocialSecurityAwardLetterExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == SocialSecurityAwardLetterExtraction()

"""Tests for retirement check extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.retirement_check import (
    RetirementCheckExtraction,
    RetirementCheckExtractionResult,
    _parse_retirement_check_json,
    extract_retirement_check,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy retirement_check"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "document_title": _core("SAMPLE"),
        "payer_or_plan_name": _core("SAMPLE"),
        "payer_bank_name": _core("SAMPLE"),
        "payee_or_retiree_name": _core("SAMPLE"),
        "check_number": _core("SAMPLE"),
        "check_date": _core("2024-01-15"),
        "benefit_period_start": _core("2024-01-15"),
        "benefit_period_end": _core("2024-01-15"),
        "benefit_type": _core("SAMPLE"),
        "plan_claim_or_account_last4": _core("SAMPLE"),
        "gross_benefit_amount": _core("1234.56"),
        "net_check_amount": _core("1234.56"),
        "written_amount": _core("SAMPLE"),
        "payment_frequency": _core("SAMPLE"),
        "memo_or_benefit_reference": _core("SAMPLE"),
        "front_image_present": _core("SAMPLE"),
        "back_image_present": _core("SAMPLE"),
        "payee_endorsement": _core("SAMPLE"),
        "deposit_account_last4": _core("SAMPLE"),
        "cleared_or_posted_date": _core("2024-01-15"),
        "void_stop_orreturn_status": _core("SAMPLE"),
        "related_award_orstatement_reference": _core("SAMPLE"),
        "loan_number": _core("SAMPLE"),
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
    d = _parse_retirement_check_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.document_title.value == "SAMPLE"
    assert d.document_title.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"document_title": _core(None)}}
    parsed = _parse_retirement_check_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_retirement_check_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_retirement_check(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_retirement_check(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = RetirementCheckExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == RetirementCheckExtraction()

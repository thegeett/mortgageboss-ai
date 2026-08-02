"""Tests for credit report extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.credit_report import (
    CreditReportExtraction,
    CreditReportExtractionResult,
    _parse_credit_report_json,
    extract_credit_report,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy credit_report"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "borrower_name": _core("SAMPLE"),
        "co_borrower_name": _core("SAMPLE"),
        "borrower_ssn": _core("SAMPLE"),
        "co_borrower_ssn": _core("SAMPLE"),
        "borrower_date_of_birth": _core("2024-01-15"),
        "borrower_current_address": _core("SAMPLE"),
        "borrower_former_address": _core("SAMPLE"),
        "report_date": _core("2024-01-15"),
        "score_date": _core("2024-01-15"),
        "report_provider": _core("SAMPLE"),
        "report_reference_number": _core("SAMPLE"),
        "credit_report_type": _core("SAMPLE"),
        "score_equifax": _core(2024),
        "score_experian": _core(2024),
        "score_transunion": _core(2024),
        "score_model": _core("SAMPLE"),
        "tradeline_count": _core(2024),
        "total_monthly_debt_payment": _core("1234.56"),
        "public_record_count": _core(2024),
        "inquiry_count": _core(2024),
        "security_freeze_or_fraud_alert": _core("SAMPLE"),
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
    d = _parse_credit_report_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.borrower_name.value == "SAMPLE"
    assert d.borrower_name.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"borrower_name": _core(None)}}
    parsed = _parse_credit_report_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_credit_report_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_credit_report(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_credit_report(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = CreditReportExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == CreditReportExtraction()

"""Tests for military leave and earning statement les extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.military_leave_and_earning_statement_les import (
    MilitaryLeaveAndEarningStatementLesExtraction,
    MilitaryLeaveAndEarningStatementLesExtractionResult,
    _parse_military_leave_and_earning_statement_les_json,
    extract_military_leave_and_earning_statement_les,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy military_leave_and_earning_statement_les"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "document_title": _core("SAMPLE"),
        "issuer_name": _core("SAMPLE"),
        "service_member_name": _core("SAMPLE"),
        "social_security_number_masked": _core("SAMPLE"),
        "pay_grade": _core("SAMPLE"),
        "branch_or_component": _core("SAMPLE"),
        "pay_period": _core("SAMPLE"),
        "pay_date_or_service_date": _core("2024-01-15"),
        "years_of_service": _core("1234.56"),
        "ets_or_service_expiration_date": _core("2024-01-15"),
        "duty_station": _core("SAMPLE"),
        "bah_dependency_status": _core("SAMPLE"),
        "gross_entitlements": _core("1234.56"),
        "total_deductions": _core("1234.56"),
        "total_allotments": _core("1234.56"),
        "net_pay": _core("1234.56"),
        "end_of_month_pay": _core("1234.56"),
        "federal_tax_data": _core("SAMPLE"),
        "fica_tax_data": _core("SAMPLE"),
        "state_tax_data": _core("SAMPLE"),
        "leave_balance": _core("SAMPLE"),
        "direct_deposit_account_last4": _core("SAMPLE"),
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
    d = _parse_military_leave_and_earning_statement_les_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.document_title.value == "SAMPLE"
    assert d.document_title.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"document_title": _core(None)}}
    parsed = _parse_military_leave_and_earning_statement_les_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_military_leave_and_earning_statement_les_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_military_leave_and_earning_statement_les(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_military_leave_and_earning_statement_les(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = MilitaryLeaveAndEarningStatementLesExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == MilitaryLeaveAndEarningStatementLesExtraction()

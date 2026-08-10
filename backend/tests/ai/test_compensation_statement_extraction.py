"""Tests for compensation statement extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.compensation_statement import (
    CompensationStatementExtraction,
    CompensationStatementExtractionResult,
    _parse_compensation_statement_json,
    extract_compensation_statement,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy compensation_statement"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "employee_name": _core("SAMPLE"),
        "employer_name": _core("SAMPLE"),
        "effective_date": _core("2024-01-15"),
        "base_pay_current": _core("1234.56"),
        "base_pay_new": _core("1234.56"),
        "base_pay_increase_amount": _core("1234.56"),
        "base_pay_increase_percent": _core("1234.56"),
        "bonus_target_percent": _core("1234.56"),
        "bonus_actual_award": _core("1234.56"),
        "equity_award_amount": _core("1234.56"),
        "equity_award_type": _core("SAMPLE"),
        "one_time_payment_amount": _core("1234.56"),
        "performance_rating": _core("SAMPLE"),
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
    d = _parse_compensation_statement_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.employee_name.value == "SAMPLE"
    assert d.employee_name.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"employee_name": _core(None)}}
    parsed = _parse_compensation_statement_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_compensation_statement_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_compensation_statement(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_compensation_statement(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = CompensationStatementExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == CompensationStatementExtraction()

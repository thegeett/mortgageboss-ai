"""Tests for VOE extraction (LP-60) — the AI wrapper is MOCKED.

Follows the W-2 test template. Focus: the typed core is coerced (names/title/
status/frequency→str, dates→date, income/ytd/hours→Decimal) with source; nothing
dropped; honest nulls; graceful failure; metadata-only logging.

No real VOE sample documents were available — these verify the mechanism/shape,
not accuracy against real forms (validated as real documents flow through; field
set refined with Priya).
"""

import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import structlog
from app.ai.client import AIClientError
from app.ai.extraction import voe as voe_module
from app.ai.extraction.voe import VOEExtraction, VOEExtractionResult, _parse_voe_json, extract_voe
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy voe bytes"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "employer_name": _core("ACME Corp", snippet="Employer: ACME Corp"),
        "employee_name": _core("Jane Doe"),
        "position_title": _core("Senior Analyst"),
        "employment_status": _core("current", snippet="Currently employed"),
        "start_date": _core("2019-03-15", snippet="Hire date 03/15/2019"),
        "end_date": _core(None),
        "current_income_amount": _core("$85,000.00", snippet="Base 85,000.00/yr"),
        "income_frequency": _core("annual"),
        "ytd_income": _core("42000.00"),
        "hours": _core("40"),
        "probability_of_continued_employment": _core("likely"),
    },
    "additional_sections": [
        {
            "section": "Prior Year Earnings",
            "fields": [{"label": "2023 base", "value": "82000.00", "page": 1}],
        }
    ],
    "confidence": 0.9,
    "reasoning": "Standard VOE.",
}
FULL_JSON = json.dumps(FULL_PAYLOAD)


def _mock_complete(
    monkeypatch: pytest.MonkeyPatch, *, text: str | None = None, exc: Exception | None = None
) -> AsyncMock:
    if exc is not None:
        mock = AsyncMock(side_effect=exc)
    else:
        mock = AsyncMock(
            return_value=SimpleNamespace(text=text, input_tokens=160, output_tokens=70, model="m")
        )
    monkeypatch.setattr(voe_module, "complete", mock)
    return mock


def test_parse_full_shape_with_types() -> None:
    result = _parse_voe_json(FULL_JSON)
    assert result is not None
    assert result.status == ExtractionStatus.SUCCEEDED
    d = result.data
    assert d.employer_name.value == "ACME Corp"
    assert d.employment_status.value == "current"
    assert d.start_date.value == date(2019, 3, 15)  # coerced to a date
    assert d.current_income_amount.value == Decimal("85000.00")  # "$85,000.00"
    assert d.hours.value == Decimal("40")
    assert d.end_date.value is None  # honest null for a current employee
    assert [s.section for s in d.additional_sections] == ["Prior Year Earnings"]


def test_source_location_present() -> None:
    d = _parse_voe_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.start_date.source is not None and d.start_date.source.snippet == "Hire date 03/15/2019"


def test_junk_date_becomes_none_partial() -> None:
    payload = {
        "typed_core": {
            "employer_name": _core("ACME Corp"),
            "start_date": _core("sometime last year", snippet="last year"),
        },
        "confidence": 0.6,
    }
    result = _parse_voe_json(json.dumps(payload))
    assert result is not None
    assert result.data.start_date.value is None
    assert result.data.start_date.source is not None  # source kept
    assert result.status == ExtractionStatus.PARTIAL


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"employer_name": _core(None), "ytd_income": _core(None)}}
    result = _parse_voe_json(json.dumps(payload))
    assert result is not None
    assert result.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_voe_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_voe(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED
    assert result.data.employer_name.value == "ACME Corp"
    assert result.input_tokens == 160


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_voe(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


async def test_extract_empty_skips_api(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_voe(b"", "application/pdf")
    assert result.status == ExtractionStatus.FAILED
    assert mock.call_count == 0


async def test_does_not_log_values(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    with structlog.testing.capture_logs() as logs:
        await extract_voe(PDF_BYTES, "application/pdf")
    blob = " ".join(repr(e) for e in logs)
    assert "ACME Corp" not in blob and "85000" not in blob and "Jane Doe" not in blob
    done = [e for e in logs if e["event"] == "voe_extraction_done"]
    assert len(done) == 1 and done[0]["core_fields_present"] == 10


def test_failed_factory() -> None:
    result = VOEExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == VOEExtraction()

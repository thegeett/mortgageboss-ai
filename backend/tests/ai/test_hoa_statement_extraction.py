"""Tests for HOA statement extraction (LP-62) — the AI wrapper is MOCKED.

Focus: the typed core is coerced with source; the **property_address is captured**
(Phase 3 subject-vs-other matching); dues_amount + dues_frequency are the
obligation; honest nulls; graceful failure.

No real HOA statement samples were available — these verify the mechanism/shape,
not accuracy against real statements (validated as real documents flow through;
field set refined with Priya).
"""

import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.ai.client import AIClientError
from app.ai.extraction import hoa_statement as hoa_module
from app.ai.extraction.hoa_statement import (
    HOAStatementExtraction,
    HOAStatementExtractionResult,
    _parse_hoa_statement_json,
    extract_hoa_statement,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy hoa statement"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "association_name": _core("Oak Ridge HOA"),
        "property_address": _core("789 Pine Ct", snippet="789 Pine Ct"),
        "dues_amount": _core("$350.00", snippet="Monthly Dues 350.00"),
        "dues_frequency": _core("monthly"),
        "balance": _core("350.00"),
        "due_date": _core("2024-11-01"),
    },
    "additional_sections": [
        {"section": "Late Fees", "fields": [{"label": "Late fee", "value": "25.00"}]}
    ],
    "confidence": 0.9,
    "reasoning": "HOA statement.",
}
FULL_JSON = json.dumps(FULL_PAYLOAD)


def _mock_complete(
    monkeypatch: pytest.MonkeyPatch, *, text: str | None = None, exc: Exception | None = None
) -> AsyncMock:
    if exc is not None:
        mock = AsyncMock(side_effect=exc)
    else:
        mock = AsyncMock(
            return_value=SimpleNamespace(text=text, input_tokens=130, output_tokens=50, model="m")
        )
    monkeypatch.setattr(hoa_module, "complete", mock)
    return mock


def test_address_and_dues_obligation_captured() -> None:
    d = _parse_hoa_statement_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.property_address.value == "789 Pine Ct"  # captured for Phase 3 matching
    assert d.dues_amount.value == Decimal("350.00")  # "$350.00" coerced
    assert d.dues_frequency.value == "monthly"  # the obligation is monthly
    assert d.due_date.value == date(2024, 11, 1)


def test_source_location_present() -> None:
    d = _parse_hoa_statement_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.dues_amount.source is not None
    assert d.dues_amount.source.snippet == "Monthly Dues 350.00"


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"association_name": _core(None), "dues_amount": _core(None)}}
    result = _parse_hoa_statement_json(json.dumps(payload))
    assert result is not None
    assert result.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_hoa_statement_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_hoa_statement(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED
    assert result.data.property_address.value == "789 Pine Ct"


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_hoa_statement(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = HOAStatementExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == HOAStatementExtraction()

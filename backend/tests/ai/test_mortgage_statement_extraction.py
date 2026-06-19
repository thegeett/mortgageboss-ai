"""Tests for mortgage statement extraction (LP-62) — the AI wrapper is MOCKED.

Focus: the typed core is coerced with source; the **property_address is captured**
(for Phase 3 subject-vs-other matching); monthly_payment is the DTI obligation;
honest nulls; graceful failure.

No real mortgage statement samples were available — these verify the
mechanism/shape, not accuracy against real statements (validated as real documents
flow through; field set refined with Priya).
"""

import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.ai.client import AIClientError
from app.ai.extraction import mortgage_statement as ms_module
from app.ai.extraction.mortgage_statement import (
    MortgageStatementExtraction,
    MortgageStatementExtractionResult,
    _parse_mortgage_statement_json,
    extract_mortgage_statement,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy mortgage statement"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "lender_name": _core("Wells Fargo"),
        "property_address": _core("456 Oak Ave", snippet="Property: 456 Oak Ave"),
        "monthly_payment": _core("$2,150.00", snippet="Total Payment 2,150.00"),
        "unpaid_balance": _core("312000.00"),
        "escrow_amount": _core("450.00"),
        "due_date": _core("2024-11-01"),
    },
    "additional_sections": [
        {"section": "Payment Breakdown", "fields": [{"label": "Principal", "value": "900.00"}]}
    ],
    "confidence": 0.9,
    "reasoning": "Mortgage statement.",
}
FULL_JSON = json.dumps(FULL_PAYLOAD)


def _mock_complete(
    monkeypatch: pytest.MonkeyPatch, *, text: str | None = None, exc: Exception | None = None
) -> AsyncMock:
    if exc is not None:
        mock = AsyncMock(side_effect=exc)
    else:
        mock = AsyncMock(
            return_value=SimpleNamespace(text=text, input_tokens=150, output_tokens=60, model="m")
        )
    monkeypatch.setattr(ms_module, "complete", mock)
    return mock


def test_property_address_captured_for_subject_vs_other() -> None:
    """The property address is captured so Phase 3 can match subject-vs-other."""
    d = _parse_mortgage_statement_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.property_address.value == "456 Oak Ave"
    assert d.property_address.source is not None and d.property_address.source.page == 1


def test_parse_full_shape_with_types() -> None:
    result = _parse_mortgage_statement_json(FULL_JSON)
    assert result is not None
    assert result.status == ExtractionStatus.SUCCEEDED
    d = result.data
    assert d.monthly_payment.value == Decimal("2150.00")  # "$2,150.00" coerced (DTI obligation)
    assert d.unpaid_balance.value == Decimal("312000.00")
    assert d.due_date.value == date(2024, 11, 1)


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"lender_name": _core(None), "monthly_payment": _core(None)}}
    result = _parse_mortgage_statement_json(json.dumps(payload))
    assert result is not None
    assert result.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_mortgage_statement_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_mortgage_statement(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED
    assert result.data.property_address.value == "456 Oak Ave"


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_mortgage_statement(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = MortgageStatementExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == MortgageStatementExtraction()

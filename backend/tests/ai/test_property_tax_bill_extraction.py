"""Tests for property tax bill extraction (LP-62) — the AI wrapper is MOCKED.

Focus: the typed core is coerced with source; the **property_address is captured**
(Phase 3 subject-vs-other matching); ``due_dates`` stays a STRING (a bill often has
two installments); annual_tax_amount is the housing-expense/DTI figure; honest
nulls; graceful failure.

No real tax bill samples were available — these verify the mechanism/shape, not
accuracy against real bills (validated as real documents flow through; field set
refined with Priya).
"""

import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.ai.client import AIClientError
from app.ai.extraction import property_tax_bill as ptb_module
from app.ai.extraction.property_tax_bill import (
    PropertyTaxBillExtraction,
    PropertyTaxBillExtractionResult,
    _parse_property_tax_bill_json,
    extract_property_tax_bill,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy tax bill"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "property_address": _core("123 Main St", snippet="123 Main St"),
        "assessed_value": _core("1200000.00"),
        "annual_tax_amount": _core("$8,400.00", snippet="Total Tax 8,400.00"),
        "due_dates": _core("1st 11/01/2024; 2nd 02/01/2025", snippet="due 11/01 and 02/01"),
        "taxing_authority": _core("Santa Clara County"),
    },
    "additional_sections": [
        {"section": "Parcel", "fields": [{"label": "APN", "value": "123-45-678"}]}
    ],
    "confidence": 0.9,
    "reasoning": "County tax bill.",
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
    monkeypatch.setattr(ptb_module, "complete", mock)
    return mock


def test_address_captured_and_due_dates_string() -> None:
    d = _parse_property_tax_bill_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.property_address.value == "123 Main St"  # captured for Phase 3 matching
    assert d.annual_tax_amount.value == Decimal("8400.00")  # housing/DTI figure
    # due_dates is a string — both installments preserved verbatim.
    assert d.due_dates.value == "1st 11/01/2024; 2nd 02/01/2025"


def test_source_location_present() -> None:
    d = _parse_property_tax_bill_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.annual_tax_amount.source is not None
    assert d.annual_tax_amount.source.snippet == "Total Tax 8,400.00"


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"property_address": _core(None), "annual_tax_amount": _core(None)}}
    result = _parse_property_tax_bill_json(json.dumps(payload))
    assert result is not None
    assert result.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_property_tax_bill_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_property_tax_bill(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED
    assert result.data.property_address.value == "123 Main St"


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_property_tax_bill(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = PropertyTaxBillExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == PropertyTaxBillExtraction()

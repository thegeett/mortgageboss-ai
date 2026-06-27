"""Tests for purchase agreement extraction (LP-62) — the AI wrapper is MOCKED.

Follows the existing extractor test template. Focus: the typed core is coerced
(names/address→str, sales_price/earnest→Decimal, closing_date→date) with source;
terms land in the catch-all; honest nulls; graceful failure; metadata-only logging.

No real purchase agreement samples were available — these verify the
mechanism/shape, not accuracy against real contracts (validated as real documents
flow through; field set refined with Priya).
"""

import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import structlog
from app.ai.client import AIClientError
from app.ai.extraction import purchase_agreement as pa_module
from app.ai.extraction.purchase_agreement import (
    PurchaseAgreementExtraction,
    PurchaseAgreementExtractionResult,
    _parse_purchase_agreement_json,
    extract_purchase_agreement,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy purchase agreement"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "buyer_name": _core("Jane Doe"),
        "seller_name": _core("John Smith"),
        "property_address": _core("123 Main St, Anytown CA"),
        "sales_price": _core("$1,380,000.00", snippet="Purchase Price $1,380,000"),
        "closing_date": _core("2024-11-15", snippet="close 11/15/2024"),
        "earnest_money_amount": _core("50000.00"),
    },
    "additional_sections": [
        {"section": "Contingencies", "fields": [{"label": "Financing", "value": "30 days"}]}
    ],
    "confidence": 0.9,
    "reasoning": "Purchase agreement.",
}
FULL_JSON = json.dumps(FULL_PAYLOAD)


def _mock_complete(
    monkeypatch: pytest.MonkeyPatch, *, text: str | None = None, exc: Exception | None = None
) -> AsyncMock:
    if exc is not None:
        mock = AsyncMock(side_effect=exc)
    else:
        mock = AsyncMock(
            return_value=SimpleNamespace(text=text, input_tokens=170, output_tokens=80, model="m")
        )
    monkeypatch.setattr(pa_module, "complete", mock)
    return mock


def test_parse_full_shape_with_types() -> None:
    result = _parse_purchase_agreement_json(FULL_JSON)
    assert result is not None
    assert result.status == ExtractionStatus.SUCCEEDED
    d = result.data
    assert d.property_address.value == "123 Main St, Anytown CA"
    assert d.sales_price.value == Decimal("1380000.00")  # "$1,380,000.00" coerced (LTV basis)
    assert d.closing_date.value == date(2024, 11, 15)
    labels = [f.label for s in d.additional_sections for f in s.fields]
    assert "Financing" in labels


def test_source_location_present() -> None:
    d = _parse_purchase_agreement_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.sales_price.source is not None
    assert d.sales_price.source.snippet == "Purchase Price $1,380,000"


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"buyer_name": _core(None), "sales_price": _core(None)}}
    result = _parse_purchase_agreement_json(json.dumps(payload))
    assert result is not None
    assert result.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_purchase_agreement_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_purchase_agreement(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED
    assert result.data.sales_price.value == Decimal("1380000.00")


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_purchase_agreement(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("media_type", ["text/plain", ""])
async def test_extract_unsupported_skips_api(
    monkeypatch: pytest.MonkeyPatch, media_type: str
) -> None:
    mock = _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_purchase_agreement(PDF_BYTES, media_type)
    assert result.status == ExtractionStatus.FAILED
    assert mock.call_count == 0


async def test_does_not_log_values(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    with structlog.testing.capture_logs() as logs:
        await extract_purchase_agreement(PDF_BYTES, "application/pdf")
    blob = " ".join(repr(e) for e in logs)
    assert "Jane Doe" not in blob and "1380000" not in blob and "1,380,000" not in blob
    done = [e for e in logs if e["event"] == "purchase_agreement_extraction_done"]
    assert len(done) == 1 and done[0]["core_fields_present"] == 6


def test_failed_factory() -> None:
    result = PurchaseAgreementExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == PurchaseAgreementExtraction()

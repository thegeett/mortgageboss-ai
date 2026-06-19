"""Tests for Profit & Loss extraction (LP-60) — the AI wrapper is MOCKED.

Follows the W-2 test template. Focus: the typed core is coerced (business→str,
period→date, revenue/expenses/net_profit→Decimal) with source; the individual
expense lines land in the catch-all (nothing dropped); honest nulls; graceful
failure; metadata-only logging. ``net_profit`` is the key self-employment figure.

No real P&L sample documents were available — these verify the mechanism/shape,
not accuracy against real statements (validated as real documents flow through;
field set refined with Priya).
"""

import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import structlog
from app.ai.client import AIClientError
from app.ai.extraction import profit_and_loss as pnl_module
from app.ai.extraction.profit_and_loss import (
    ProfitAndLossExtraction,
    ProfitAndLossExtractionResult,
    _parse_pnl_json,
    extract_profit_and_loss,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy p&l bytes"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "business_name": _core("Doe Consulting LLC"),
        "period_start": _core("2024-01-01", snippet="Jan 1, 2024"),
        "period_end": _core("2024-12-31", snippet="Dec 31, 2024"),
        "total_revenue": _core("$210,000.00", snippet="Total Revenue 210,000.00"),
        "total_expenses": _core("113500.00"),
        "net_profit": _core("96500.00", snippet="Net Income 96,500.00"),
    },
    "additional_sections": [
        {
            "section": "Major Expenses",
            "fields": [
                {"label": "Contract labor", "value": "40000.00", "page": 1},
                {"label": "Rent", "value": "24000.00", "page": 1},
            ],
        }
    ],
    "confidence": 0.88,
    "reasoning": "Annual P&L.",
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
    monkeypatch.setattr(pnl_module, "complete", mock)
    return mock


def test_parse_full_shape_with_types() -> None:
    result = _parse_pnl_json(FULL_JSON)
    assert result is not None
    assert result.status == ExtractionStatus.SUCCEEDED
    d = result.data
    assert d.business_name.value == "Doe Consulting LLC"
    assert d.period_start.value == date(2024, 1, 1)
    assert d.total_revenue.value == Decimal("210000.00")  # "$210,000.00"
    assert d.net_profit.value == Decimal("96500.00")  # the key figure
    # The individual expense lines are preserved in the catch-all.
    labels = [f.label for s in d.additional_sections for f in s.fields]
    assert "Contract labor" in labels and "Rent" in labels


def test_source_location_present() -> None:
    d = _parse_pnl_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.net_profit.source is not None and d.net_profit.source.snippet == "Net Income 96,500.00"


def test_missing_net_profit_is_null_not_computed() -> None:
    """If net profit isn't printed, it stays null — the extractor doesn't compute it."""
    payload = {
        "typed_core": {"total_revenue": _core("210000"), "total_expenses": _core("113500")},
        "confidence": 0.7,
    }
    result = _parse_pnl_json(json.dumps(payload))
    assert result is not None
    assert result.data.net_profit.value is None
    assert result.status == ExtractionStatus.SUCCEEDED


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"net_profit": _core(None), "total_revenue": _core(None)}}
    result = _parse_pnl_json(json.dumps(payload))
    assert result is not None
    assert result.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_pnl_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_profit_and_loss(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED
    assert result.data.net_profit.value == Decimal("96500.00")


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_profit_and_loss(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


async def test_does_not_log_values(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    with structlog.testing.capture_logs() as logs:
        await extract_profit_and_loss(PDF_BYTES, "application/pdf")
    blob = " ".join(repr(e) for e in logs)
    assert "Doe Consulting" not in blob and "96500" not in blob and "210000" not in blob
    done = [e for e in logs if e["event"] == "pnl_extraction_done"]
    assert len(done) == 1 and done[0]["core_fields_present"] == 6


def test_failed_factory() -> None:
    result = ProfitAndLossExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == ProfitAndLossExtraction()

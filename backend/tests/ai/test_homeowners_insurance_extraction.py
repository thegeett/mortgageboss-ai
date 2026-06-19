"""Tests for homeowner's insurance extraction (LP-62) — the AI wrapper is MOCKED.

Focus: the typed core is coerced (carrier/policy/address→str, coverage/premium→
Decimal, effective/expiration→date) with source; honest nulls; graceful failure.

No real insurance binder samples were available — these verify the mechanism/shape,
not accuracy against real binders (validated as real documents flow through; field
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
from app.ai.extraction import homeowners_insurance as hoi_module
from app.ai.extraction.homeowners_insurance import (
    HomeownersInsuranceExtraction,
    HomeownersInsuranceExtractionResult,
    _parse_homeowners_insurance_json,
    extract_homeowners_insurance,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy insurance binder"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "carrier_name": _core("State Farm"),
        "policy_number": _core("HO-123456"),
        "property_address": _core("123 Main St"),
        "coverage_amount": _core("$450,000.00", snippet="Coverage A 450,000"),
        "annual_premium": _core("1850.00", snippet="Annual Premium 1,850.00"),
        "effective_date": _core("2024-10-01"),
        "expiration_date": _core("2025-10-01"),
    },
    "additional_sections": [
        {"section": "Mortgagee Clause", "fields": [{"label": "Loss payee", "value": "ABC Lender"}]}
    ],
    "confidence": 0.9,
    "reasoning": "Declarations page.",
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
    monkeypatch.setattr(hoi_module, "complete", mock)
    return mock


def test_parse_full_shape_with_types() -> None:
    result = _parse_homeowners_insurance_json(FULL_JSON)
    assert result is not None
    assert result.status == ExtractionStatus.SUCCEEDED
    d = result.data
    assert d.carrier_name.value == "State Farm"
    assert d.coverage_amount.value == Decimal("450000.00")  # "$450,000.00" coerced
    assert d.annual_premium.value == Decimal("1850.00")  # housing expense
    assert d.effective_date.value == date(2024, 10, 1)
    assert d.expiration_date.value == date(2025, 10, 1)


def test_source_location_present() -> None:
    d = _parse_homeowners_insurance_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.coverage_amount.source is not None
    assert d.coverage_amount.source.snippet == "Coverage A 450,000"


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"carrier_name": _core(None), "annual_premium": _core(None)}}
    result = _parse_homeowners_insurance_json(json.dumps(payload))
    assert result is not None
    assert result.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_homeowners_insurance_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_homeowners_insurance(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED
    assert result.data.annual_premium.value == Decimal("1850.00")


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_homeowners_insurance(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


async def test_does_not_log_values(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    with structlog.testing.capture_logs() as logs:
        await extract_homeowners_insurance(PDF_BYTES, "application/pdf")
    blob = " ".join(repr(e) for e in logs)
    assert "State Farm" not in blob and "450000" not in blob and "HO-123456" not in blob
    done = [e for e in logs if e["event"] == "homeowners_insurance_extraction_done"]
    assert len(done) == 1 and done[0]["core_fields_present"] == 7


def test_failed_factory() -> None:
    result = HomeownersInsuranceExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == HomeownersInsuranceExtraction()

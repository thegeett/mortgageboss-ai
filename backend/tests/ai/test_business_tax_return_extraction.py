"""Tests for business tax return extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.business_tax_return import (
    BusinessTaxReturnExtraction,
    BusinessTaxReturnExtractionResult,
    _parse_business_tax_return_json,
    extract_business_tax_return,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy business_tax_return"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "return_form_type": _core("SAMPLE"),
        "tax_period_start": _core("2024-01-15"),
        "tax_period_end": _core("2024-01-15"),
        "business_legal_name": _core("SAMPLE"),
        "ein": _core("SAMPLE"),
        "business_address": _core("SAMPLE"),
        "entity_type": _core("SAMPLE"),
        "accounting_method": _core("SAMPLE"),
        "initial_final_or_amended_return": _core("SAMPLE"),
        "date_business_started_or_incorporated": _core("2024-01-15"),
        "principal_business_activity": _core("SAMPLE"),
        "naics_or_activity_code": _core("SAMPLE"),
        "gross_receipts_or_sales": _core("1234.56"),
        "gross_profit": _core("1234.56"),
        "ordinary_or_taxable_income": _core("1234.56"),
        "depreciation_and_amortization": _core("1234.56"),
        "depletion": _core("1234.56"),
        "guaranteed_payments": _core("1234.56"),
        "distributions_or_dividends": _core("1234.56"),
        "retained_earnings_or_capital": _core("1234.56"),
        "authorized_signer_name_title": _core("SAMPLE"),
        "signature_date": _core("2024-01-15"),
        "paid_preparer_name": _core("SAMPLE"),
    },
    "additional_sections": [{"section": "Other", "fields": [{"label": "Note", "value": "x"}]}],
    "owner_partner_shareholder_records": [
        {
            "owner_name": "SAMPLE",
            "ownership_percentage": "SAMPLE",
            "distribution_or_k1_share": "1234.56",
            "page": 1,
            "snippet": "s",
        }
    ],
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
    d = _parse_business_tax_return_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.return_form_type.value == "SAMPLE"
    assert d.return_form_type.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"return_form_type": _core(None)}}
    parsed = _parse_business_tax_return_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_business_tax_return_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_business_tax_return(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_business_tax_return(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = BusinessTaxReturnExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == BusinessTaxReturnExtraction()

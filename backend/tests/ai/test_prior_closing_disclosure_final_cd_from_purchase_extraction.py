"""Tests for prior closing disclosure final cd from purchase extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.prior_closing_disclosure_final_cd_from_purchase import (
    PriorClosingDisclosureFinalCdFromPurchaseExtraction,
    PriorClosingDisclosureFinalCdFromPurchaseExtractionResult,
    _parse_prior_closing_disclosure_final_cd_from_purchase_json,
    extract_prior_closing_disclosure_final_cd_from_purchase,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy prior_closing_disclosure_final_cd_from_purchase"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "borrower_name": _core("SAMPLE"),
        "borrower_name_2": _core("SAMPLE"),
        "borrower_names_raw": _core("SAMPLE"),
        "seller_name": _core("SAMPLE"),
        "property_address": _core("SAMPLE"),
        "lender_name": _core("SAMPLE"),
        "settlement_agent_name": _core("SAMPLE"),
        "settlement_file_number": _core("SAMPLE"),
        "loan_number": _core("SAMPLE"),
        "closing_date": _core("2024-01-15"),
        "disbursement_date": _core("2024-01-15"),
        "cd_delivery_or_received_date": _core("2024-01-15"),
        "final_or_corrected_indicator": _core("SAMPLE"),
        "loan_amount": _core("1234.56"),
        "sale_price": _core("1234.56"),
        "loan_purpose": _core("SAMPLE"),
        "interest_rate": _core("SAMPLE"),
        "apr": _core("SAMPLE"),
        "monthly_principal_and_interest": _core("1234.56"),
        "total_closing_costs": _core("1234.56"),
        "cash_to_close": _core("1234.56"),
        "lender_credits": _core("1234.56"),
        "seller_credits": _core("1234.56"),
        "deposit_or_earnest_money": _core("1234.56"),
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
    d = _parse_prior_closing_disclosure_final_cd_from_purchase_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.borrower_name.value == "SAMPLE"
    assert d.borrower_name.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"borrower_name": _core(None)}}
    parsed = _parse_prior_closing_disclosure_final_cd_from_purchase_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_prior_closing_disclosure_final_cd_from_purchase_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_prior_closing_disclosure_final_cd_from_purchase(
        PDF_BYTES, "application/pdf"
    )
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_prior_closing_disclosure_final_cd_from_purchase(
        PDF_BYTES, "application/pdf"
    )
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = PriorClosingDisclosureFinalCdFromPurchaseExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == PriorClosingDisclosureFinalCdFromPurchaseExtraction()

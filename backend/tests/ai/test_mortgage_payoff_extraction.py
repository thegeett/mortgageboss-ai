"""Tests for mortgage payoff extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.mortgage_payoff import (
    MortgagePayoffExtraction,
    MortgagePayoffExtractionResult,
    _parse_mortgage_payoff_json,
    extract_mortgage_payoff,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy mortgage_payoff"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "issuer_name": _core("SAMPLE"),
        "creditor_or_servicer_name": _core("SAMPLE"),
        "servicer_phone": _core("SAMPLE"),
        "borrower_names_raw": _core("SAMPLE"),
        "borrower_name": _core("SAMPLE"),
        "borrower_name_2": _core("SAMPLE"),
        "property_address": _core("SAMPLE"),
        "loan_number_masked": _core("SAMPLE"),
        "account_case_reference_number": _core("SAMPLE"),
        "payoff_quote_date": _core("2024-01-15"),
        "payoff_good_through_date": _core("2024-01-15"),
        "unpaid_principal_balance": _core("1234.56"),
        "interest_through_good_through_date": _core("1234.56"),
        "per_diem_interest": _core("1234.56"),
        "escrow_balance_orcredit": _core("1234.56"),
        "prepayment_penalty": _core("1234.56"),
        "total_payoff_amount": _core("1234.56"),
        "payoff_after_good_through_formula": _core("SAMPLE"),
        "payment_method_allowed": _core("SAMPLE"),
        "wire_or_remittance_instructions": _core("SAMPLE"),
        "certified_funds_requirement": _core("SAMPLE"),
        "lien_release_timing": _core("SAMPLE"),
        "quote_status": _core("SAMPLE"),
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
    d = _parse_mortgage_payoff_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.issuer_name.value == "SAMPLE"
    assert d.issuer_name.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"issuer_name": _core(None)}}
    parsed = _parse_mortgage_payoff_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_mortgage_payoff_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_mortgage_payoff(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_mortgage_payoff(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = MortgagePayoffExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == MortgagePayoffExtraction()

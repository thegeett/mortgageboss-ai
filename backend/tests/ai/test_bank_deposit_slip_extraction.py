"""Tests for bank deposit slip extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.bank_deposit_slip import (
    BankDepositSlipExtraction,
    BankDepositSlipExtractionResult,
    _parse_bank_deposit_slip_json,
    extract_bank_deposit_slip,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy bank_deposit_slip"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "financial_institution_name": _core("SAMPLE"),
        "branch_identifier": _core("SAMPLE"),
        "account_holder_name": _core("SAMPLE"),
        "account_number_masked": _core("SAMPLE"),
        "account_type": _core("SAMPLE"),
        "deposit_date": _core("2024-01-15"),
        "deposit_channel": _core("SAMPLE"),
        "transaction_or_teller_number": _core("SAMPLE"),
        "deposit_total": _core("1234.56"),
        "cash_amount": _core("1234.56"),
        "checks_total": _core("1234.56"),
        "less_cash_received": _core("1234.56"),
        "currency": _core("SAMPLE"),
        "funds_availability_date": _core("2024-01-15"),
        "teller_validation_or_stamp": _core("SAMPLE"),
        "deposit_time": _core("SAMPLE"),
        "document_issue_date": _core("2024-01-15"),
        "loan_number": _core("SAMPLE"),
    },
    "additional_sections": [{"section": "Other", "fields": [{"label": "Note", "value": "x"}]}],
    "check_items": [
        {
            "payer_or_drawer": "SAMPLE",
            "amount": "1234.56",
            "check_number": "SAMPLE",
            "source": "SAMPLE",
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
    d = _parse_bank_deposit_slip_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.financial_institution_name.value == "SAMPLE"
    assert d.financial_institution_name.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"financial_institution_name": _core(None)}}
    parsed = _parse_bank_deposit_slip_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_bank_deposit_slip_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_bank_deposit_slip(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_bank_deposit_slip(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = BankDepositSlipExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == BankDepositSlipExtraction()

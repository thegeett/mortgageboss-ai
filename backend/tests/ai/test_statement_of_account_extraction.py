"""Tests for statement of account extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.statement_of_account import (
    StatementOfAccountExtraction,
    StatementOfAccountExtractionResult,
    _parse_statement_of_account_json,
    extract_statement_of_account,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy statement_of_account"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "issuer_name": _core("SAMPLE"),
        "creditor_or_servicer_name": _core("SAMPLE"),
        "customer_or_debtor_name": _core("SAMPLE"),
        "customer_or_debtor_name_2": _core("SAMPLE"),
        "customer_or_debtor_count": _core(2024),
        "account_number_masked": _core("SAMPLE"),
        "account_type": _core("SAMPLE"),
        "statement_date": _core("2024-01-15"),
        "statement_period_start": _core("2024-01-15"),
        "statement_period_end": _core("2024-01-15"),
        "previous_balance": _core("1234.56"),
        "current_balance": _core("1234.56"),
        "minimum_or_scheduled_payment": _core("1234.56"),
        "payment_due_date": _core("2024-01-15"),
        "past_due_amount": _core("1234.56"),
        "days_past_due": _core(2024),
        "delinquency_or_collection_stage": _core("SAMPLE"),
        "current_account_status": _core("SAMPLE"),
        "credit_limit_or_original_amount": _core("1234.56"),
        "payoff_or_settlement_amount": _core("1234.56"),
        "payoff_good_through_date": _core("2024-01-15"),
        "property_address": _core("SAMPLE"),
        "loan_number": _core("SAMPLE"),
    },
    "additional_sections": [{"section": "Other", "fields": [{"label": "Note", "value": "x"}]}],
    "transactions_or_activity": [
        {
            "date": "2024-01-15",
            "description": "SAMPLE",
            "amount": "1234.56",
            "type": "SAMPLE",
            "running_balance": "1234.56",
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
    d = _parse_statement_of_account_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.issuer_name.value == "SAMPLE"
    assert d.issuer_name.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"issuer_name": _core(None)}}
    parsed = _parse_statement_of_account_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_statement_of_account_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_statement_of_account(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_statement_of_account(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = StatementOfAccountExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == StatementOfAccountExtraction()

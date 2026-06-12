"""Tests for bank statement extraction (LP-39c) — the AI wrapper is MOCKED.

The hardest type: typed core + a TYPED transactions list (ADR-061) + grouped
catch-all. Focus: transactions captured as typed rows (date/amount/...) with source
and **no hallucination**; nothing dropped; honest nulls; a **truncated/malformed**
long list → graceful ``.failed()`` (no crash); and the **account number is never
logged**.
"""

import base64
import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import structlog
from app.ai.client import AIClientError
from app.ai.extraction import bank_statement as bs_module
from app.ai.extraction.bank_statement import (
    BankStatementExtraction,
    BankStatementExtractionResult,
    _parse_bank_statement_json,
    extract_bank_statement,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy bank statement bytes"
PNG_BYTES = b"\x89PNG\r\n\x1a\n dummy"
ACCT = "****1234"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


def _txn(d: str, desc: str, amount: str, ttype: str, bal: str | None = None) -> dict:
    return {
        "date": d,
        "description": desc,
        "amount": amount,
        "transaction_type": ttype,
        "running_balance": bal,
        "page": 1,
        "snippet": f"{d} {desc} {amount}",
    }


FULL_PAYLOAD = {
    "typed_core": {
        "bank_name": _core("First Bank", snippet="First Bank"),
        "account_holder_name": _core("Jane Doe", snippet="Jane Doe"),
        "account_number_masked": _core(ACCT, snippet=f"Acct {ACCT}"),
        "account_type": _core("checking", snippet="Checking"),
        "statement_period_end": _core("2024-06-30", snippet="Through 06/30/2024"),
        "beginning_balance": _core("3170.18", snippet="Beginning 3,170.18"),
        "ending_balance": _core("$5,230.18", snippet="Ending 5,230.18"),
        "total_deposits": _core("2100.00", snippet="Deposits 2,100.00"),
        "total_withdrawals": _core("40.00", snippet="Withdrawals 40.00"),
    },
    "transactions": [
        _txn("2024-06-03", "Payroll ACME", "2100.00", "deposit", "5230.18"),
        _txn("2024-06-05", "ATM withdrawal", "40.00", "withdrawal", "5190.18"),
        _txn("2024-06-10", "Interest", "0.42", "interest"),
    ],
    "additional_sections": [
        {"section": "Messages", "fields": [{"label": "Notice", "value": "Go paperless"}]},
    ],
    "confidence": 0.9,
    "reasoning": "Single-page checking statement.",
}
FULL_JSON = json.dumps(FULL_PAYLOAD)


def _mock_complete(
    monkeypatch: pytest.MonkeyPatch, *, text: str | None = None, exc: Exception | None = None
) -> AsyncMock:
    if exc is not None:
        mock = AsyncMock(side_effect=exc)
    else:
        mock = AsyncMock(
            return_value=SimpleNamespace(text=text, input_tokens=400, output_tokens=300, model="m")
        )
    monkeypatch.setattr(bs_module, "complete", mock)
    return mock


# --------------------------------------------------------------------------- #
# Parser: typed core + transactions list + catch-all
# --------------------------------------------------------------------------- #


def test_parse_full_shape_with_transactions() -> None:
    result = _parse_bank_statement_json(FULL_JSON)
    assert result is not None
    assert result.status == ExtractionStatus.SUCCEEDED
    d = result.data
    assert d.bank_name.value == "First Bank"
    assert d.ending_balance.value == Decimal("5230.18")  # "$5,230.18" coerced
    assert d.account_type.value == "checking"
    # Transactions — typed rows.
    assert len(d.transactions) == 3
    t0 = d.transactions[0]
    assert t0.date == date(2024, 6, 3)
    assert t0.amount == Decimal("2100.00")
    assert t0.transaction_type == "deposit"
    assert t0.running_balance == Decimal("5230.18")
    # Catch-all preserved.
    assert [s.section for s in d.additional_sections] == ["Messages"]


def test_source_location_on_core_and_transactions() -> None:
    d = _parse_bank_statement_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.ending_balance.source is not None and d.ending_balance.source.page == 1
    assert d.transactions[0].source is not None
    assert d.transactions[0].source.snippet == "2024-06-03 Payroll ACME 2100.00"


def test_transactions_no_hallucination_and_no_drop() -> None:
    # Only the rows present are kept; a junk/empty row is dropped, a partial row kept.
    payload = {
        "typed_core": {"ending_balance": _core("100")},
        "transactions": [
            _txn("2024-06-03", "Payroll", "2100.00", "deposit"),
            {"junk": "no fields"},  # dropped (fully empty)
            {"description": "Unreadable amount", "amount": "???", "page": 2, "snippet": "??"},
        ],
        "confidence": 0.8,
    }
    d = _parse_bank_statement_json(json.dumps(payload)).data  # type: ignore[union-attr]
    assert len(d.transactions) == 2  # junk dropped; the 2 real rows kept
    # The unreadable-amount row is kept (description present) with amount None.
    partial = d.transactions[1]
    assert partial.description == "Unreadable amount"
    assert partial.amount is None  # bad value → None, row not fabricated


def test_honest_nulls_absent_core_fields() -> None:
    payload = {"typed_core": {"ending_balance": _core("100")}, "transactions": []}
    result = _parse_bank_statement_json(json.dumps(payload))
    assert result is not None
    assert result.data.ending_balance.value == Decimal("100")
    assert result.data.bank_name.value is None
    assert result.data.account_number_masked.value is None


def test_transactions_only_is_succeeded() -> None:
    # No typed-core fields but transactions present → still content (not FAILED).
    payload = {"transactions": [_txn("2024-06-03", "Payroll", "2100.00", "deposit")]}
    result = _parse_bank_statement_json(json.dumps(payload))
    assert result is not None
    assert result.status == ExtractionStatus.SUCCEEDED


@pytest.mark.parametrize("raw", ["not json", "", "[1,2,3]"])
def test_unparseable_returns_none(raw: str) -> None:
    assert _parse_bank_statement_json(raw) is None


def test_truncated_json_returns_none() -> None:
    # A long transaction list cut off mid-array (model hit the token cap).
    truncated = (
        '{"typed_core": {"ending_balance": {"value": "100"}}, "transactions": ['
        '{"date": "2024-06-03", "description": "Payroll", "amount": "2100.00",'
    )  # no closing — invalid JSON
    assert _parse_bank_statement_json(truncated) is None


def test_clamps_confidence() -> None:
    payload = {"typed_core": {"ending_balance": _core("100")}, "confidence": 1.9}
    result = _parse_bank_statement_json(json.dumps(payload))
    assert result is not None
    assert result.confidence == 1.0


# --------------------------------------------------------------------------- #
# extract_bank_statement
# --------------------------------------------------------------------------- #


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_bank_statement(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED
    assert len(result.data.transactions) == 3
    block = mock.await_args.kwargs["messages"][0]["content"][0]
    assert block["type"] == "document"
    assert base64.standard_b64decode(block["source"]["data"]) == PDF_BYTES


async def test_extract_truncated_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text='{"typed_core": {"ending_balance": {"value": "1')  # truncated
    result = await extract_bank_statement(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == BankStatementExtraction()


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_bank_statement(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


async def test_extract_empty_skips_api(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_bank_statement(b"", "application/pdf")
    assert result.status == ExtractionStatus.FAILED
    assert mock.call_count == 0


@pytest.mark.parametrize("media_type", ["text/plain", "image/gif", ""])
async def test_extract_unsupported_skips_api(
    monkeypatch: pytest.MonkeyPatch, media_type: str
) -> None:
    mock = _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_bank_statement(PDF_BYTES, media_type)
    assert result.status == ExtractionStatus.FAILED
    assert mock.call_count == 0


# --------------------------------------------------------------------------- #
# PRIVACY — no bytes/base64/values logged; SPECIFICALLY no account number
# --------------------------------------------------------------------------- #


async def test_does_not_log_values_or_account_number(monkeypatch: pytest.MonkeyPatch) -> None:
    pii_bytes = b"%PDF First Bank ****1234 Payroll 2100"
    pii_b64 = base64.standard_b64encode(pii_bytes).decode("utf-8")
    _mock_complete(monkeypatch, text=FULL_JSON)

    with structlog.testing.capture_logs() as logs:
        result = await extract_bank_statement(pii_bytes, "application/pdf")

    blob = " ".join(repr(e) for e in logs)
    assert ACCT not in blob  # the account number must never be logged
    assert pii_b64 not in blob
    assert "First Bank" not in blob  # extracted value
    assert "Payroll ACME" not in blob  # a transaction description
    done = [e for e in logs if e["event"] == "bank_statement_extraction_done"]
    assert len(done) == 1
    assert done[0]["transaction_count"] == 3
    assert done[0]["core_fields_present"] == 9
    # The raw account number is still available to the caller (tenant-scoped JSON).
    assert result.data.account_number_masked.value == ACCT


def test_failed_factory() -> None:
    result = BankStatementExtractionResult.failed("because reasons")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == BankStatementExtraction()
    assert result.data.transactions == []

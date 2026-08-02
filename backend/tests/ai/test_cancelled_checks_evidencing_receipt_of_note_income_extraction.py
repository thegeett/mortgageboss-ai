"""Tests for cancelled checks evidencing receipt of note income extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.cancelled_checks_evidencing_receipt_of_note_income import (
    CancelledChecksEvidencingReceiptOfNoteIncomeExtraction,
    CancelledChecksEvidencingReceiptOfNoteIncomeExtractionResult,
    _parse_cancelled_checks_evidencing_receipt_of_note_income_json,
    extract_cancelled_checks_evidencing_receipt_of_note_income,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy cancelled_checks_evidencing_receipt_of_note_income"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "drawer_or_maker_name": _core("SAMPLE"),
        "drawer_bank_name": _core("SAMPLE"),
        "drawer_account_last4": _core("SAMPLE"),
        "payee_or_borrower_name": _core("SAMPLE"),
        "check_number": _core("SAMPLE"),
        "check_date": _core("2024-01-15"),
        "check_amount_numeric": _core("1234.56"),
        "check_amount_written": _core("SAMPLE"),
        "memo_or_note_reference": _core("SAMPLE"),
        "front_image_present": _core("SAMPLE"),
        "back_image_present": _core("SAMPLE"),
        "payee_endorsement": _core("SAMPLE"),
        "deposit_account_last4": _core("SAMPLE"),
        "bank_paid_or_cleared_stamp": _core("SAMPLE"),
        "cleared_date": _core("2024-01-15"),
        "deposit_or_posting_date": _core("2024-01-15"),
        "return_stop_or_void_indicator": _core("SAMPLE"),
        "statement_or_transaction_reference": _core("SAMPLE"),
        "related_note_date": _core("2024-01-15"),
        "related_note_payment_amount": _core("1234.56"),
        "related_note_maturity_date": _core("2024-01-15"),
        "payment_period_start": _core("2024-01-15"),
        "payment_period_end": _core("2024-01-15"),
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
    d = _parse_cancelled_checks_evidencing_receipt_of_note_income_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.drawer_or_maker_name.value == "SAMPLE"
    assert d.drawer_or_maker_name.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"drawer_or_maker_name": _core(None)}}
    parsed = _parse_cancelled_checks_evidencing_receipt_of_note_income_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_cancelled_checks_evidencing_receipt_of_note_income_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_cancelled_checks_evidencing_receipt_of_note_income(
        PDF_BYTES, "application/pdf"
    )
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_cancelled_checks_evidencing_receipt_of_note_income(
        PDF_BYTES, "application/pdf"
    )
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = CancelledChecksEvidencingReceiptOfNoteIncomeExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == CancelledChecksEvidencingReceiptOfNoteIncomeExtraction()

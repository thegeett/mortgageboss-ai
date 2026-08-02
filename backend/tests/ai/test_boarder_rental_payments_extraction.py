"""Tests for boarder rental payments extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.boarder_rental_payments import (
    BoarderRentalPaymentsExtraction,
    BoarderRentalPaymentsExtractionResult,
    _parse_boarder_rental_payments_json,
    extract_boarder_rental_payments,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy boarder_rental_payments"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "issuer_name": _core("SAMPLE"),
        "boarder_payer_name": _core("SAMPLE"),
        "borrower_recipient_name": _core("SAMPLE"),
        "relationship_to_borrower": _core("SAMPLE"),
        "property_address": _core("SAMPLE"),
        "agreement_start_date": _core("2024-01-15"),
        "agreement_end_date": _core("2024-01-15"),
        "written_agreement_indicator": _core("SAMPLE"),
        "monthly_or_periodic_payment_amount": _core("1234.56"),
        "payment_frequency": _core("SAMPLE"),
        "payment_due_day_or_schedule": _core("SAMPLE"),
        "total_payments_received": _core("1234.56"),
        "current_arrears": _core("1234.56"),
        "returned_payment_count": _core(2024),
        "recipient_account_last4": _core("SAMPLE"),
        "loan_number": _core("SAMPLE"),
        "account_case_reference_number": _core("SAMPLE"),
        "document_issue_date": _core("2024-01-15"),
    },
    "additional_sections": [{"section": "Other", "fields": [{"label": "Note", "value": "x"}]}],
    "payment_history": [
        {
            "date": "2024-01-15",
            "amount": "1234.56",
            "method": "SAMPLE",
            "status": "SAMPLE",
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
    d = _parse_boarder_rental_payments_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.issuer_name.value == "SAMPLE"
    assert d.issuer_name.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"issuer_name": _core(None)}}
    parsed = _parse_boarder_rental_payments_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_boarder_rental_payments_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_boarder_rental_payments(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_boarder_rental_payments(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = BoarderRentalPaymentsExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == BoarderRentalPaymentsExtraction()

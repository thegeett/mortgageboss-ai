"""Tests for evidence of payment extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.evidence_of_payment import (
    EvidenceOfPaymentExtraction,
    EvidenceOfPaymentExtractionResult,
    _parse_evidence_of_payment_json,
    extract_evidence_of_payment,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy evidence_of_payment"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "issuer_name": _core("SAMPLE"),
        "payer_name": _core("SAMPLE"),
        "payee_or_creditor_name": _core("SAMPLE"),
        "obligation_type": _core("SAMPLE"),
        "account_or_case_number_masked": _core("SAMPLE"),
        "property_address_if_applicable": _core("SAMPLE"),
        "payment_amount": _core("1234.56"),
        "payment_date": _core("2024-01-15"),
        "posting_or_cleared_date": _core("2024-01-15"),
        "payment_method": _core("SAMPLE"),
        "check_reference_or_trace_number": _core("SAMPLE"),
        "source_institution": _core("SAMPLE"),
        "source_account_last4": _core("SAMPLE"),
        "payment_description_or_memo": _core("SAMPLE"),
        "cleared_or_completed_indicator": _core("SAMPLE"),
        "balance_before_payment": _core("1234.56"),
        "balance_after_payment": _core("1234.56"),
        "paid_in_full_indicator": _core("SAMPLE"),
        "account_status_after_payment": _core("SAMPLE"),
        "billing_or_due_period": _core("SAMPLE"),
        "loan_number": _core("SAMPLE"),
    },
    "additional_sections": [{"section": "Other", "fields": [{"label": "Note", "value": "x"}]}],
    "recurring_payment_history": [
        {
            "date": "2024-01-15",
            "amount": "1234.56",
            "status": "SAMPLE",
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
    d = _parse_evidence_of_payment_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.issuer_name.value == "SAMPLE"
    assert d.issuer_name.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"issuer_name": _core(None)}}
    parsed = _parse_evidence_of_payment_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_evidence_of_payment_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_evidence_of_payment(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_evidence_of_payment(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = EvidenceOfPaymentExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == EvidenceOfPaymentExtraction()

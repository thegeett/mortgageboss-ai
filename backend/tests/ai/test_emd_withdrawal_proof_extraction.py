"""Tests for emd withdrawal proof extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.emd_withdrawal_proof import (
    EmdWithdrawalProofExtraction,
    EmdWithdrawalProofExtractionResult,
    _parse_emd_withdrawal_proof_json,
    extract_emd_withdrawal_proof,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy emd_withdrawal_proof"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "financial_institution_name": _core("SAMPLE"),
        "account_owner_names": _core("SAMPLE"),
        "account_number_masked": _core("SAMPLE"),
        "statement_period_start": _core("2024-01-15"),
        "statement_period_end": _core("2024-01-15"),
        "transaction_date": _core("2024-01-15"),
        "posting_date": _core("SAMPLE"),
        "withdrawal_amount": _core("1234.56"),
        "transaction_type": _core("SAMPLE"),
        "payee_or_recipient": _core("SAMPLE"),
        "check_number": _core("SAMPLE"),
        "wire_ach_trace_number": _core("SAMPLE"),
        "transaction_description": _core("SAMPLE"),
        "balance_after_transaction": _core("1234.56"),
        "check_cleared_or_transaction_completed": _core("SAMPLE"),
        "related_emd_receipt_reference": _core("SAMPLE"),
        "related_purchase_contract_amount": _core("1234.56"),
        "property_address": _core("SAMPLE"),
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
    d = _parse_emd_withdrawal_proof_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.financial_institution_name.value == "SAMPLE"
    assert d.financial_institution_name.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"financial_institution_name": _core(None)}}
    parsed = _parse_emd_withdrawal_proof_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_emd_withdrawal_proof_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_emd_withdrawal_proof(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_emd_withdrawal_proof(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = EmdWithdrawalProofExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == EmdWithdrawalProofExtraction()

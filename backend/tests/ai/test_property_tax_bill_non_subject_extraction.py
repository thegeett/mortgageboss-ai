"""Tests for property tax bill non subject extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.property_tax_bill_non_subject import (
    PropertyTaxBillNonSubjectExtraction,
    PropertyTaxBillNonSubjectExtractionResult,
    _parse_property_tax_bill_non_subject_json,
    extract_property_tax_bill_non_subject,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy property_tax_bill_non_subject"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "document_title": _core("SAMPLE"),
        "taxing_authority": _core("SAMPLE"),
        "property_address": _core("SAMPLE"),
        "parcel_or_apn": _core("SAMPLE"),
        "taxpayer_name": _core("SAMPLE"),
        "taxpayer_name_2": _core("SAMPLE"),
        "taxpayer_count": _core(2024),
        "tax_bill_or_account_number": _core("SAMPLE"),
        "tax_year": _core(2024),
        "total_assessed_value": _core("1234.56"),
        "taxable_value": _core("1234.56"),
        "base_tax_amount": _core("1234.56"),
        "total_tax_due": _core("1234.56"),
        "penalties_and_interest": _core("1234.56"),
        "current_balance": _core("1234.56"),
        "delinquent_or_lien_status": _core("SAMPLE"),
        "legal_description": _core("SAMPLE"),
        "subject_property_indicator": _core("SAMPLE"),
        "loan_number": _core("SAMPLE"),
    },
    "additional_sections": [{"section": "Other", "fields": [{"label": "Note", "value": "x"}]}],
    "installments_and_due_dates": [
        {
            "installment_label": "SAMPLE",
            "amount": "1234.56",
            "due_date": "2024-01-15",
            "paid_indicator": "SAMPLE",
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
    d = _parse_property_tax_bill_non_subject_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.document_title.value == "SAMPLE"
    assert d.document_title.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"document_title": _core(None)}}
    parsed = _parse_property_tax_bill_non_subject_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_property_tax_bill_non_subject_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_property_tax_bill_non_subject(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_property_tax_bill_non_subject(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = PropertyTaxBillNonSubjectExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == PropertyTaxBillNonSubjectExtraction()

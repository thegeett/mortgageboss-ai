"""Tests for form 1065 partnership tax transcripts extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.form_1065_partnership_tax_transcripts import (
    Form1065PartnershipTaxTranscriptsExtraction,
    Form1065PartnershipTaxTranscriptsExtractionResult,
    _parse_form_1065_partnership_tax_transcripts_json,
    extract_form_1065_partnership_tax_transcripts,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy form_1065_partnership_tax_transcripts"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "issuer_name": _core("SAMPLE"),
        "transcript_type": _core("SAMPLE"),
        "tax_form_number": _core("SAMPLE"),
        "tax_period_ending": _core("2024-01-15"),
        "request_or_processing_date": _core("2024-01-15"),
        "partnership_legal_name": _core("SAMPLE"),
        "ein_masked": _core("SAMPLE"),
        "business_address": _core("SAMPLE"),
        "date_business_started": _core("2024-01-15"),
        "accounting_method": _core("SAMPLE"),
        "number_of_schedules_k1": _core(2024),
        "gross_receipts_or_sales": _core("1234.56"),
        "cost_of_goods_sold": _core("1234.56"),
        "gross_profit": _core("1234.56"),
        "total_income": _core("1234.56"),
        "guaranteed_payments_to_partners": _core("1234.56"),
        "ordinary_business_income_or_loss": _core("1234.56"),
    },
    "additional_sections": [{"section": "Other", "fields": [{"label": "Note", "value": "x"}]}],
    "schedule_k_items": [
        {"line_label": "SAMPLE", "amount": "1234.56", "source": "SAMPLE", "page": 1, "snippet": "s"}
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
    d = _parse_form_1065_partnership_tax_transcripts_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.issuer_name.value == "SAMPLE"
    assert d.issuer_name.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"issuer_name": _core(None)}}
    parsed = _parse_form_1065_partnership_tax_transcripts_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_form_1065_partnership_tax_transcripts_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_form_1065_partnership_tax_transcripts(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_form_1065_partnership_tax_transcripts(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = Form1065PartnershipTaxTranscriptsExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == Form1065PartnershipTaxTranscriptsExtraction()

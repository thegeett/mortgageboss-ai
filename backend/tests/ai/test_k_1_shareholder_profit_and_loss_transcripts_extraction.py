"""Tests for k 1 shareholder profit and loss transcripts extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.k_1_shareholder_profit_and_loss_transcripts import (
    K1ShareholderProfitAndLossTranscriptsExtraction,
    K1ShareholderProfitAndLossTranscriptsExtractionResult,
    _parse_k_1_shareholder_profit_and_loss_transcripts_json,
    extract_k_1_shareholder_profit_and_loss_transcripts,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy k_1_shareholder_profit_and_loss_transcripts"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "transcript_type": _core("SAMPLE"),
        "transcript_request_or_run_date": _core("2024-01-15"),
        "tax_year": _core("SAMPLE"),
        "source_form": _core("SAMPLE"),
        "entity_name": _core("SAMPLE"),
        "entity_ein_masked": _core("SAMPLE"),
        "shareholder_or_partner_name": _core("SAMPLE"),
        "shareholder_or_partner_tin_masked": _core("SAMPLE"),
        "ownership_percentage": _core("SAMPLE"),
        "ordinary_business_income_or_loss": _core("1234.56"),
        "rental_real_estate_income_or_loss": _core("1234.56"),
        "other_rental_income_or_loss": _core("1234.56"),
        "guaranteed_payments_or_compensation": _core("1234.56"),
        "distributions_or_withdrawals": _core("1234.56"),
        "interest_dividends_and_gains": _core("SAMPLE"),
    },
    "additional_sections": [{"section": "Other", "fields": [{"label": "Note", "value": "x"}]}],
    "transcript_line_items": [
        {
            "line_code": "SAMPLE",
            "description": "SAMPLE",
            "amount": "1234.56",
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
    d = _parse_k_1_shareholder_profit_and_loss_transcripts_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.transcript_type.value == "SAMPLE"
    assert d.transcript_type.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"transcript_type": _core(None)}}
    parsed = _parse_k_1_shareholder_profit_and_loss_transcripts_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_k_1_shareholder_profit_and_loss_transcripts_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_k_1_shareholder_profit_and_loss_transcripts(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_k_1_shareholder_profit_and_loss_transcripts(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = K1ShareholderProfitAndLossTranscriptsExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == K1ShareholderProfitAndLossTranscriptsExtraction()

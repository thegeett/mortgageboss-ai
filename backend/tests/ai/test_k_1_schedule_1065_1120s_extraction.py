"""Tests for k 1 schedule 1065 1120s extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.k_1_schedule_1065_1120s import (
    K1Schedule10651120sExtraction,
    K1Schedule10651120sExtractionResult,
    _parse_k_1_schedule_1065_1120s_json,
    extract_k_1_schedule_1065_1120s,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy k_1_schedule_1065_1120s"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "tax_year": _core(2024),
        "source_form": _core("SAMPLE"),
        "final_or_amended_k1": _core("SAMPLE"),
        "entity_name": _core("SAMPLE"),
        "entity_ein": _core("SAMPLE"),
        "entity_address": _core("SAMPLE"),
        "partner_or_shareholder_name": _core("SAMPLE"),
        "partner_or_shareholder_tin": _core("SAMPLE"),
        "partner_or_shareholder_address": _core("SAMPLE"),
        "partner_type_or_shareholder_status": _core("SAMPLE"),
        "profit_loss_capital_or_ownership_percentages": _core("SAMPLE"),
        "current_year_net_income_or_loss": _core("1234.56"),
        "capital_account_ending": _core("1234.56"),
        "withdrawals_and_distributions": _core("1234.56"),
        "guaranteed_payments": _core("1234.56"),
        "distributions": _core("1234.56"),
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
    d = _parse_k_1_schedule_1065_1120s_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.tax_year.value == 2024
    assert d.tax_year.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"tax_year": _core(None)}}
    parsed = _parse_k_1_schedule_1065_1120s_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_k_1_schedule_1065_1120s_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_k_1_schedule_1065_1120s(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_k_1_schedule_1065_1120s(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = K1Schedule10651120sExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == K1Schedule10651120sExtraction()

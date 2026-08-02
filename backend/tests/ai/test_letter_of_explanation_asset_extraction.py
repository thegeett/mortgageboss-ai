"""Tests for letter of explanation asset extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.letter_of_explanation_asset import (
    LetterOfExplanationAssetExtraction,
    LetterOfExplanationAssetExtractionResult,
    _parse_letter_of_explanation_asset_json,
    extract_letter_of_explanation_asset,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy letter_of_explanation_asset"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "borrower_name": _core("SAMPLE"),
        "borrower_name_2": _core("SAMPLE"),
        "borrower_count": _core(2024),
        "letter_date": _core("2024-01-15"),
        "financial_institution_or_custodian": _core("SAMPLE"),
        "account_number_last4": _core("SAMPLE"),
        "asset_type": _core("SAMPLE"),
        "asset_issue_type": _core("SAMPLE"),
        "source_or_origin_of_funds": _core("SAMPLE"),
        "source_party_name_and_relationship": _core("SAMPLE"),
        "borrowed_funds_indicator": _core("SAMPLE"),
        "repayment_obligation_terms": _core("SAMPLE"),
        "current_availability_or_balance": _core("1234.56"),
        "borrower_certification": _core("SAMPLE"),
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
    d = _parse_letter_of_explanation_asset_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.borrower_name.value == "SAMPLE"
    assert d.borrower_name.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"borrower_name": _core(None)}}
    parsed = _parse_letter_of_explanation_asset_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_letter_of_explanation_asset_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_letter_of_explanation_asset(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_letter_of_explanation_asset(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = LetterOfExplanationAssetExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == LetterOfExplanationAssetExtraction()

"""Tests for bankruptcy filing extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.bankruptcy_filing import (
    BankruptcyFilingExtraction,
    BankruptcyFilingExtractionResult,
    _parse_bankruptcy_filing_json,
    extract_bankruptcy_filing,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy bankruptcy_filing"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "debtor_1_legal_name": _core("SAMPLE"),
        "debtor_2_legal_name": _core("SAMPLE"),
        "ssn_or_itin_last4": _core("SAMPLE"),
        "ssn_or_itin_last4_2": _core("SAMPLE"),
        "debtor_address": _core("SAMPLE"),
        "county_of_residence": _core("SAMPLE"),
        "bankruptcy_court_name": _core("SAMPLE"),
        "case_number": _core("SAMPLE"),
        "bankruptcy_chapter": _core("SAMPLE"),
        "amended_filing_indicator": _core("SAMPLE"),
        "filing_date": _core("2024-01-15"),
        "debts_primarily_consumer_or_business": _core("SAMPLE"),
        "filing_basis_and_venue": _core("SAMPLE"),
        "estimated_asset_range": _core("SAMPLE"),
        "estimated_liability_range": _core("SAMPLE"),
        "rental_property_eviction_judgment": _core("SAMPLE"),
        "attorney_name": _core("SAMPLE"),
        "document_issue_date": _core("2024-01-15"),
        "loan_number": _core("SAMPLE"),
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
    d = _parse_bankruptcy_filing_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.debtor_1_legal_name.value == "SAMPLE"
    assert d.debtor_1_legal_name.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"debtor_1_legal_name": _core(None)}}
    parsed = _parse_bankruptcy_filing_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_bankruptcy_filing_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_bankruptcy_filing(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_bankruptcy_filing(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = BankruptcyFilingExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == BankruptcyFilingExtraction()

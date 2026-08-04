"""Tests for title commitment extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.title_commitment import (
    TitleCommitmentExtraction,
    TitleCommitmentExtractionResult,
    _parse_title_commitment_json,
    extract_title_commitment,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy title_commitment"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "title_company_name": _core("SAMPLE"),
        "commitment_number": _core("SAMPLE"),
        "effective_date": _core("2024-01-15"),
        "commitment_date": _core("2024-01-15"),
        "policy_amount": _core("1234.56"),
        "policy_type": _core("SAMPLE"),
        "property_address": _core("SAMPLE"),
        "legal_description": _core("SAMPLE"),
        "legal_description_type": _core("SAMPLE"),
        "parcel_identification_number": _core("SAMPLE"),
        "county": _core("SAMPLE"),
        "vested_owner_name": _core("SAMPLE"),
        "vested_owner_name_2": _core("SAMPLE"),
        "vesting_type": _core("SAMPLE"),
        "vesting_marital_recital": _core("SAMPLE"),
        "proposed_insured_name": _core("SAMPLE"),
        "seller_of_record": _core("SAMPLE"),
        "open_liens_indicator": _core("SAMPLE"),
        "judgments_indicator": _core("SAMPLE"),
        "survey_exception_indicator": _core("SAMPLE"),
        "taxes_status": _core("SAMPLE"),
        "annual_tax_amount": _core("1234.56"),
    },
    "additional_sections": [{"section": "Other", "fields": [{"label": "Note", "value": "x"}]}],
    "schedule_b_items": [
        {
            "schedule": "SAMPLE",
            "item_number": "SAMPLE",
            "item_type": "SAMPLE",
            "description": "SAMPLE",
            "recording_date": "2024-01-15",
            "recording_reference": "SAMPLE",
            "amount": "1234.56",
            "is_satisfied": "SAMPLE",
            "affected_party": "SAMPLE",
            "page": 1,
            "snippet": "s",
        }
    ],
    "chain_of_title": [
        {
            "transfer_date": "2024-01-15",
            "grantor": "SAMPLE",
            "grantee": "SAMPLE",
            "consideration_amount": "1234.56",
            "recording_reference": "SAMPLE",
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
    d = _parse_title_commitment_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.title_company_name.value == "SAMPLE"
    assert d.title_company_name.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"title_company_name": _core(None)}}
    parsed = _parse_title_commitment_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_title_commitment_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_title_commitment(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_title_commitment(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = TitleCommitmentExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == TitleCommitmentExtraction()

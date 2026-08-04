"""Tests for bankruptcy discharge extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.bankruptcy_discharge import (
    BankruptcyDischargeExtraction,
    BankruptcyDischargeExtractionResult,
    _parse_bankruptcy_discharge_json,
    extract_bankruptcy_discharge,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy bankruptcy_discharge"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "debtor_name": _core("SAMPLE"),
        "joint_debtor_name": _core("SAMPLE"),
        "bankruptcy_chapter": _core("SAMPLE"),
        "discharge_granted_indicator": _core("SAMPLE"),
        "discharge_order_date": _core("2024-01-15"),
        "discharge_effective_date": _core("2024-01-15"),
        "case_status_after_discharge": _core("SAMPLE"),
        "bankruptcy_court_name": _core("SAMPLE"),
        "district_or_division": _core("SAMPLE"),
        "case_number": _core("SAMPLE"),
        "case_filing_date": _core("2024-01-15"),
        "exceptions_or_nondischargeable_debts": _core("SAMPLE"),
        "debts_subject_to_discharge_summary": _core("SAMPLE"),
        "prior_discharge_or_revocation_reference": _core("SAMPLE"),
        "judge_name": _core("SAMPLE"),
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
    d = _parse_bankruptcy_discharge_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.debtor_name.value == "SAMPLE"
    assert d.debtor_name.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"debtor_name": _core(None)}}
    parsed = _parse_bankruptcy_discharge_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_bankruptcy_discharge_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_bankruptcy_discharge(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_bankruptcy_discharge(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = BankruptcyDischargeExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == BankruptcyDischargeExtraction()

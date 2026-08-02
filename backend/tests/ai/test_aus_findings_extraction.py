"""Tests for aus findings extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.aus_findings import (
    AusFindingsExtraction,
    AusFindingsExtractionResult,
    _parse_aus_findings_json,
    extract_aus_findings,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy aus_findings"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "aus_engine": _core("SAMPLE"),
        "casefile_or_key_number": _core("SAMPLE"),
        "submission_date": _core("2024-01-15"),
        "submission_number": _core(2024),
        "lender_loan_number": _core("SAMPLE"),
        "recommendation": _core("SAMPLE"),
        "eligibility_status": _core("SAMPLE"),
        "risk_class": _core("SAMPLE"),
        "ineligibility_reasons": _core("SAMPLE"),
        "aus_qualifying_income": _core("1234.56"),
        "aus_total_assets": _core("1234.56"),
        "aus_credit_score": _core(2024),
        "aus_dti_ratio": _core("1234.56"),
        "aus_ltv_ratio": _core("1234.56"),
        "aus_cltv_ratio": _core("1234.56"),
        "aus_loan_amount": _core("1234.56"),
        "aus_property_value": _core("1234.56"),
        "aus_occupancy": _core("SAMPLE"),
        "aus_loan_purpose": _core("SAMPLE"),
        "required_reserve_months": _core("1234.56"),
        "asset_documentation_level": _core("SAMPLE"),
        "income_documentation_level": _core("SAMPLE"),
        "condition_count": _core(2024),
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
    d = _parse_aus_findings_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.aus_engine.value == "SAMPLE"
    assert d.aus_engine.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"aus_engine": _core(None)}}
    parsed = _parse_aus_findings_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_aus_findings_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_aus_findings(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_aus_findings(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = AusFindingsExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == AusFindingsExtraction()

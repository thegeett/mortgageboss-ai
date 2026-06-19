"""Tests for Letter of Explanation extraction (LP-60) — the AI wrapper is MOCKED.

Follows the W-2 test template, but the LOE is **prose-light**: the typed core is
subject + explanation_summary + a single primary referenced employer/date/amount;
ADDITIONAL references go to the catch-all. Focus: the light core is coerced with
source; additional references land in catch-all; honest nulls; graceful failure.

No real LOE sample documents were available — these verify the mechanism/shape,
not accuracy against real letters (validated as real documents flow through;
field set refined with Priya).
"""

import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import structlog
from app.ai.client import AIClientError
from app.ai.extraction import letter_of_explanation as loe_module
from app.ai.extraction.letter_of_explanation import (
    LetterOfExplanationExtraction,
    LetterOfExplanationExtractionResult,
    _parse_loe_json,
    extract_letter_of_explanation,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy loe bytes"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "subject": _core("employment gap Mar-Aug 2023", snippet="explain the gap"),
        "explanation_summary": _core(
            "Borrower was between jobs after a layoff and returned to full-time work in Aug 2023."
        ),
        "referenced_employer": _core("ACME Corp"),
        "referenced_date": _core("2023-08-01", snippet="August 2023"),
        "referenced_amount": _core(None),
    },
    "additional_sections": [
        {
            "section": "References",
            "fields": [{"label": "Prior employer", "value": "Globex LLC", "page": 1}],
        }
    ],
    "confidence": 0.85,
    "reasoning": "A short borrower letter explaining a 2023 employment gap.",
}
FULL_JSON = json.dumps(FULL_PAYLOAD)


def _mock_complete(
    monkeypatch: pytest.MonkeyPatch, *, text: str | None = None, exc: Exception | None = None
) -> AsyncMock:
    if exc is not None:
        mock = AsyncMock(side_effect=exc)
    else:
        mock = AsyncMock(
            return_value=SimpleNamespace(text=text, input_tokens=120, output_tokens=50, model="m")
        )
    monkeypatch.setattr(loe_module, "complete", mock)
    return mock


def test_parse_prose_light_core() -> None:
    result = _parse_loe_json(FULL_JSON)
    assert result is not None
    assert result.status == ExtractionStatus.SUCCEEDED
    d = result.data
    assert d.subject.value == "employment gap Mar-Aug 2023"
    assert "layoff" in (d.explanation_summary.value or "")
    assert d.referenced_employer.value == "ACME Corp"
    assert d.referenced_date.value == date(2023, 8, 1)
    assert d.referenced_amount.value is None  # honest null — no amount in this letter


def test_additional_references_in_catch_all() -> None:
    d = _parse_loe_json(FULL_JSON).data  # type: ignore[union-attr]
    labels = [f.label for s in d.additional_sections for f in s.fields]
    assert "Prior employer" in labels  # extra reference preserved, not forced into the core


def test_subject_only_still_succeeds() -> None:
    """A bare letter with just a subject + summary is a valid (non-failed) extraction."""
    payload = {
        "typed_core": {
            "subject": _core("large deposit"),
            "explanation_summary": _core("The $12,000 deposit was the sale of a vehicle."),
        },
        "confidence": 0.8,
    }
    result = _parse_loe_json(json.dumps(payload))
    assert result is not None
    assert result.status == ExtractionStatus.SUCCEEDED
    assert result.data.referenced_amount.value is None


def test_referenced_amount_coerced_when_present() -> None:
    payload = {
        "typed_core": {
            "subject": _core("large deposit"),
            "referenced_amount": _core("$12,000.00", snippet="deposit of $12,000"),
        },
        "confidence": 0.8,
    }
    d = _parse_loe_json(json.dumps(payload)).data  # type: ignore[union-attr]
    assert d.referenced_amount.value == Decimal("12000.00")


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"subject": _core(None), "explanation_summary": _core(None)}}
    result = _parse_loe_json(json.dumps(payload))
    assert result is not None
    assert result.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_loe_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_letter_of_explanation(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED
    assert result.data.subject.value == "employment gap Mar-Aug 2023"


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_letter_of_explanation(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


async def test_does_not_log_values(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    with structlog.testing.capture_logs() as logs:
        await extract_letter_of_explanation(PDF_BYTES, "application/pdf")
    blob = " ".join(repr(e) for e in logs)
    assert "ACME Corp" not in blob and "layoff" not in blob
    done = [e for e in logs if e["event"] == "loe_extraction_done"]
    assert len(done) == 1 and done[0]["core_fields_present"] == 4


def test_failed_factory() -> None:
    result = LetterOfExplanationExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == LetterOfExplanationExtraction()

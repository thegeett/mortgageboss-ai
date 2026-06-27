"""Tests for gift letter extraction (LP-61) — the AI wrapper is MOCKED.

A gift letter is attestation prose. Focus: the typed core captures the parties +
amount + the **no-repayment attestation** (what makes it a gift vs. undisclosed
debt); the attestation stays null when the letter doesn't state it (honest null);
graceful failure. No account number is present.

No real gift letter samples were available — these verify the mechanism/shape,
not accuracy against real letters (validated as real documents flow through;
field set refined with Priya).
"""

import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import structlog
from app.ai.client import AIClientError
from app.ai.extraction import gift_letter as gift_module
from app.ai.extraction.gift_letter import (
    GiftLetterExtraction,
    GiftLetterExtractionResult,
    _parse_gift_letter_json,
    extract_gift_letter,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy gift letter bytes"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "donor_name": _core("John Doe", snippet="Donor: John Doe"),
        "donor_relationship": _core("father"),
        "recipient_name": _core("Jane Doe"),
        "gift_amount": _core("$56,000.00", snippet="gift of $56,000"),
        "property_address": _core("123 Main St"),
        "no_repayment_attestation": _core(
            "These funds are a gift and no repayment is expected.",
            snippet="no repayment is expected",
        ),
    },
    "additional_sections": [
        {"section": "Source of Funds", "fields": [{"label": "Donor bank", "value": "First Nat'l"}]}
    ],
    "confidence": 0.92,
    "reasoning": "Signed gift letter.",
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
    monkeypatch.setattr(gift_module, "complete", mock)
    return mock


def test_parse_attestation_oriented_core() -> None:
    result = _parse_gift_letter_json(FULL_JSON)
    assert result is not None
    assert result.status == ExtractionStatus.SUCCEEDED
    d = result.data
    assert d.donor_name.value == "John Doe"
    assert d.donor_relationship.value == "father"
    assert d.gift_amount.value == Decimal("56000.00")  # "$56,000.00" coerced
    # The no-repayment attestation — what distinguishes a gift from undisclosed debt.
    assert d.no_repayment_attestation.value is not None
    assert "no repayment" in d.no_repayment_attestation.value.lower()


def test_attestation_null_when_absent() -> None:
    """If the letter has no no-repayment statement, the attestation stays null."""
    payload = {
        "typed_core": {
            "donor_name": _core("John Doe"),
            "gift_amount": _core("56000"),
        },
        "confidence": 0.7,
    }
    d = _parse_gift_letter_json(json.dumps(payload)).data  # type: ignore[union-attr]
    assert d.gift_amount.value == Decimal("56000")
    assert d.no_repayment_attestation.value is None  # not fabricated


def test_source_location_present() -> None:
    d = _parse_gift_letter_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.gift_amount.source is not None and d.gift_amount.source.snippet == "gift of $56,000"


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"donor_name": _core(None), "gift_amount": _core(None)}}
    result = _parse_gift_letter_json(json.dumps(payload))
    assert result is not None
    assert result.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_gift_letter_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_gift_letter(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED
    assert result.data.gift_amount.value == Decimal("56000.00")


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_gift_letter(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


async def test_does_not_log_values(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    with structlog.testing.capture_logs() as logs:
        await extract_gift_letter(PDF_BYTES, "application/pdf")
    blob = " ".join(repr(e) for e in logs)
    assert "John Doe" not in blob and "56000" not in blob and "56,000" not in blob
    done = [e for e in logs if e["event"] == "gift_letter_extraction_done"]
    assert len(done) == 1 and done[0]["core_fields_present"] == 6


def test_failed_factory() -> None:
    result = GiftLetterExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == GiftLetterExtraction()

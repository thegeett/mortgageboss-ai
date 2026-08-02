"""Tests for verification of rent extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.verification_of_rent import (
    VerificationOfRentExtraction,
    VerificationOfRentExtractionResult,
    _parse_verification_of_rent_json,
    extract_verification_of_rent,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy verification_of_rent"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "document_title": _core("SAMPLE"),
        "landlord_or_property_manager_name": _core("SAMPLE"),
        "landlord_contact_phone": _core("SAMPLE"),
        "landlord_relationship_to_borrower": _core("SAMPLE"),
        "tenant_name": _core("SAMPLE"),
        "tenant_name_2": _core("SAMPLE"),
        "rental_property_address": _core("SAMPLE"),
        "lease_start_date": _core("2024-01-15"),
        "lease_end_date": _core("2024-01-15"),
        "current_tenant_indicator": _core("SAMPLE"),
        "monthly_rent": _core("1234.56"),
        "rent_due_day": _core(2024),
        "subsidy_or_concession": _core("SAMPLE"),
        "late_payment_count": _core(2024),
        "returned_payment_count": _core(2024),
        "current_arrears": _core("1234.56"),
        "eviction_or_collection_status": _core("SAMPLE"),
        "verifier_name_title": _core("SAMPLE"),
        "verification_date": _core("2024-01-15"),
        "independent_source_indicator": _core("SAMPLE"),
    },
    "additional_sections": [{"section": "Other", "fields": [{"label": "Note", "value": "x"}]}],
    "rent_payment_history": [
        {
            "month": "SAMPLE",
            "amount_due": "1234.56",
            "amount_paid": "1234.56",
            "payment_status": "SAMPLE",
            "source": "SAMPLE",
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
    d = _parse_verification_of_rent_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.document_title.value == "SAMPLE"
    assert d.document_title.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"document_title": _core(None)}}
    parsed = _parse_verification_of_rent_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_verification_of_rent_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_verification_of_rent(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_verification_of_rent(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = VerificationOfRentExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == VerificationOfRentExtraction()

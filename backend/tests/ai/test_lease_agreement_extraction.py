"""Tests for lease agreement extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.lease_agreement import (
    LeaseAgreementExtraction,
    LeaseAgreementExtractionResult,
    _parse_lease_agreement_json,
    extract_lease_agreement,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy lease_agreement"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "document_title": _core("SAMPLE"),
        "issuer_name": _core("SAMPLE"),
        "landlord_or_lessor_names_raw": _core("SAMPLE"),
        "landlord_or_lessor_name": _core("SAMPLE"),
        "landlord_or_lessor_name_2": _core("SAMPLE"),
        "tenant_or_lessee_names_raw": _core("SAMPLE"),
        "tenant_or_lessee_name": _core("SAMPLE"),
        "tenant_or_lessee_name_2": _core("SAMPLE"),
        "rental_property_address": _core("SAMPLE"),
        "unit_or_premises_description": _core("SAMPLE"),
        "lease_start_date": _core("2024-01-15"),
        "lease_end_date": _core("2024-01-15"),
        "lease_term_type": _core("SAMPLE"),
        "monthly_rent": _core("1234.56"),
        "rent_due_date_or_day": _core("SAMPLE"),
        "security_deposit": _core("1234.56"),
        "renewal_and_termination_terms": _core("SAMPLE"),
        "landlord_signature_date": _core("2024-01-15"),
        "tenant_signature_date": _core("2024-01-15"),
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
    d = _parse_lease_agreement_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.document_title.value == "SAMPLE"
    assert d.document_title.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"document_title": _core(None)}}
    parsed = _parse_lease_agreement_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_lease_agreement_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_lease_agreement(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_lease_agreement(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = LeaseAgreementExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == LeaseAgreementExtraction()

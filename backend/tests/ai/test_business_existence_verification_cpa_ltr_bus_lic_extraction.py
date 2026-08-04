"""Tests for business existence verification cpa ltr bus lic extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.business_existence_verification_cpa_ltr_bus_lic import (
    BusinessExistenceVerificationCpaLtrBusLicExtraction,
    BusinessExistenceVerificationCpaLtrBusLicExtractionResult,
    _parse_business_existence_verification_cpa_ltr_bus_lic_json,
    extract_business_existence_verification_cpa_ltr_bus_lic,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy business_existence_verification_cpa_ltr_bus_lic"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "business_legal_name": _core("SAMPLE"),
        "entity_type": _core("SAMPLE"),
        "business_address": _core("SAMPLE"),
        "ein_or_state_entity_number_masked": _core("SAMPLE"),
        "formation_or_incorporation_date": _core("2024-01-15"),
        "business_start_date": _core("2024-01-15"),
        "industry_or_business_activity": _core("SAMPLE"),
        "active_or_good_standing_status": _core("SAMPLE"),
        "status_as_of_date": _core("2024-01-15"),
        "borrower_owner_name": _core("SAMPLE"),
        "borrower_owner_name_2": _core("SAMPLE"),
        "ownership_percentage": _core("SAMPLE"),
        "owner_title_or_role": _core("SAMPLE"),
        "verification_document_type": _core("SAMPLE"),
        "license_or_registration_number": _core("SAMPLE"),
        "license_issue_date": _core("2024-01-15"),
        "license_expiration_date": _core("2024-01-15"),
        "verifying_authority_or_cpa": _core("SAMPLE"),
        "verification_method": _core("SAMPLE"),
        "verification_date": _core("2024-01-15"),
        "issuer_name": _core("SAMPLE"),
        "account_case_reference_number": _core("SAMPLE"),
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
    d = _parse_business_existence_verification_cpa_ltr_bus_lic_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.business_legal_name.value == "SAMPLE"
    assert d.business_legal_name.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"business_legal_name": _core(None)}}
    parsed = _parse_business_existence_verification_cpa_ltr_bus_lic_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_business_existence_verification_cpa_ltr_bus_lic_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_business_existence_verification_cpa_ltr_bus_lic(
        PDF_BYTES, "application/pdf"
    )
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_business_existence_verification_cpa_ltr_bus_lic(
        PDF_BYTES, "application/pdf"
    )
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = BusinessExistenceVerificationCpaLtrBusLicExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == BusinessExistenceVerificationCpaLtrBusLicExtraction()

"""Tests for certificate of eligibility extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.certificate_of_eligibility import (
    CertificateOfEligibilityExtraction,
    CertificateOfEligibilityExtractionResult,
    _parse_certificate_of_eligibility_json,
    extract_certificate_of_eligibility,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy certificate_of_eligibility"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "issuer_name": _core("SAMPLE"),
        "regional_loan_center_or_issuer": _core("SAMPLE"),
        "veteran_or_service_member_name": _core("SAMPLE"),
        "social_security_number_masked": _core("SAMPLE"),
        "va_file_or_loan_number": _core("SAMPLE"),
        "coe_status": _core("SAMPLE"),
        "coe_issue_date": _core("2024-01-15"),
        "entitlement_code": _core("SAMPLE"),
        "basic_entitlement_amount": _core("1234.56"),
        "available_entitlement_amount": _core("1234.56"),
        "funding_fee_exempt_indicator": _core("SAMPLE"),
        "funding_fee_exemption_reason": _core("SAMPLE"),
        "disability_compensation_status": _core("SAMPLE"),
        "restoration_status": _core("SAMPLE"),
        "minimum_service_requirement_met": _core("SAMPLE"),
        "branch_of_service": _core("SAMPLE"),
        "service_status": _core("SAMPLE"),
        "surviving_spouse_indicator": _core("SAMPLE"),
    },
    "additional_sections": [{"section": "Other", "fields": [{"label": "Note", "value": "x"}]}],
    "prior_va_loan_or_entitlement_charges": [
        {
            "prior_loan_reference": "SAMPLE",
            "entitlement_amount_charged": "1234.56",
            "prior_loan_status": "SAMPLE",
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
    d = _parse_certificate_of_eligibility_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.issuer_name.value == "SAMPLE"
    assert d.issuer_name.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"issuer_name": _core(None)}}
    parsed = _parse_certificate_of_eligibility_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_certificate_of_eligibility_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_certificate_of_eligibility(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_certificate_of_eligibility(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = CertificateOfEligibilityExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == CertificateOfEligibilityExtraction()

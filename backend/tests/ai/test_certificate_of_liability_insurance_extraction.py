"""Tests for certificate of liability insurance extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.certificate_of_liability_insurance import (
    CertificateOfLiabilityInsuranceExtraction,
    CertificateOfLiabilityInsuranceExtractionResult,
    _parse_certificate_of_liability_insurance_json,
    extract_certificate_of_liability_insurance,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy certificate_of_liability_insurance"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "certificate_number": _core("SAMPLE"),
        "certificate_date": _core("2024-01-15"),
        "producer_name": _core("SAMPLE"),
        "producer_address": _core("SAMPLE"),
        "insured_name": _core("SAMPLE"),
        "insured_address": _core("SAMPLE"),
        "certificate_holder_name": _core("SAMPLE"),
        "certificate_holder_address": _core("SAMPLE"),
        "description_of_operations": _core("SAMPLE"),
        "project_or_property_reference": _core("SAMPLE"),
    },
    "additional_sections": [{"section": "Other", "fields": [{"label": "Note", "value": "x"}]}],
    "coverage_lines": [
        {
            "coverage_type": "SAMPLE",
            "insurer_name": "SAMPLE",
            "insurer_naic_number": "SAMPLE",
            "policy_number": "SAMPLE",
            "policy_effective_date": "2024-01-15",
            "policy_expiration_date": "2024-01-15",
            "limit_description": "SAMPLE",
            "limit_amount": "1234.56",
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
    d = _parse_certificate_of_liability_insurance_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.certificate_number.value == "SAMPLE"
    assert d.certificate_number.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"certificate_number": _core(None)}}
    parsed = _parse_certificate_of_liability_insurance_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_certificate_of_liability_insurance_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_certificate_of_liability_insurance(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_certificate_of_liability_insurance(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = CertificateOfLiabilityInsuranceExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == CertificateOfLiabilityInsuranceExtraction()

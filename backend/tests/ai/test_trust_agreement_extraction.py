"""Tests for trust agreement extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.trust_agreement import (
    TrustAgreementExtraction,
    TrustAgreementExtractionResult,
    _parse_trust_agreement_json,
    extract_trust_agreement,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy trust_agreement"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "document_title": _core("SAMPLE"),
        "issuer_name": _core("SAMPLE"),
        "trust_name": _core("SAMPLE"),
        "trust_execution_date": _core("2024-01-15"),
        "trust_type": _core("SAMPLE"),
        "revocable_indicator": _core("SAMPLE"),
        "governing_law_state": _core("SAMPLE"),
        "tax_identification_number_masked": _core("SAMPLE"),
        "grantor_or_settlor_name": _core("SAMPLE"),
        "grantor_or_settlor_name_2": _core("SAMPLE"),
        "grantor_or_settlor_count": _core(2024),
        "current_trustee_name": _core("SAMPLE"),
        "current_trustee_name_2": _core("SAMPLE"),
        "current_trustee_count": _core(2024),
        "successor_trustee_name": _core("SAMPLE"),
        "beneficiary_name": _core("SAMPLE"),
        "beneficiary_name_2": _core("SAMPLE"),
        "beneficiary_count": _core(2024),
        "borrower_role_in_trust": _core("SAMPLE"),
        "trustee_power_to_borrow": _core("SAMPLE"),
        "trustee_power_to_mortgage_or_encumber": _core("SAMPLE"),
        "trustee_power_to_buy_sell_or_hold_real_property": _core("SAMPLE"),
        "distribution_terms": _core("SAMPLE"),
        "subject_property_in_trust": _core("SAMPLE"),
        "trustee_signature_present": _core("SAMPLE"),
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
    d = _parse_trust_agreement_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.document_title.value == "SAMPLE"
    assert d.document_title.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"document_title": _core(None)}}
    parsed = _parse_trust_agreement_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_trust_agreement_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_trust_agreement(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_trust_agreement(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = TrustAgreementExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == TrustAgreementExtraction()

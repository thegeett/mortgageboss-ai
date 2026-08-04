"""Tests for social security administration ssa 89 extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.social_security_administration_ssa_89 import (
    SocialSecurityAdministrationSsa89Extraction,
    SocialSecurityAdministrationSsa89ExtractionResult,
    _parse_social_security_administration_ssa_89_json,
    extract_social_security_administration_ssa_89,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy social_security_administration_ssa_89"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "document_title": _core("SAMPLE"),
        "form_number": _core("SAMPLE"),
        "form_revision": _core("SAMPLE"),
        "issuer_name": _core("SAMPLE"),
        "printed_name": _core("SAMPLE"),
        "date_of_birth": _core("2024-01-15"),
        "social_security_number": _core("SAMPLE"),
        "consent_reason": _core("SAMPLE"),
        "other_consent_reason": _core("SAMPLE"),
        "company_name": _core("SAMPLE"),
        "company_address": _core("SAMPLE"),
        "agent_name": _core("SAMPLE"),
        "consent_validity_days": _core(2024),
        "custom_validity_initials": _core("SAMPLE"),
        "one_time_use_acknowledgment": _core("SAMPLE"),
        "individual_signature": _core("SAMPLE"),
        "date_signed": _core("2024-01-15"),
        "signer_relationship_if_representative": _core("SAMPLE"),
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
    d = _parse_social_security_administration_ssa_89_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.document_title.value == "SAMPLE"
    assert d.document_title.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"document_title": _core(None)}}
    parsed = _parse_social_security_administration_ssa_89_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_social_security_administration_ssa_89_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_social_security_administration_ssa_89(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_social_security_administration_ssa_89(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = SocialSecurityAdministrationSsa89ExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == SocialSecurityAdministrationSsa89Extraction()

"""Tests for birth certificate extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.birth_certificate import (
    BirthCertificateExtraction,
    BirthCertificateExtractionResult,
    _parse_birth_certificate_json,
    extract_birth_certificate,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy birth_certificate"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "child_name_at_birth": _core("SAMPLE"),
        "current_or_amended_name": _core("SAMPLE"),
        "date_of_birth": _core("2024-01-15"),
        "sex": _core("SAMPLE"),
        "place_of_birth": _core("SAMPLE"),
        "issuing_country_state_or_territory": _core("SAMPLE"),
        "issuing_vital_records_office": _core("SAMPLE"),
        "certificate_or_state_file_number": _core("SAMPLE"),
        "local_file_or_registration_number": _core("SAMPLE"),
        "registration_date": _core("2024-01-15"),
        "certificate_issue_date": _core("2024-01-15"),
        "certified_copy_indicator": _core("SAMPLE"),
        "amended_or_corrected_indicator": _core("SAMPLE"),
        "delayed_registration_indicator": _core("SAMPLE"),
        "parent_1_name": _core("SAMPLE"),
        "parent_2_name": _core("SAMPLE"),
        "registrar_name_or_seal": _core("SAMPLE"),
        "facility_or_place_of_birth": _core("SAMPLE"),
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
    d = _parse_birth_certificate_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.child_name_at_birth.value == "SAMPLE"
    assert d.child_name_at_birth.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"child_name_at_birth": _core(None)}}
    parsed = _parse_birth_certificate_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_birth_certificate_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_birth_certificate(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_birth_certificate(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = BirthCertificateExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == BirthCertificateExtraction()

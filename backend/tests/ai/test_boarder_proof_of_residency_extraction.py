"""Tests for boarder proof of residency extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.boarder_proof_of_residency import (
    BoarderProofOfResidencyExtraction,
    BoarderProofOfResidencyExtractionResult,
    _parse_boarder_proof_of_residency_json,
    extract_boarder_proof_of_residency,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy boarder_proof_of_residency"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "issuer_name": _core("SAMPLE"),
        "document_title": _core("SAMPLE"),
        "boarder_name": _core("SAMPLE"),
        "borrower_or_host_name": _core("SAMPLE"),
        "relationship_to_borrower": _core("SAMPLE"),
        "residence_address": _core("SAMPLE"),
        "unit_or_room_description": _core("SAMPLE"),
        "evidence_type": _core("SAMPLE"),
        "evidence_issuer_or_provider": _core("SAMPLE"),
        "document_date": _core("2024-01-15"),
        "coverage_or_service_period_start": _core("2024-01-15"),
        "coverage_or_service_period_end": _core("2024-01-15"),
        "account_or_reference_number_masked": _core("SAMPLE"),
        "residency_start_date": _core("2024-01-15"),
        "current_residency_indicator": _core("SAMPLE"),
        "mailing_and_service_address": _core("SAMPLE"),
        "occupancy_attestation": _core("SAMPLE"),
        "property_address": _core("SAMPLE"),
        "loan_number": _core("SAMPLE"),
        "account_case_reference_number": _core("SAMPLE"),
    },
    "additional_sections": [{"section": "Other", "fields": [{"label": "Note", "value": "x"}]}],
    "supporting_documents": [{"document_name": "SAMPLE", "page": 1, "snippet": "s"}],
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
    d = _parse_boarder_proof_of_residency_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.issuer_name.value == "SAMPLE"
    assert d.issuer_name.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"issuer_name": _core(None)}}
    parsed = _parse_boarder_proof_of_residency_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_boarder_proof_of_residency_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_boarder_proof_of_residency(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_boarder_proof_of_residency(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = BoarderProofOfResidencyExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == BoarderProofOfResidencyExtraction()

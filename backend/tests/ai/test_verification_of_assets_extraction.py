"""Tests for verification of assets extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.verification_of_assets import (
    VerificationOfAssetsExtraction,
    VerificationOfAssetsExtractionResult,
    _parse_verification_of_assets_json,
    extract_verification_of_assets,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy verification_of_assets"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "document_title": _core("SAMPLE"),
        "verification_provider_name": _core("SAMPLE"),
        "report_id": _core("SAMPLE"),
        "report_generated_date_time": _core("SAMPLE"),
        "data_refresh_date_time": _core("SAMPLE"),
        "verification_method": _core("SAMPLE"),
        "borrower_name": _core("SAMPLE"),
        "borrower_name_2": _core("SAMPLE"),
        "borrower_count": _core(2024),
        "consent_or_authorization_reference": _core("SAMPLE"),
        "total_verified_assets": _core("1234.56"),
        "total_available_assets": _core("1234.56"),
    },
    "additional_sections": [{"section": "Other", "fields": [{"label": "Note", "value": "x"}]}],
    "verified_accounts": [
        {
            "institution_name": "SAMPLE",
            "account_number_masked": "SAMPLE",
            "account_type": "SAMPLE",
            "account_holder_name": "SAMPLE",
            "current_balance": "1234.56",
            "available_balance": "1234.56",
            "average_balance": "1234.56",
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
    d = _parse_verification_of_assets_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.document_title.value == "SAMPLE"
    assert d.document_title.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"document_title": _core(None)}}
    parsed = _parse_verification_of_assets_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_verification_of_assets_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_verification_of_assets(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_verification_of_assets(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = VerificationOfAssetsExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == VerificationOfAssetsExtraction()

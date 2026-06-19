"""Tests for driver's license / ID extraction (LP-63) — the AI wrapper is MOCKED.

The driver's license is the most identity-dense document in the product, so the
critical test here is **PRIVACY**: the ID number (masked) and the DOB are captured
for the Phase 3 identity cross-check but are **never logged**. All data here is
SYNTHETIC — never a real identity document. Also covers the shape, source
locations, the expiration capture (staleness), and graceful failure.

No real ID samples were available (and only synthetic data is ever used for IDs) —
these verify the mechanism/shape, not accuracy against real IDs.
"""

import base64
import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import structlog
from app.ai.client import AIClientError
from app.ai.extraction import drivers_license as dl_module
from app.ai.extraction.drivers_license import (
    DriversLicenseExtraction,
    DriversLicenseExtractionResult,
    _parse_drivers_license_json,
    extract_drivers_license,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy id bytes"
# SYNTHETIC identity values — never a real person.
SYNTH_DOB = "1990-04-15"
SYNTH_ID_MASKED = "****1234"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "full_name": _core("Jane A Doe"),
        "date_of_birth": _core(SYNTH_DOB, snippet="DOB 04/15/1990"),
        "address": _core("100 Test St, Anytown CA"),
        "id_number_masked": _core(SYNTH_ID_MASKED, snippet="DL ****1234"),
        "issuing_state": _core("CA"),
        "issuing_authority": _core("DMV"),
        "expiration_date": _core("2028-05-01", snippet="EXP 05/01/2028"),
    },
    "additional_sections": [
        {"section": "License Details", "fields": [{"label": "Class", "value": "C"}]}
    ],
    "confidence": 0.92,
    "reasoning": "State driver's license.",
}
FULL_JSON = json.dumps(FULL_PAYLOAD)


def _mock_complete(
    monkeypatch: pytest.MonkeyPatch, *, text: str | None = None, exc: Exception | None = None
) -> AsyncMock:
    if exc is not None:
        mock = AsyncMock(side_effect=exc)
    else:
        mock = AsyncMock(
            return_value=SimpleNamespace(text=text, input_tokens=120, output_tokens=50, model="m")
        )
    monkeypatch.setattr(dl_module, "complete", mock)
    return mock


def test_parse_full_shape_with_types() -> None:
    result = _parse_drivers_license_json(FULL_JSON)
    assert result is not None
    assert result.status == ExtractionStatus.SUCCEEDED
    d = result.data
    assert d.full_name.value == "Jane A Doe"
    assert d.date_of_birth.value == date(1990, 4, 15)  # coerced to a date
    assert d.id_number_masked.value == SYNTH_ID_MASKED


def test_expiration_date_captured_for_staleness() -> None:
    """The ID expiration is captured (an expired ID is invalid → staleness, LP-71)."""
    d = _parse_drivers_license_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.expiration_date.value == date(2028, 5, 1)
    assert (
        d.expiration_date.source is not None
        and d.expiration_date.source.snippet == "EXP 05/01/2028"
    )


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"full_name": _core(None), "id_number_masked": _core(None)}}
    result = _parse_drivers_license_json(json.dumps(payload))
    assert result is not None
    assert result.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_drivers_license_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_drivers_license(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED
    assert result.data.expiration_date.value == date(2028, 5, 1)


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_drivers_license(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("media_type", ["text/plain", ""])
async def test_extract_unsupported_skips_api(
    monkeypatch: pytest.MonkeyPatch, media_type: str
) -> None:
    mock = _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_drivers_license(PDF_BYTES, media_type)
    assert result.status == ExtractionStatus.FAILED
    assert mock.call_count == 0


# --------------------------------------------------------------------------- #
# PRIVACY — the CRITICAL check for this batch: NO ID values logged
# --------------------------------------------------------------------------- #


async def test_does_not_log_any_id_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole ID is PII: name, DOB, ID number, address must NEVER be logged."""
    pii_bytes = b"%PDF ID Jane A Doe DOB 1990 DL 9991234"
    pii_b64 = base64.standard_b64encode(pii_bytes).decode("utf-8")
    _mock_complete(monkeypatch, text=FULL_JSON)

    with structlog.testing.capture_logs() as logs:
        result = await extract_drivers_license(pii_bytes, "application/pdf")

    blob = " ".join(repr(e) for e in logs)
    assert SYNTH_DOB not in blob  # the DOB value
    assert "04/15/1990" not in blob and "1990" not in blob  # any DOB rendering
    assert SYNTH_ID_MASKED not in blob and "1234" not in blob  # even the masked ID number
    assert "Jane A Doe" not in blob  # the name
    assert "100 Test St" not in blob  # the address
    assert pii_b64 not in blob  # the base64 payload
    done = [e for e in logs if e["event"] == "drivers_license_extraction_done"]
    assert len(done) == 1
    assert done[0]["core_fields_present"] == 7  # only a COUNT is logged
    # The raw values are still available to the caller (tenant-scoped JSON).
    assert result.data.date_of_birth.value == date(1990, 4, 15)
    assert result.data.id_number_masked.value == SYNTH_ID_MASKED


def test_failed_factory() -> None:
    result = DriversLicenseExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == DriversLicenseExtraction()

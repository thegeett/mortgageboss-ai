"""Tests for pay stub extraction (LP-39) — the AI wrapper is MOCKED.

No real API calls and no key: ``complete`` is patched to return canned text or
raise. Extraction now reads the **full document** (PDF/image bytes) natively
(LP-39 modification, LP-37 revision), so the tests pass bytes + a media type. The
focus is the contract — typed coercion (Decimal/date), HONEST NULLS (missing
values are never fabricated), tolerant per-field coercion (one bad field → None,
not a whole-extraction failure), graceful ``failed`` on any error, the
empty/unsupported-document short-circuit, confidence clamping, and the privacy
rule that the document bytes/base64 / raw response / extracted VALUES are never
logged. Dummy bytes are fine (the SDK/wrapper is mocked).
"""

import base64
import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import structlog
from app.ai.client import AIClientError
from app.ai.extraction import pay_stub as pay_stub_module
from app.ai.extraction.pay_stub import (
    PayStubExtraction,
    PayStubExtractionResult,
    _parse_pay_stub_json,
    extract_pay_stub,
)
from app.models.extraction import ExtractionStatus

# Dummy document bytes — the wrapper is mocked, so these need not be real files.
PDF_BYTES = b"%PDF-1.7 dummy pay stub bytes"
PNG_BYTES = b"\x89PNG\r\n\x1a\n dummy image bytes"

FULL_JSON = json.dumps(
    {
        "employer_name": "ACME Corp",
        "employee_name": "Jane Doe",
        "pay_period_start": "2024-06-01",
        "pay_period_end": "2024-06-15",
        "pay_date": "2024-06-20",
        "gross_pay": "$4,200.00",
        "net_pay": "3180.55",
        "ytd_gross": "50400.00",
        "pay_frequency": "semimonthly",
        "hours": None,
        "rate": None,
        "confidence": 0.9,
        "reasoning": "Standard pay stub.",
    }
)


def _mock_complete(
    monkeypatch: pytest.MonkeyPatch, *, text: str | None = None, exc: Exception | None = None
) -> AsyncMock:
    if exc is not None:
        mock = AsyncMock(side_effect=exc)
    else:
        mock = AsyncMock(
            return_value=SimpleNamespace(text=text, input_tokens=200, output_tokens=80, model="m")
        )
    monkeypatch.setattr(pay_stub_module, "complete", mock)
    return mock


# --------------------------------------------------------------------------- #
# Parser: typed coercion + honest nulls
# --------------------------------------------------------------------------- #


def test_parse_full_pay_stub_typed_values() -> None:
    result = _parse_pay_stub_json(FULL_JSON)
    assert result is not None
    assert result.status == ExtractionStatus.SUCCEEDED
    assert result.confidence == 0.9
    d = result.data
    assert d.employer_name == "ACME Corp"
    assert d.employee_name == "Jane Doe"
    assert d.pay_period_start == date(2024, 6, 1)
    assert d.pay_period_end == date(2024, 6, 15)
    assert d.pay_date == date(2024, 6, 20)
    assert d.gross_pay == Decimal("4200.00")  # "$4,200.00" coerced
    assert d.net_pay == Decimal("3180.55")
    assert d.ytd_gross == Decimal("50400.00")
    assert d.pay_frequency == "semimonthly"
    assert d.hours is None  # honest null, not fabricated
    assert d.rate is None


def test_parse_json_in_fences_and_preamble() -> None:
    raw = f"Sure, here is the data:\n```json\n{FULL_JSON}\n```\nLet me know!"
    result = _parse_pay_stub_json(raw)
    assert result is not None
    assert result.data.employer_name == "ACME Corp"


def test_missing_fields_are_null_not_fabricated() -> None:
    raw = json.dumps({"employer_name": "ACME Corp", "gross_pay": "4200", "confidence": 0.6})
    result = _parse_pay_stub_json(raw)
    assert result is not None
    assert result.data.employer_name == "ACME Corp"
    assert result.data.gross_pay == Decimal("4200")
    # Everything else absent → None (never invented).
    assert result.data.employee_name is None
    assert result.data.net_pay is None
    assert result.data.pay_date is None
    assert result.status == ExtractionStatus.SUCCEEDED  # absent != coercion loss


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("$4,200.00", Decimal("4200.00")),
        ("4200", Decimal("4200")),
        ("4,200.50", Decimal("4200.50")),
        (4200, Decimal("4200")),
        (4200.5, Decimal("4200.5")),
    ],
)
def test_currency_coercion(raw_value: object, expected: Decimal) -> None:
    raw = json.dumps({"gross_pay": raw_value, "confidence": 0.5})
    result = _parse_pay_stub_json(raw)
    assert result is not None
    assert result.data.gross_pay == expected


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("2024-06-15", date(2024, 6, 15)),
        ("06/15/2024", date(2024, 6, 15)),
        ("June 15, 2024", date(2024, 6, 15)),
    ],
)
def test_date_coercion(raw_value: str, expected: date) -> None:
    raw = json.dumps({"pay_date": raw_value, "confidence": 0.5})
    result = _parse_pay_stub_json(raw)
    assert result is not None
    assert result.data.pay_date == expected


def test_junk_field_becomes_none_others_intact_and_partial() -> None:
    raw = json.dumps(
        {
            "employer_name": "ACME Corp",
            "gross_pay": "not a number",  # uncoercible → None, marks PARTIAL
            "net_pay": "3180.55",
            "confidence": 0.7,
        }
    )
    result = _parse_pay_stub_json(raw)
    assert result is not None
    assert result.data.gross_pay is None  # bad field dropped
    assert result.data.net_pay == Decimal("3180.55")  # others intact
    assert result.data.employer_name == "ACME Corp"
    assert result.status == ExtractionStatus.PARTIAL  # data was lost


def test_all_null_response_is_failed_status() -> None:
    raw = json.dumps({"employer_name": None, "gross_pay": None, "confidence": 0.1})
    result = _parse_pay_stub_json(raw)
    assert result is not None
    assert result.status == ExtractionStatus.FAILED  # nothing extracted


@pytest.mark.parametrize("raw", ["not json", "", "{ broken", "[1,2,3]"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_pay_stub_json(raw) is None


def test_parse_clamps_confidence() -> None:
    raw = json.dumps({"gross_pay": "100", "confidence": 1.7})
    result = _parse_pay_stub_json(raw)
    assert result is not None
    assert result.confidence == 1.0


def test_accepts_fields_nested_under_data_key() -> None:
    raw = json.dumps({"data": {"employer_name": "ACME Corp"}, "confidence": 0.8})
    result = _parse_pay_stub_json(raw)
    assert result is not None
    assert result.data.employer_name == "ACME Corp"


# --------------------------------------------------------------------------- #
# extract_pay_stub
# --------------------------------------------------------------------------- #


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_pay_stub(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED
    assert result.data.gross_pay == Decimal("4200.00")
    assert mock.call_count == 1
    kwargs = mock.await_args.kwargs
    assert kwargs["model"] == pay_stub_module.settings.anthropic_model_extraction
    assert "system" in kwargs
    # Sends a document block (not a text string); base64 round-trips to the bytes.
    block = kwargs["messages"][0]["content"][0]
    assert block["type"] == "document"
    assert block["source"]["media_type"] == "application/pdf"
    assert base64.standard_b64decode(block["source"]["data"]) == PDF_BYTES


async def test_extract_image_input_uses_image_block(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_pay_stub(PNG_BYTES, "image/png")
    assert result.status == ExtractionStatus.SUCCEEDED
    block = mock.await_args.kwargs["messages"][0]["content"][0]
    assert block["type"] == "image"
    assert block["source"]["media_type"] == "image/png"


async def test_extract_malformed_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text="I read a pay stub for Jane, gross was around 4k.")
    result = await extract_pay_stub(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED
    assert result.confidence == 0.0
    assert result.data == PayStubExtraction()  # all-null
    assert "parse" in (result.reasoning or "").lower()


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_pay_stub(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED
    assert "ai call failed" in (result.reasoning or "").lower()


async def test_extract_empty_document_skips_api(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_pay_stub(b"", "application/pdf")
    assert result.status == ExtractionStatus.FAILED
    assert mock.call_count == 0  # never called the API


@pytest.mark.parametrize("media_type", ["text/plain", "application/zip", "image/gif", ""])
async def test_extract_unsupported_media_type_skips_api(
    monkeypatch: pytest.MonkeyPatch, media_type: str
) -> None:
    mock = _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_pay_stub(PDF_BYTES, media_type)
    assert result.status == ExtractionStatus.FAILED
    assert mock.call_count == 0  # unsupported type → no API call


# --------------------------------------------------------------------------- #
# PRIVACY: never log document bytes/base64 / raw response / extracted values
# --------------------------------------------------------------------------- #


async def test_does_not_log_bytes_base64_or_values(monkeypatch: pytest.MonkeyPatch) -> None:
    pii_bytes = b"%PDF Jane Doe SSN 123-45-6789 employer SECRETCORP gross 9999.99"
    pii_b64 = base64.standard_b64encode(pii_bytes).decode("utf-8")
    _mock_complete(
        monkeypatch,
        text=json.dumps(
            {
                "employer_name": "SECRETCORP",
                "employee_name": "Jane Doe",
                "gross_pay": "9999.99",
                "confidence": 0.9,
                "reasoning": "clear",
            }
        ),
    )
    with structlog.testing.capture_logs() as logs:
        result = await extract_pay_stub(pii_bytes, "application/pdf")

    blob = " ".join(repr(e) for e in logs)
    assert "123-45-6789" not in blob  # raw document byte content
    assert pii_b64 not in blob  # base64 payload never logged
    assert "SECRETCORP" not in blob  # extracted value not logged
    assert "9999.99" not in blob
    # The metadata log IS present: status, confidence, field count only.
    done = [e for e in logs if e["event"] == "paystub_extraction_done"]
    assert len(done) == 1
    assert done[0]["status"] == ExtractionStatus.SUCCEEDED
    assert done[0]["fields_present"] == 3
    assert "employer_name" not in done[0]  # no field values in the log
    assert result.data.employer_name == "SECRETCORP"  # but returned to the caller


def test_failed_factory() -> None:
    result = PayStubExtractionResult.failed("because reasons")
    assert result.status == ExtractionStatus.FAILED
    assert result.confidence == 0.0
    assert result.reasoning == "because reasons"
    assert result.data == PayStubExtraction()  # all fields None

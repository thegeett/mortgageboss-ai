"""Tests for pay stub extraction (LP-39a shape) — the AI wrapper is MOCKED.

No real API calls/key. Extraction now returns the **typed core + grouped
catch-all + per-field source** shape. The focus: the typed core is coerced
(Decimal/date) with **source location** (page+snippet); **nothing is dropped**
(non-core fields land in the grouped catch-all); HONEST NULLS (absent → None);
tolerant per-field coercion (one bad core field → None, source kept, PARTIAL);
graceful ``failed`` on any error; the empty/unsupported short-circuit; confidence
clamping; and the privacy rule (bytes/base64/values never logged).
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

PDF_BYTES = b"%PDF-1.7 dummy pay stub bytes"
PNG_BYTES = b"\x89PNG\r\n\x1a\n dummy image bytes"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "employer_name": _core("ACME Corp", snippet="ACME Corp"),
        "employee_name": _core("Jane Doe", snippet="Jane Doe"),
        "pay_period_start": _core("2024-06-01", snippet="06/01/2024"),
        "pay_period_end": _core("2024-06-15", snippet="Period Ending 06/15/2024"),
        "pay_date": _core("2024-06-20", snippet="Pay Date 06/20/2024"),
        "gross_pay": _core("$4,200.00", snippet="Gross Pay 4,200.00"),
        "net_pay": _core("3180.55", snippet="Net Pay 3,180.55"),
        "ytd_gross": _core("50400.00", snippet="YTD 50,400.00"),
        "pay_frequency": _core("semimonthly", snippet="Semi-Monthly"),
        "hours": _core(None, page=None, snippet=None),
        "rate": _core(None, page=None, snippet=None),
    },
    "additional_sections": [
        {
            "section": "Deductions",
            "fields": [
                {"label": "401(k)", "value": "210.00", "page": 1, "snippet": "401(k) 210.00"},
                {"label": "Medical", "value": "85.00", "page": 1, "snippet": "Medical 85.00"},
            ],
        },
        {
            "section": "Taxes",
            "fields": [
                {"label": "Federal", "value": "540.00", "page": 1, "snippet": "Fed Tax 540.00"},
            ],
        },
    ],
    "confidence": 0.9,
    "reasoning": "Standard pay stub.",
}
FULL_JSON = json.dumps(FULL_PAYLOAD)


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
# Parser: typed core (coerced + source) + grouped catch-all
# --------------------------------------------------------------------------- #


def test_parse_full_shape_typed_core_and_catch_all() -> None:
    result = _parse_pay_stub_json(FULL_JSON)
    assert result is not None
    assert result.status == ExtractionStatus.SUCCEEDED
    assert result.confidence == 0.9
    d = result.data
    # Typed core — coerced values.
    assert d.employer_name.value == "ACME Corp"
    assert d.pay_period_end.value == date(2024, 6, 15)
    assert d.pay_date.value == date(2024, 6, 20)
    assert d.gross_pay.value == Decimal("4200.00")  # "$4,200.00" coerced
    assert d.net_pay.value == Decimal("3180.55")
    assert d.pay_frequency.value == "semimonthly"
    assert d.hours.value is None  # honest null
    assert d.rate.value is None
    # Grouped catch-all — preserved, by section, values as strings.
    assert [s.section for s in d.additional_sections] == ["Deductions", "Taxes"]
    deductions = d.additional_sections[0]
    assert [(f.label, f.value) for f in deductions.fields] == [
        ("401(k)", "210.00"),
        ("Medical", "85.00"),
    ]


def test_source_location_on_core_and_catch_all() -> None:
    d = _parse_pay_stub_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.gross_pay.source is not None
    assert d.gross_pay.source.page == 1
    assert d.gross_pay.source.snippet == "Gross Pay 4,200.00"
    # Absent field → no source.
    assert d.hours.source is None
    # Catch-all field carries source too.
    fed = d.additional_sections[1].fields[0]
    assert (
        fed.source is not None and fed.source.page == 1 and fed.source.snippet == "Fed Tax 540.00"
    )


def test_nothing_dropped_non_core_lands_in_catch_all() -> None:
    """A field that isn't part of the typed core must appear in the catch-all."""
    payload = {
        "typed_core": {"gross_pay": _core("4200")},
        "additional_sections": [
            {"section": "Other", "fields": [{"label": "Check Number", "value": "00123"}]}
        ],
        "confidence": 0.8,
    }
    d = _parse_pay_stub_json(json.dumps(payload)).data  # type: ignore[union-attr]
    assert d.gross_pay.value == Decimal("4200")  # core
    labels = [f.label for s in d.additional_sections for f in s.fields]
    assert "Check Number" in labels  # nothing lost


def test_parse_json_in_fences_and_preamble() -> None:
    raw = f"Sure:\n```json\n{FULL_JSON}\n```\nThanks!"
    result = _parse_pay_stub_json(raw)
    assert result is not None
    assert result.data.employer_name.value == "ACME Corp"


def test_missing_core_fields_are_null_not_fabricated() -> None:
    payload = {"typed_core": {"employer_name": _core("ACME Corp"), "gross_pay": _core("4200")}}
    result = _parse_pay_stub_json(json.dumps(payload))
    assert result is not None
    assert result.data.employer_name.value == "ACME Corp"
    assert result.data.gross_pay.value == Decimal("4200")
    assert result.data.employee_name.value is None
    assert result.data.net_pay.value is None
    assert result.status == ExtractionStatus.SUCCEEDED  # absent != coercion loss


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [("$4,200.00", Decimal("4200.00")), ("4200", Decimal("4200")), (4200.5, Decimal("4200.5"))],
)
def test_currency_coercion(raw_value: object, expected: Decimal) -> None:
    payload = {"typed_core": {"gross_pay": _core(raw_value)}, "confidence": 0.5}
    result = _parse_pay_stub_json(json.dumps(payload))
    assert result is not None
    assert result.data.gross_pay.value == expected


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [("2024-06-15", date(2024, 6, 15)), ("06/15/2024", date(2024, 6, 15))],
)
def test_date_coercion(raw_value: str, expected: date) -> None:
    payload = {"typed_core": {"pay_date": _core(raw_value)}, "confidence": 0.5}
    result = _parse_pay_stub_json(json.dumps(payload))
    assert result is not None
    assert result.data.pay_date.value == expected


def test_junk_core_field_becomes_none_keeps_source_and_partial() -> None:
    payload = {
        "typed_core": {
            "employer_name": _core("ACME Corp"),
            "gross_pay": _core("not a number", snippet="Gross ???"),  # uncoercible → None
            "net_pay": _core("3180.55"),
        },
        "confidence": 0.7,
    }
    result = _parse_pay_stub_json(json.dumps(payload))
    assert result is not None
    assert result.data.gross_pay.value is None  # bad value dropped
    assert result.data.gross_pay.source is not None  # but source kept
    assert result.data.gross_pay.source.snippet == "Gross ???"
    assert result.data.net_pay.value == Decimal("3180.55")  # others intact
    assert result.status == ExtractionStatus.PARTIAL  # data was lost


def test_all_null_core_is_failed_status() -> None:
    payload = {"typed_core": {"employer_name": _core(None), "gross_pay": _core(None)}}
    result = _parse_pay_stub_json(json.dumps(payload))
    assert result is not None
    assert result.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken", "[1,2,3]"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_pay_stub_json(raw) is None


def test_parse_clamps_confidence() -> None:
    payload = {"typed_core": {"gross_pay": _core("100")}, "confidence": 1.7}
    result = _parse_pay_stub_json(json.dumps(payload))
    assert result is not None
    assert result.confidence == 1.0


def test_flat_fallback_without_typed_core_wrapper() -> None:
    # Tolerant: core fields at the top level (no "typed_core" wrapper) still parse.
    payload = {"employer_name": _core("ACME Corp"), "confidence": 0.8}
    result = _parse_pay_stub_json(json.dumps(payload))
    assert result is not None
    assert result.data.employer_name.value == "ACME Corp"


def test_catch_all_skips_empty_sections_and_bad_fields() -> None:
    payload = {
        "typed_core": {"gross_pay": _core("100")},
        "additional_sections": [
            {"section": "Empty", "fields": []},  # dropped (no valid fields)
            {"section": "Bad", "fields": [{"value": "x"}, "not a dict"]},  # no label → dropped
            {"section": "Good", "fields": [{"label": "X", "value": "1"}]},
        ],
        "confidence": 0.5,
    }
    d = _parse_pay_stub_json(json.dumps(payload)).data  # type: ignore[union-attr]
    assert [s.section for s in d.additional_sections] == ["Good"]


# --------------------------------------------------------------------------- #
# extract_pay_stub
# --------------------------------------------------------------------------- #


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_pay_stub(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED
    assert result.data.gross_pay.value == Decimal("4200.00")
    assert len(result.data.additional_sections) == 2
    kwargs = mock.await_args.kwargs
    assert kwargs["model"] == pay_stub_module.settings.anthropic_model_extraction
    block = kwargs["messages"][0]["content"][0]
    assert block["type"] == "document"
    assert base64.standard_b64decode(block["source"]["data"]) == PDF_BYTES


async def test_extract_image_input_uses_image_block(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_pay_stub(PNG_BYTES, "image/png")
    assert result.status == ExtractionStatus.SUCCEEDED
    block = mock.await_args.kwargs["messages"][0]["content"][0]
    assert block["type"] == "image"
    assert block["source"]["media_type"] == "image/png"


async def test_extract_malformed_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text="I read a pay stub, gross was around 4k.")
    result = await extract_pay_stub(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == PayStubExtraction()  # all-null default
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
    assert mock.call_count == 0


@pytest.mark.parametrize("media_type", ["text/plain", "application/zip", "image/gif", ""])
async def test_extract_unsupported_media_type_skips_api(
    monkeypatch: pytest.MonkeyPatch, media_type: str
) -> None:
    mock = _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_pay_stub(PDF_BYTES, media_type)
    assert result.status == ExtractionStatus.FAILED
    assert mock.call_count == 0


# --------------------------------------------------------------------------- #
# PRIVACY: never log bytes/base64 / extracted values
# --------------------------------------------------------------------------- #


async def test_does_not_log_bytes_base64_or_values(monkeypatch: pytest.MonkeyPatch) -> None:
    pii_bytes = b"%PDF Jane Doe SSN 123-45-6789 employer SECRETCORP gross 9999.99"
    pii_b64 = base64.standard_b64encode(pii_bytes).decode("utf-8")
    payload = {
        "typed_core": {
            "employer_name": _core("SECRETCORP", snippet="SECRETCORP Inc"),
            "gross_pay": _core("9999.99", snippet="Gross 9,999.99"),
        },
        "additional_sections": [
            {"section": "Other", "fields": [{"label": "SSN", "value": "123-45-6789"}]}
        ],
        "confidence": 0.9,
        "reasoning": "clear",
    }
    _mock_complete(monkeypatch, text=json.dumps(payload))

    with structlog.testing.capture_logs() as logs:
        result = await extract_pay_stub(pii_bytes, "application/pdf")

    blob = " ".join(repr(e) for e in logs)
    assert "123-45-6789" not in blob  # raw byte content + catch-all value
    assert pii_b64 not in blob  # base64 payload
    assert "SECRETCORP" not in blob  # extracted core value
    assert "9999.99" not in blob
    done = [e for e in logs if e["event"] == "paystub_extraction_done"]
    assert len(done) == 1
    assert done[0]["status"] == ExtractionStatus.SUCCEEDED
    assert done[0]["core_fields_present"] == 2
    assert done[0]["catch_all_sections"] == 1
    assert result.data.employer_name.value == "SECRETCORP"  # returned to the caller


def test_failed_factory() -> None:
    result = PayStubExtractionResult.failed("because reasons")
    assert result.status == ExtractionStatus.FAILED
    assert result.confidence == 0.0
    assert result.data == PayStubExtraction()  # all typed fields default, no sections
    assert result.data.gross_pay.value is None
    assert result.data.additional_sections == []

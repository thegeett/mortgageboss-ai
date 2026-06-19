"""Tests for 1099 extraction (LP-60) — the AI wrapper is MOCKED.

Follows the W-2 test template (LP-39b). Focus: the typed core is coerced
(subtype/names/TINs→str, tax_year→int, income_amount→Decimal) with source; the
1099 **subtype variation** (NEC vs INT extract the right subtype + primary
amount); nothing is dropped (non-core → catch-all); honest nulls; graceful
failure; and the **recipient TIN is never logged** (but is available to the
caller, masked in display).

No real 1099 sample documents were available — these verify the
mechanism/shape, not extraction accuracy against real forms (validated as real
documents flow through; field set refined with Priya).
"""

import base64
import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import structlog
from app.ai.client import AIClientError
from app.ai.extraction import form_1099 as form_1099_module
from app.ai.extraction.form_1099 import (
    Form1099Extraction,
    Form1099ExtractionResult,
    _parse_1099_json,
    extract_1099,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy 1099 bytes"
PNG_BYTES = b"\x89PNG\r\n\x1a\n dummy image bytes"
RECIPIENT_TIN = "987-65-4321"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


NEC_PAYLOAD = {
    "typed_core": {
        "form_subtype": _core("NEC", snippet="Form 1099-NEC"),
        "payer_name": _core("Globex LLC", snippet="PAYER Globex LLC"),
        "payer_tin": _core("12-3456789", snippet="12-3456789"),
        "recipient_name": _core("Jane Doe", snippet="Jane Doe"),
        "recipient_tin": _core(RECIPIENT_TIN, snippet=f"RECIPIENT TIN {RECIPIENT_TIN}"),
        "tax_year": _core("2024", snippet="2024"),
        "income_amount": _core("$48,250.00", snippet="1 Nonemployee compensation 48,250.00"),
    },
    "additional_sections": [
        {
            "section": "Withholding",
            "fields": [{"label": "Federal income tax withheld", "value": "0.00", "page": 1}],
        }
    ],
    "confidence": 0.9,
    "reasoning": "Clear 1099-NEC.",
}
NEC_JSON = json.dumps(NEC_PAYLOAD)


def _mock_complete(
    monkeypatch: pytest.MonkeyPatch, *, text: str | None = None, exc: Exception | None = None
) -> AsyncMock:
    if exc is not None:
        mock = AsyncMock(side_effect=exc)
    else:
        mock = AsyncMock(
            return_value=SimpleNamespace(text=text, input_tokens=150, output_tokens=60, model="m")
        )
    monkeypatch.setattr(form_1099_module, "complete", mock)
    return mock


# --------------------------------------------------------------------------- #
# Parser: typed core + grouped catch-all + subtype handling
# --------------------------------------------------------------------------- #


def test_parse_full_shape() -> None:
    result = _parse_1099_json(NEC_JSON)
    assert result is not None
    assert result.status == ExtractionStatus.SUCCEEDED
    d = result.data
    assert d.form_subtype.value == "NEC"
    assert d.income_amount.value == Decimal("48250.00")  # "$48,250.00" coerced
    assert isinstance(d.tax_year.value, int) and d.tax_year.value == 2024
    assert d.recipient_tin.value == RECIPIENT_TIN
    assert [s.section for s in d.additional_sections] == ["Withholding"]


def test_source_location_present() -> None:
    d = _parse_1099_json(NEC_JSON).data  # type: ignore[union-attr]
    assert d.income_amount.source is not None
    assert d.income_amount.source.snippet == "1 Nonemployee compensation 48,250.00"


@pytest.mark.parametrize(
    ("subtype", "amount", "expected"),
    [
        ("NEC", "48250.00", Decimal("48250.00")),
        ("INT", "1320.55", Decimal("1320.55")),
        ("DIV", "900.00", Decimal("900.00")),
        ("R", "15000.00", Decimal("15000.00")),
    ],
)
def test_subtype_variation_extracts_right_amount(
    subtype: str, amount: str, expected: Decimal
) -> None:
    """A NEC vs an INT (etc.) extract the right subtype + primary amount."""
    payload = {
        "typed_core": {
            "form_subtype": _core(subtype),
            "income_amount": _core(amount),
        },
        "confidence": 0.9,
    }
    d = _parse_1099_json(json.dumps(payload)).data  # type: ignore[union-attr]
    assert d.form_subtype.value == subtype
    assert d.income_amount.value == expected


def test_nothing_dropped_non_core_lands_in_catch_all() -> None:
    payload = {
        "typed_core": {"form_subtype": _core("INT"), "income_amount": _core("100")},
        "additional_sections": [
            {"section": "State", "fields": [{"label": "State tax withheld", "value": "5.00"}]}
        ],
        "confidence": 0.7,
    }
    d = _parse_1099_json(json.dumps(payload)).data  # type: ignore[union-attr]
    labels = [f.label for s in d.additional_sections for f in s.fields]
    assert "State tax withheld" in labels


def test_missing_fields_are_null_not_fabricated() -> None:
    payload = {"typed_core": {"income_amount": _core("100")}}
    result = _parse_1099_json(json.dumps(payload))
    assert result is not None
    assert result.data.income_amount.value == Decimal("100")
    assert result.data.payer_name.value is None
    assert result.data.recipient_tin.value is None


def test_junk_amount_becomes_none_partial() -> None:
    payload = {
        "typed_core": {"form_subtype": _core("NEC"), "income_amount": _core("n/a")},
        "confidence": 0.6,
    }
    result = _parse_1099_json(json.dumps(payload))
    assert result is not None
    assert result.data.income_amount.value is None
    assert result.data.income_amount.source is not None  # source kept
    assert result.status == ExtractionStatus.PARTIAL


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"form_subtype": _core(None), "income_amount": _core(None)}}
    result = _parse_1099_json(json.dumps(payload))
    assert result is not None
    assert result.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken", "[1,2,3]"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_1099_json(raw) is None


# --------------------------------------------------------------------------- #
# extract_1099
# --------------------------------------------------------------------------- #


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = _mock_complete(monkeypatch, text=NEC_JSON)
    result = await extract_1099(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED
    assert result.data.form_subtype.value == "NEC"
    assert result.input_tokens == 150
    block = mock.await_args.kwargs["messages"][0]["content"][0]
    assert block["type"] == "document"
    assert base64.standard_b64decode(block["source"]["data"]) == PDF_BYTES


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_1099(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


async def test_extract_malformed_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text="I read a 1099 for some contractor income.")
    result = await extract_1099(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == Form1099Extraction()


@pytest.mark.parametrize("media_type", ["text/plain", "image/gif", ""])
async def test_extract_unsupported_skips_api(
    monkeypatch: pytest.MonkeyPatch, media_type: str
) -> None:
    mock = _mock_complete(monkeypatch, text=NEC_JSON)
    result = await extract_1099(PDF_BYTES, media_type)
    assert result.status == ExtractionStatus.FAILED
    assert mock.call_count == 0


def test_failed_factory() -> None:
    result = Form1099ExtractionResult.failed("because reasons")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == Form1099Extraction()


# --------------------------------------------------------------------------- #
# PRIVACY — recipient TIN never logged (but available to the caller)
# --------------------------------------------------------------------------- #


async def test_does_not_log_recipient_tin_or_values(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=NEC_JSON)
    with structlog.testing.capture_logs() as logs:
        result = await extract_1099(PDF_BYTES, "application/pdf")
    blob = " ".join(repr(e) for e in logs)
    assert RECIPIENT_TIN not in blob  # the recipient TIN/SSN must never be logged
    assert "Globex LLC" not in blob  # extracted payer value
    assert "48250" not in blob and "48,250" not in blob  # extracted amount
    done = [e for e in logs if e["event"] == "form_1099_extraction_done"]
    assert len(done) == 1
    assert done[0]["form_subtype"] == "NEC"  # subtype is a non-PII category, safe to log
    assert done[0]["core_fields_present"] == 7
    # The raw TIN is still available to the caller (tenant-scoped JSON), masked in display.
    assert result.data.recipient_tin.value == RECIPIENT_TIN

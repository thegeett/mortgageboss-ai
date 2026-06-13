"""Tests for W-2 extraction (LP-39b) — the AI wrapper is MOCKED.

W-2 reuses the LP-39a shape (typed core + grouped catch-all + per-field source)
with a *different* typed core (annual figures, the federal boxes 1-6, identity).
Focus: the typed core is coerced (tax_year→int, boxes→Decimal, names/ssn/ein→str)
with source; **nothing is dropped** (non-core → catch-all); honest nulls; graceful
failure; and — specifically — the **SSN value is never logged**.
"""

import base64
import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import structlog
from app.ai.client import AIClientError
from app.ai.extraction import w2 as w2_module
from app.ai.extraction.w2 import W2Extraction, W2ExtractionResult, _parse_w2_json, extract_w2
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy w2 bytes"
PNG_BYTES = b"\x89PNG\r\n\x1a\n dummy image bytes"
SSN = "123-45-6789"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "tax_year": _core("2024", snippet="2024"),
        "employee_name": _core("Jane Doe", snippet="Jane Doe"),
        "employee_ssn": _core(SSN, snippet=f"a {SSN}"),
        "employer_name": _core("ACME Corp", snippet="ACME Corp"),
        "employer_ein": _core("12-3456789", snippet="b 12-3456789"),
        "wages_tips_other_comp": _core("$62,000.00", snippet="1 Wages 62,000.00"),
        "federal_income_tax_withheld": _core("8400.00", snippet="2 Fed 8,400.00"),
        "social_security_wages": _core("62000.00", snippet="3 SS 62,000.00"),
        "social_security_tax_withheld": _core("3844.00", snippet="4 SS 3,844.00"),
        "medicare_wages": _core("62000.00", snippet="5 Med 62,000.00"),
        "medicare_tax_withheld": _core("899.00", snippet="6 Med 899.00"),
    },
    "additional_sections": [
        {
            "section": "State/Local",
            "fields": [
                {"label": "State", "value": "CA", "page": 1, "snippet": "15 CA"},
                {"label": "State wages", "value": "62000.00", "page": 1, "snippet": "16 62,000.00"},
            ],
        },
        {
            "section": "Box 12 Codes",
            "fields": [{"label": "D", "value": "5000.00", "page": 1, "snippet": "12a D 5,000.00"}],
        },
    ],
    "confidence": 0.92,
    "reasoning": "Standard W-2.",
}
FULL_JSON = json.dumps(FULL_PAYLOAD)


def _mock_complete(
    monkeypatch: pytest.MonkeyPatch, *, text: str | None = None, exc: Exception | None = None
) -> AsyncMock:
    if exc is not None:
        mock = AsyncMock(side_effect=exc)
    else:
        mock = AsyncMock(
            return_value=SimpleNamespace(text=text, input_tokens=180, output_tokens=70, model="m")
        )
    monkeypatch.setattr(w2_module, "complete", mock)
    return mock


# --------------------------------------------------------------------------- #
# Parser: typed core (coerced + source) + grouped catch-all
# --------------------------------------------------------------------------- #


def test_parse_full_shape() -> None:
    result = _parse_w2_json(FULL_JSON)
    assert result is not None
    assert result.status == ExtractionStatus.SUCCEEDED
    assert result.confidence == 0.92
    d = result.data
    # Typed values — note tax_year is an int, the boxes are Decimal.
    assert d.tax_year.value == 2024
    assert isinstance(d.tax_year.value, int)
    assert d.wages_tips_other_comp.value == Decimal("62000.00")  # "$62,000.00" coerced
    assert d.medicare_tax_withheld.value == Decimal("899.00")
    assert d.employer_ein.value == "12-3456789"
    assert d.employee_name.value == "Jane Doe"
    # Grouped catch-all preserved by section.
    assert [s.section for s in d.additional_sections] == ["State/Local", "Box 12 Codes"]


def test_source_location_on_core_and_catch_all() -> None:
    d = _parse_w2_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.wages_tips_other_comp.source is not None
    assert d.wages_tips_other_comp.source.page == 1
    assert d.wages_tips_other_comp.source.snippet == "1 Wages 62,000.00"
    box12 = d.additional_sections[1].fields[0]
    assert box12.source is not None and box12.source.snippet == "12a D 5,000.00"


def test_nothing_dropped_non_core_lands_in_catch_all() -> None:
    payload = {
        "typed_core": {"tax_year": _core("2024")},
        "additional_sections": [
            {"section": "Other", "fields": [{"label": "Control number", "value": "X-99"}]}
        ],
        "confidence": 0.7,
    }
    d = _parse_w2_json(json.dumps(payload)).data  # type: ignore[union-attr]
    assert d.tax_year.value == 2024
    labels = [f.label for s in d.additional_sections for f in s.fields]
    assert "Control number" in labels


def test_missing_core_fields_are_null_not_fabricated() -> None:
    payload = {"typed_core": {"wages_tips_other_comp": _core("62000")}}
    result = _parse_w2_json(json.dumps(payload))
    assert result is not None
    assert result.data.wages_tips_other_comp.value == Decimal("62000")
    assert result.data.tax_year.value is None
    assert result.data.employee_ssn.value is None
    assert result.status == ExtractionStatus.SUCCEEDED


def test_junk_core_field_becomes_none_keeps_source_partial() -> None:
    payload = {
        "typed_core": {
            "tax_year": _core("not a year", snippet="????"),  # uncoercible → None
            "wages_tips_other_comp": _core("62000"),
        },
        "confidence": 0.6,
    }
    result = _parse_w2_json(json.dumps(payload))
    assert result is not None
    assert result.data.tax_year.value is None
    assert result.data.tax_year.source is not None  # source kept
    assert result.data.wages_tips_other_comp.value == Decimal("62000")
    assert result.status == ExtractionStatus.PARTIAL


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"tax_year": _core(None), "wages_tips_other_comp": _core(None)}}
    result = _parse_w2_json(json.dumps(payload))
    assert result is not None
    assert result.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken", "[1,2,3]"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_w2_json(raw) is None


def test_parse_clamps_confidence() -> None:
    payload = {"typed_core": {"tax_year": _core("2024")}, "confidence": 1.7}
    result = _parse_w2_json(json.dumps(payload))
    assert result is not None
    assert result.confidence == 1.0


# --------------------------------------------------------------------------- #
# extract_w2
# --------------------------------------------------------------------------- #


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_w2(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED
    assert result.data.tax_year.value == 2024
    assert len(result.data.additional_sections) == 2
    kwargs = mock.await_args.kwargs
    assert kwargs["model"] == w2_module.settings.anthropic_model_extraction
    block = kwargs["messages"][0]["content"][0]
    assert block["type"] == "document"
    assert base64.standard_b64decode(block["source"]["data"]) == PDF_BYTES


async def test_extract_image_input(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = _mock_complete(monkeypatch, text=FULL_JSON)
    await extract_w2(PNG_BYTES, "image/png")
    block = mock.await_args.kwargs["messages"][0]["content"][0]
    assert block["type"] == "image"


async def test_extract_malformed_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text="I read a W-2, wages were about 62k.")
    result = await extract_w2(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == W2Extraction()


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_w2(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED
    assert "ai call failed" in (result.reasoning or "").lower()


async def test_extract_empty_skips_api(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_w2(b"", "application/pdf")
    assert result.status == ExtractionStatus.FAILED
    assert mock.call_count == 0


@pytest.mark.parametrize("media_type", ["text/plain", "image/gif", ""])
async def test_extract_unsupported_skips_api(
    monkeypatch: pytest.MonkeyPatch, media_type: str
) -> None:
    mock = _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_w2(PDF_BYTES, media_type)
    assert result.status == ExtractionStatus.FAILED
    assert mock.call_count == 0


# --------------------------------------------------------------------------- #
# PRIVACY — no bytes/base64/values logged; SPECIFICALLY no SSN
# --------------------------------------------------------------------------- #


async def test_does_not_log_values_or_ssn(monkeypatch: pytest.MonkeyPatch) -> None:
    pii_bytes = b"%PDF W-2 SECRETCORP wages 62000"
    pii_b64 = base64.standard_b64encode(pii_bytes).decode("utf-8")
    _mock_complete(monkeypatch, text=FULL_JSON)

    with structlog.testing.capture_logs() as logs:
        result = await extract_w2(pii_bytes, "application/pdf")

    blob = " ".join(repr(e) for e in logs)
    assert SSN not in blob  # the extracted SSN value must never be logged
    assert pii_b64 not in blob  # base64 payload
    assert "ACME Corp" not in blob  # extracted employer value
    assert "62000" not in blob  # extracted wage value
    done = [e for e in logs if e["event"] == "w2_extraction_done"]
    assert len(done) == 1
    assert done[0]["core_fields_present"] == 11
    assert done[0]["catch_all_sections"] == 2
    # The raw SSN is still available to the caller (tenant-scoped JSON), masked in display.
    assert result.data.employee_ssn.value == SSN


def test_failed_factory() -> None:
    result = W2ExtractionResult.failed("because reasons")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == W2Extraction()
    assert result.data.tax_year.value is None

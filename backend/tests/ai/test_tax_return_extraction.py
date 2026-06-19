"""Tests for tax return extraction (LP-64) — the AI wrapper is MOCKED.

A tax return is the hardest, most varied extractor: a NESTED bundle (1040 core +
a VARIABLE set of typed schedules + catch-all). The focus is therefore the nested
mechanism/shape: the 1040 core, **Schedule C ``net_profit`` (the self-employment
heart)**, the variable composition (present-or-null; repeatable Schedule Cs / E
properties / K-1s as lists), the catch-all for other schedules, the SSN never
logged, and graceful failure.

**Accuracy honesty (emphatic):** NO real sample returns were available, so these
verify the nested SHAPE — **not** extraction accuracy against real, multi-schedule
returns. A multi-schedule extractor tested only against constructed inputs is
especially unproven; real (synthetic/redacted) self-employed returns are needed to
validate accuracy, and the field set is refined with Priya.
"""

import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import structlog
from app.ai.client import AIClientError
from app.ai.extraction import tax_return as tr_module
from app.ai.extraction.tax_return import (
    TaxReturnExtraction,
    TaxReturnExtractionResult,
    _parse_tax_return_json,
    extract_tax_return,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy tax return bundle"
SSN_MASKED = "***-**-1234"


def _f(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    """A TypedField-shaped {value, page, snippet} entry."""
    return {"value": value, "page": page, "snippet": snippet}


# A self-employed return: two Schedule Cs, a Schedule E (one property), no K-1.
SELF_EMPLOYED_PAYLOAD = {
    "typed_core": {
        "tax_year": _f(2023, snippet="2023"),
        "filing_status": _f("married_filing_jointly"),
        "taxpayer_names": _f("Mahesh & Spouse"),
        "taxpayer_ssn_masked": _f(SSN_MASKED, snippet="SSN ***-**-1234"),
        "total_income": _f("$150,000.00"),
        "adjusted_gross_income": _f("142500.00", snippet="AGI 142,500"),
        "wages": _f("0.00"),
        "taxable_income": _f("118000.00"),
    },
    "schedule_c": [
        {
            "business_name": _f("Swad Mania LLC", page=3),
            "gross_receipts": _f("220000.00", page=3),
            "total_expenses": _f("131800.00", page=3),
            "net_profit": _f("$88,200.00", page=3, snippet="Net profit 88,200"),
        },
        {
            "business_name": _f("Chhotala Realty LLC", page=4),
            "net_profit": _f("45000.00", page=4),
        },
    ],
    "schedule_e": {
        "properties": [
            {"address": _f("10 Rental Rd"), "net_income": _f("12000.00")},
        ],
        "total_net_rental_income": _f("12000.00"),
        "depreciation": _f("3000.00"),
    },
    "k1s": [],
    "additional_sections": [
        {"section": "Schedule B", "fields": [{"label": "Interest income", "value": "320.00"}]}
    ],
    "confidence": 0.85,
    "reasoning": "Self-employed 1040 with two Schedule Cs.",
}
SELF_EMPLOYED_JSON = json.dumps(SELF_EMPLOYED_PAYLOAD)


def _mock_complete(
    monkeypatch: pytest.MonkeyPatch, *, text: str | None = None, exc: Exception | None = None
) -> AsyncMock:
    if exc is not None:
        mock = AsyncMock(side_effect=exc)
    else:
        mock = AsyncMock(
            return_value=SimpleNamespace(text=text, input_tokens=900, output_tokens=600, model="m")
        )
    monkeypatch.setattr(tr_module, "complete", mock)
    return mock


# --------------------------------------------------------------------------- #
# Nested shape + Schedule C (the self-employment heart)
# --------------------------------------------------------------------------- #


def test_parse_nested_shape_1040_core() -> None:
    result = _parse_tax_return_json(SELF_EMPLOYED_JSON)
    assert result is not None
    assert result.status == ExtractionStatus.SUCCEEDED
    d = result.data
    assert d.tax_year.value == 2023 and isinstance(d.tax_year.value, int)
    assert d.adjusted_gross_income.value == Decimal("142500.00")
    assert d.taxpayer_ssn_masked.value == SSN_MASKED


def test_schedule_c_net_profit_is_the_heart() -> None:
    """The KEY assertion — Schedule C net_profit (self-employment income) is captured."""
    d = _parse_tax_return_json(SELF_EMPLOYED_JSON).data  # type: ignore[union-attr]
    assert len(d.schedule_c) == 2  # MULTIPLE Schedule Cs → a list
    c0 = d.schedule_c[0]
    assert c0.business_name.value == "Swad Mania LLC"
    assert c0.net_profit.value == Decimal("88200.00")  # "$88,200.00" coerced
    assert c0.net_profit.source is not None and c0.net_profit.source.page == 3  # source on the row
    assert d.schedule_c[1].net_profit.value == Decimal("45000.00")


def test_schedule_e_properties_and_depreciation() -> None:
    d = _parse_tax_return_json(SELF_EMPLOYED_JSON).data  # type: ignore[union-attr]
    assert d.schedule_e is not None
    assert len(d.schedule_e.properties) == 1
    assert d.schedule_e.properties[0].address.value == "10 Rental Rd"
    assert d.schedule_e.total_net_rental_income.value == Decimal("12000.00")
    assert d.schedule_e.depreciation.value == Decimal("3000.00")  # added back in Phase 3


def test_other_schedules_in_catch_all() -> None:
    d = _parse_tax_return_json(SELF_EMPLOYED_JSON).data  # type: ignore[union-attr]
    assert [s.section for s in d.additional_sections] == ["Schedule B"]


# --------------------------------------------------------------------------- #
# Variable composition — present-or-null; repeatable; no hallucination
# --------------------------------------------------------------------------- #


def test_w2_employee_return_has_no_schedules() -> None:
    """A W-2 employee's return: schedules absent → empty list / null (not a crash)."""
    payload = {
        "typed_core": {
            "tax_year": _f(2023),
            "wages": _f("95000.00"),
            "adjusted_gross_income": _f("95000.00"),
        },
        "schedule_c": [],
        "schedule_e": None,
        "k1s": [],
        "confidence": 0.9,
    }
    d = _parse_tax_return_json(json.dumps(payload)).data  # type: ignore[union-attr]
    assert d.schedule_c == []
    assert d.schedule_e is None
    assert d.k1s == []
    assert d.wages.value == Decimal("95000.00")


def test_absent_schedule_keys_default_empty() -> None:
    """Schedules omitted entirely (not just empty) still default to empty/null."""
    payload = {"typed_core": {"tax_year": _f(2023), "total_income": _f("50000")}, "confidence": 0.8}
    d = _parse_tax_return_json(json.dumps(payload)).data  # type: ignore[union-attr]
    assert d.schedule_c == [] and d.schedule_e is None and d.k1s == []


def test_empty_schedule_rows_dropped_no_hallucination() -> None:
    """Fully-empty / non-dict schedule entries are dropped — no hallucinated schedules."""
    payload = {
        "typed_core": {"tax_year": _f(2023)},
        "schedule_c": [{"business_name": _f(None), "net_profit": _f(None)}, "junk", 7],
        "schedule_e": {"properties": [], "total_net_rental_income": _f(None)},
        "k1s": [{"entity_name": _f("Partner LLC"), "ordinary_income": _f("5000")}],
        "confidence": 0.7,
    }
    d = _parse_tax_return_json(json.dumps(payload)).data  # type: ignore[union-attr]
    assert d.schedule_c == []  # the empty C row dropped
    assert d.schedule_e is None  # an all-empty Schedule E → treated as absent
    assert len(d.k1s) == 1 and d.k1s[0].entity_name.value == "Partner LLC"


def test_all_null_is_failed() -> None:
    payload = {"typed_core": {"tax_year": _f(None)}, "schedule_c": [], "k1s": []}
    result = _parse_tax_return_json(json.dumps(payload))
    assert result is not None
    assert result.status == ExtractionStatus.FAILED


def test_schedule_only_return_is_succeeded() -> None:
    """A return with only schedule content (no 1040 core read) still counts."""
    payload = {"schedule_c": [{"net_profit": _f("70000", page=3)}], "confidence": 0.7}
    result = _parse_tax_return_json(json.dumps(payload))
    assert result is not None
    assert result.status == ExtractionStatus.SUCCEEDED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken", "[1,2,3]"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_tax_return_json(raw) is None


# --------------------------------------------------------------------------- #
# extract_tax_return — generous budget, graceful failure
# --------------------------------------------------------------------------- #


async def test_extract_success_uses_generous_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = _mock_complete(monkeypatch, text=SELF_EMPLOYED_JSON)
    result = await extract_tax_return(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED
    assert result.data.schedule_c[0].net_profit.value == Decimal("88200.00")
    # The multi-page bundle gets a generous token budget (more than single-form ones).
    assert mock.await_args.kwargs["max_tokens"] >= 16000


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_tax_return(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


async def test_extract_truncated_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A truncated/malformed multi-schedule response fails gracefully (never raises)."""
    _mock_complete(monkeypatch, text='{"typed_core": {"tax_year": {"value": 2023}, ')  # cut off
    result = await extract_tax_return(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


async def test_extract_empty_skips_api(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = _mock_complete(monkeypatch, text=SELF_EMPLOYED_JSON)
    result = await extract_tax_return(b"", "application/pdf")
    assert result.status == ExtractionStatus.FAILED
    assert mock.call_count == 0


# --------------------------------------------------------------------------- #
# PRIVACY — the SSN and return values are never logged
# --------------------------------------------------------------------------- #


async def test_does_not_log_ssn_or_values(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=SELF_EMPLOYED_JSON)
    with structlog.testing.capture_logs() as logs:
        result = await extract_tax_return(PDF_BYTES, "application/pdf")
    blob = " ".join(repr(e) for e in logs)
    assert SSN_MASKED not in blob and "1234" not in blob  # the SSN (even masked)
    assert "Swad Mania" not in blob and "88200" not in blob and "88,200" not in blob  # values
    assert "142500" not in blob  # AGI
    done = [e for e in logs if e["event"] == "tax_return_extraction_done"]
    assert len(done) == 1
    # Only COUNTS / presence flags are logged.
    assert done[0]["schedule_c_count"] == 2
    assert done[0]["schedule_e_present"] is True
    assert done[0]["schedule_e_properties"] == 1
    assert done[0]["k1_count"] == 0
    # The masked SSN is still available to the caller (tenant-scoped JSON).
    assert result.data.taxpayer_ssn_masked.value == SSN_MASKED


def test_failed_factory() -> None:
    result = TaxReturnExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == TaxReturnExtraction()

"""Tests for credit report extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.credit_report import (
    CreditReportExtraction,
    CreditReportExtractionResult,
    _parse_credit_report_json,
    extract_credit_report,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy credit_report"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "borrower_name": _core("SAMPLE"),
        "co_borrower_name": _core("SAMPLE"),
        "borrower_ssn": _core("SAMPLE"),
        "co_borrower_ssn": _core("SAMPLE"),
        "borrower_date_of_birth": _core("2024-01-15"),
        "borrower_current_address": _core("SAMPLE"),
        "borrower_former_address": _core("SAMPLE"),
        "report_date": _core("2024-01-15"),
        "score_date": _core("2024-01-15"),
        "report_provider": _core("SAMPLE"),
        "report_reference_number": _core("SAMPLE"),
        "credit_report_type": _core("SAMPLE"),
        "score_equifax": _core(2024),
        "score_experian": _core(2024),
        "score_transunion": _core(2024),
        "score_model": _core("SAMPLE"),
        "open_tradeline_count": _core(1),
        "total_tradeline_count": _core(1),
        "total_monthly_debt_payment": _core("1234.56"),
        "public_record_count": _core(1),
        "inquiry_count": _core(1),
        "security_freeze_or_fraud_alert": _core("SAMPLE"),
        "ssn_alert_status": _core("Requires Investigation"),
        "ssn_first_reported_date": _core("2017-09-24"),
        "address_usage_alert": _core("USED 006 TIMES IN THE LAST 30 DAYS"),
        "address_tenure": _core("016 MONTH(S)"),
        "credit_report_current_employer": _core("SAMPLE EMPLOYER"),
        "credit_report_previous_employer": _core("SAMPLE PRIOR"),
        "credit_report_occupation": _core("SAMPLE OCCUPATION"),
    },
    "additional_sections": [{"section": "Other", "fields": [{"label": "Note", "value": "x"}]}],
    "tradelines": [
        {
            "creditor_name": "SAMPLE",
            "account_type": "SAMPLE",
            "account_number_masked": "SAMPLE",
            "account_ownership": "SAMPLE",
            "date_opened": "2024-01-15",
            "balance": "1234.56",
            "credit_limit_or_high_credit": "1234.56",
            "monthly_payment": "1234.56",
            "past_due_amount": "1234.56",
            "account_status": "SAMPLE",
            "payment_status": "SAMPLE",
            "payment_history_24mo": "SAMPLE",
            "worst_delinquency": "SAMPLE",
            "is_disputed": "SAMPLE",
            "page": 1,
            "snippet": "s",
        }
    ],
    "public_records": [
        {
            "record_type": "SAMPLE",
            "filing_date": "2024-01-15",
            "discharge_or_satisfied_date": "2024-01-15",
            "status": "SAMPLE",
            "amount": "1234.56",
            "court_or_jurisdiction": "SAMPLE",
            "page": 1,
            "snippet": "s",
        }
    ],
    "inquiries": [
        {
            "inquiry_date": "2024-01-15",
            "creditor_name": "SAMPLE",
            "inquiry_type": "SAMPLE",
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
    d = _parse_credit_report_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.borrower_name.value == "SAMPLE"
    assert d.borrower_name.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"borrower_name": _core(None)}}
    parsed = _parse_credit_report_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_credit_report_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_credit_report(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_credit_report(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = CreditReportExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == CreditReportExtraction()


# --------------------------------------------------------------------------- #
# LP-445 — the count cross-check now measures LIST COMPLETENESS, not a population
# --------------------------------------------------------------------------- #
def _tradeline(name: str) -> dict:
    return {"creditor_name": name, "monthly_payment": "10.00", "page": 1, "snippet": "s"}


def _payload(*, n_tradelines: int, **counts: object) -> dict:
    """A minimal-but-valid credit-report payload with ``n_tradelines`` rows and any count overrides."""
    core = {"borrower_name": _core("SAMPLE")}
    for k, v in counts.items():
        core[k] = _core(v)
    return {
        "typed_core": core,
        "tradelines": [_tradeline(f"CREDITOR {i}") for i in range(n_tradelines)],
        "confidence": 0.9,
        "reasoning": "x",
    }


def test_open_tradeline_count_is_NOT_crosschecked() -> None:
    # The whole LP-445 fix: open_tradeline_count (9) counts OPEN tradelines; the list holds ALL (18).
    # A disagreement must NOT downgrade — it is not a completeness signal.
    parsed = _parse_credit_report_json(
        json.dumps(_payload(n_tradelines=18, open_tradeline_count=9))
    )
    assert parsed is not None
    assert parsed.data.open_tradeline_count.value == 9
    assert len(parsed.data.tradelines) == 18
    assert parsed.status == ExtractionStatus.SUCCEEDED  # the false PARTIAL is gone


def test_total_tradeline_count_fires_when_stated_and_mismatched() -> None:
    # total_tradeline_count DOES measure list length — a declared 18 with 17 captured rows means a
    # dropped row the API did not truncate → PARTIAL.
    parsed = _parse_credit_report_json(
        json.dumps(_payload(n_tradelines=17, total_tradeline_count=18))
    )
    assert parsed is not None
    assert parsed.status == ExtractionStatus.PARTIAL


def test_total_tradeline_count_passes_when_it_matches() -> None:
    parsed = _parse_credit_report_json(
        json.dumps(_payload(n_tradelines=18, total_tradeline_count=18))
    )
    assert parsed is not None
    assert parsed.status == ExtractionStatus.SUCCEEDED


def test_total_tradeline_count_null_does_not_fire() -> None:
    # The fail-closed shape: a report that states no all-in total (the common case) leaves the field
    # null, and absence is never a mismatch — a complete extraction stays SUCCEEDED.
    parsed = _parse_credit_report_json(json.dumps(_payload(n_tradelines=18)))
    assert parsed is not None
    assert parsed.data.total_tradeline_count.value is None
    assert parsed.status == ExtractionStatus.SUCCEEDED


def test_inquiry_count_is_now_crosschecked() -> None:
    # FIX 3: inquiry_count↔inquiries (an irregular plural the name heuristic missed) is now checked —
    # a declared 3 with 0 captured inquiry rows → PARTIAL, no longer a silent pass.
    payload = _payload(n_tradelines=1, inquiry_count=3)  # no inquiries list → 0 rows
    parsed = _parse_credit_report_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.PARTIAL


def test_promoted_fields_parse() -> None:
    d = _parse_credit_report_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.ssn_alert_status.value == "Requires Investigation"
    assert str(d.ssn_first_reported_date.value) == "2017-09-24"
    assert d.address_usage_alert.value == "USED 006 TIMES IN THE LAST 30 DAYS"
    assert d.address_tenure.value == "016 MONTH(S)"
    assert d.credit_report_current_employer.value == "SAMPLE EMPLOYER"
    assert d.credit_report_occupation.value == "SAMPLE OCCUPATION"


def test_unit_bearing_tenure_does_not_cause_partial() -> None:
    # LP-445 review: address_tenure is str, so the unit-bearing source ('016 MONTH(S)') coerces cleanly
    # instead of failing an int coercer (which would flag coercion_lost -> a false PARTIAL).
    payload = _payload(n_tradelines=2)
    payload["typed_core"]["address_tenure"] = _core("016 MONTH(S)")
    parsed = _parse_credit_report_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.data.address_tenure.value == "016 MONTH(S)"
    assert parsed.status == ExtractionStatus.SUCCEEDED  # no coercion loss, no false PARTIAL


def test_absent_promoted_fields_do_not_cause_partial() -> None:
    # A report with NO ID-risk / employer section: all 7 promoted fields null. Absence must not
    # downgrade — null is a legitimate state, not a coercion loss.
    parsed = _parse_credit_report_json(json.dumps(_payload(n_tradelines=2)))
    assert parsed is not None
    assert parsed.data.ssn_alert_status.value is None
    assert parsed.data.credit_report_current_employer.value is None
    assert parsed.status == ExtractionStatus.SUCCEEDED

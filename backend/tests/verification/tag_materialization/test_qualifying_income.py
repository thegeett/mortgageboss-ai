"""The `dti.qualifying_income_monthly` derived recipe (LP-366-A) — the loan's total monthly qualifying
income = the sum of the borrowers' MISMO STATED income lines (`borrower.<n>.income.<m>.monthly_amount`).

AS-1 reads this via a `loan_tag` operand (LP-366) instead of the gated DTI calc — a deposit-size question
needs income, NOT the housing expenses the DTI also weighs. It reads STATED 1003 income (`source='parsed'`),
NOT the AI `income.qualifying_monthly` tag (which degraded on the real run and whose averaging convention is
underspecified — LP-343 F2 is thereby OFF this path). Fail-closed: no income / an unparseable line → unknown,
NEVER 0.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import DocumentsSection, MismoSection, Snapshot, TagsSection
from app.verification.snapshot.pii import PiiField
from app.verification.tag_materialization.derived import (
    _UNKNOWN,
    _income_borrower_indices,
    _qualifying_income_monthly,
)


def _field(value: str) -> Field:
    return Field.present(value, source=FieldSource.EXTRACTED)


def _snapshot(mismo: Mapping[str, Field | PiiField] | None) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
        documents=DocumentsSection.present([]),
        mismo=MismoSection.present(dict(mismo)) if mismo is not None else MismoSection.missing(),
        tags=TagsSection.present({}),
    )


# The real LF-6T3N stated income (from LP-365's run): b1 has two lines, b2 one → $28,168.80.
_REAL: dict[str, Field] = {
    "borrower.1.income.1.monthly_amount": _field("3433.33"),
    "borrower.1.income.2.monthly_amount": _field("17500.02"),
    "borrower.2.income.1.monthly_amount": _field("7235.45"),
}


def test_sums_stated_income_across_borrowers_matching_the_real_file() -> None:
    value, reason = _qualifying_income_monthly(_snapshot(_REAL), "loan", None)
    assert value == "28168.80"  # exactly LP-365's reported number
    assert "28168.80" in reason


def test_enumerates_non_contiguous_borrower_indices() -> None:
    # A gap in borrower indices (1, 3 — no 2) must not silently truncate the sum.
    mismo = {
        "borrower.1.income.1.monthly_amount": _field("1000"),
        "borrower.3.income.1.monthly_amount": _field("2000"),
    }
    assert _income_borrower_indices(_snapshot(mismo)) == [1, 3]
    value, _ = _qualifying_income_monthly(_snapshot(mismo), "loan", None)
    assert value == "3000"


def test_abstains_when_mismo_absent() -> None:
    value, reason = _qualifying_income_monthly(_snapshot(None), "loan", None)
    assert value == _UNKNOWN
    assert "MISMO absent" in reason


def test_abstains_when_no_income_stated() -> None:
    # MISMO present but with no income lines → unknown, never 0 (absent ≠ zero income).
    value, _ = _qualifying_income_monthly(
        _snapshot({"loan.amount": _field("500000")}), "loan", None
    )
    assert value == _UNKNOWN


def test_abstains_when_an_income_line_is_unparseable() -> None:
    # A present-but-unparseable amount → abstain (an understated sum would mask a real deposit finding),
    # never a partial number.
    mismo = {
        "borrower.1.income.1.monthly_amount": _field("3000"),
        "borrower.1.income.2.monthly_amount": _field("N/A"),
    }
    value, _ = _qualifying_income_monthly(_snapshot(mismo), "loan", None)
    assert value == _UNKNOWN


def test_never_returns_zero_as_a_value() -> None:
    # The load-bearing invariant: no input state yields "0" (which would size AS-1's threshold from zero
    # and fire on every deposit). Absent/empty/unparseable all abstain.
    for mismo in (None, {}, {"borrower.1.income.1.monthly_amount": _field("bad")}):
        value, _ = _qualifying_income_monthly(_snapshot(mismo), "loan", None)
        assert value == _UNKNOWN and Decimal(0) != value

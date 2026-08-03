"""LP-453 (step D.2) — the tradelines list consumer: DETERMINISTIC numeric observations over the credit
report's `tradelines` list.

⚠️ The row vocabulary is OPEN-ENDED bureau text (account_type = AUTO/INST/REV/…, is_disputed = free-text incl.
non-disputes, payment_history_24mo = a variable-length 0/- string), so classifying mortgage/student/collection
or interpreting a dispute/late is a Priya/AI question (ADR-353), NOT this recipe. It emits ONLY pure aggregates:
a COUNT and a MONTHLY-PAYMENT TOTAL. Tags describe, rules judge — no threshold, no is_derogatory.

These pin: the count + payment-total computed from real-shaped rows; fail-closed (no tradelines → "unknown",
never a fabricated 0 — absent ≠ empty); a present 0 payment counts, an absent one does not; an unparseable
payment is skipped, never guessed; the loan-level aggregate spans multiple credit reports; the aggregate is
SCOPED to credit_report documents (a `tradelines` list on another doc type cannot pollute it); and the derived
recipe keys are registered (the validate_declarations guard).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    DocumentEntry,
    DocumentsSection,
    ListRow,
    MismoSection,
    Snapshot,
    TagsSection,
)
from app.verification.tag_materialization.declarations import load_declarations
from app.verification.tag_materialization.derived import KNOWN_RECIPES
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio

_LOAN = "loan"


def _row(**fields: str) -> ListRow:
    return ListRow(
        fields={k: Field.present(v, source=FieldSource.EXTRACTED) for k, v in fields.items()}
    )


def _snapshot(*credit_reports: list[ListRow]) -> Snapshot:
    """A snapshot whose credit_report document(s) carry the given tradeline rows (one list per report)."""
    docs = [
        DocumentEntry(
            content_id=f"cr{i}",
            document_type="credit_report",
            belongs_to=None,
            fields={},
            lists={"tradelines": tuple(rows)} if rows is not None else {},
        )
        for i, rows in enumerate(credit_reports)
    ]
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
        documents=DocumentsSection.present(docs),
        mismo=MismoSection.present({}),
        tags=TagsSection.present({}),
    )


async def _tags(*credit_reports: list[ListRow]) -> tuple[object | None, object | None]:
    mat = await materialize_tags(
        _snapshot(*credit_reports), only_groups=frozenset()
    )  # parsed+derived, NO AI
    loan = mat.tags.by_subject.get(_LOAN, {})
    c = loan.get("credit.tradeline_count")
    p = loan.get("credit.tradeline_monthly_payment_total")
    return (c.value if c else None, p.value if p else None)


# --------------------------------------------------------------------------- #
# The computation, on real-shaped rows (AUTO/INST/REV codes, I1/R1 statuses — the D3 vocabulary)
# --------------------------------------------------------------------------- #
async def test_count_and_payment_total_over_real_shaped_rows() -> None:
    rows = [
        _row(account_type="AUTO", account_status="AS AGREED", monthly_payment="502"),
        _row(account_type="INST", account_status="AS AGREED", monthly_payment="386"),
        _row(account_type="REV", account_status="PAID", monthly_payment="0"),  # paid-off: present 0
        _row(account_type="REV", account_status="AS AGREED", monthly_payment="269"),
    ]
    count, total = await _tags(rows)
    assert count == "4"  # numeric STRING (the derived numeric convention — matches stmt.nsf_count)
    assert str(total) == "1157"  # 502 + 386 + 0 + 269 — a present 0 contributes 0 honestly


async def test_loan_level_aggregate_spans_multiple_reports() -> None:
    # A file with two credit reports (one empty, one with rows) aggregates loan-wide — the LF-96SV shape.
    count, total = await _tags(
        [],  # an empty report contributes nothing
        [
            _row(account_type="AUTO", monthly_payment="100"),
            _row(account_type="REV", monthly_payment="50"),
        ],
    )
    assert count == "2" and str(total) == "150"


async def test_aggregate_is_scoped_to_credit_report_documents() -> None:
    # LP-453 review: a list-name is not a unique key. A NON-credit_report document that also carries a
    # `tradelines` list must NOT pollute the credit aggregate — the recipe filters by document_type.
    other = DocumentEntry(
        content_id="not-a-credit-report",
        document_type="bank_statement",
        belongs_to=None,
        fields={},
        lists={"tradelines": (_row(account_type="AUTO", monthly_payment="9999"),)},
    )
    credit = DocumentEntry(
        content_id="cr0",
        document_type="credit_report",
        belongs_to=None,
        fields={},
        lists={"tradelines": (_row(account_type="REV", monthly_payment="100"),)},
    )
    snap = Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
        documents=DocumentsSection.present([other, credit]),
        mismo=MismoSection.present({}),
        tags=TagsSection.present({}),
    )
    mat = await materialize_tags(snap, only_groups=frozenset())
    loan = mat.tags.by_subject.get(_LOAN, {})
    assert (
        loan["credit.tradeline_count"].value == "1"
    )  # only the credit_report row, not the bank statement
    assert loan["credit.tradeline_monthly_payment_total"].value == "100"  # 9999 excluded


# --------------------------------------------------------------------------- #
# Fail-closed — abstain to "unknown" (the gate catches it), NEVER a fabricated 0 (absent ≠ empty)
# --------------------------------------------------------------------------- #
async def test_no_tradelines_abstains_to_unknown_not_zero() -> None:
    # No credit report with tradelines at all → BOTH tags abstain to "unknown" (a rule couldnt_checks) —
    # the derived-recipe fail-closed convention. The point: NEVER 0.
    count, total = await _tags()  # no documents
    assert count == "unknown" and total == "unknown"
    assert count != 0 and total != 0  # never a fabricated zero


async def test_credit_report_without_a_tradelines_list_abstains() -> None:
    # A credit_report present but with NO tradelines list captured → "unknown", not zero (absent ≠ empty).
    count, total = await _tags(None)  # type: ignore[arg-type]  # a report with no tradelines list
    assert count == "unknown" and total == "unknown"


async def test_rows_present_but_no_payment_figure_abstains_payment_not_zero() -> None:
    # Rows exist but none carry a monthly_payment → the COUNT is real, but the payment total abstains to
    # "unknown", never a fabricated 0 — fail-closed on missing payment data.
    rows = [_row(account_type="AUTO"), _row(account_type="REV")]  # no monthly_payment field
    count, total = await _tags(rows)
    assert count == "2"
    assert total == "unknown" and total != 0


async def test_unparseable_payment_is_skipped_never_guessed() -> None:
    rows = [_row(monthly_payment="502"), _row(monthly_payment="n/a"), _row(monthly_payment="200")]
    count, total = await _tags(rows)
    assert count == "3"  # every row is still counted
    assert str(total) == "702"  # the unparseable "n/a" is skipped, not guessed


# --------------------------------------------------------------------------- #
# Wiring — the recipes are registered and declared (the validate_declarations guard)
# --------------------------------------------------------------------------- #
def test_recipes_are_registered_and_declared() -> None:
    assert "credit_tradeline_count" in KNOWN_RECIPES
    assert "credit_tradeline_monthly_payment_total" in KNOWN_RECIPES
    decls = load_declarations()
    for tag, recipe in (
        ("credit.tradeline_count", "credit_tradeline_count"),
        ("credit.tradeline_monthly_payment_total", "credit_tradeline_monthly_payment_total"),
    ):
        assert decls[tag].mode.value == "derived"
        assert decls[tag].subject == "loan"
        assert decls[tag].data == recipe

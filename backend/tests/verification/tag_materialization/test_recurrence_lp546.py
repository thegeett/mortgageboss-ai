"""LP-546 — `txn.is_recurring`, declared since the vocabulary was written and produced by nothing.

`activation_bars` records why FR-5 was never built: *"FR-5's declared 'pattern across statements' is
unanswerable from a context that shows one transaction."* That is true of an AI group — the transaction
context builder sends ONE transaction — and simply not true of a deterministic producer, which receives
the whole snapshot.

SO IT NEEDS NO MODEL. Whether the same payee appears in two different months is a COUNT: decidable
from the text, identical on every run, no calibration round, no per-transaction call. The JUDGMENT that
count feeds — does a recurring debit to an undisclosed party imply an obligation — stays with the rule,
where an expert can weigh it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.services.tag_correlation import produce_recurrence_tags
from app.verification.snapshot.model import (
    DocumentEntry,
    DocumentsSection,
    Field,
    Snapshot,
    TagsSection,
    TransactionRecord,
)
from app.verification.tag_materialization.derived import _payee_key


def _txn(content_id: str, description: str, date: str) -> TransactionRecord:
    return TransactionRecord(
        content_id=content_id,
        date=Field(value=date, source="extracted"),
        amount=Field(value="3286.21", source="extracted"),
        description=Field(value=description, source="extracted"),
        direction=Field(value="debit", source="derived"),
    )


def _snapshot(*transactions: TransactionRecord) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 8, 18, tzinfo=UTC),
        documents=DocumentsSection(
            entries=[
                DocumentEntry(
                    content_id="bs",
                    document_type="bank_statement",
                    transactions=tuple(transactions),
                )
            ]
        ),
        tags=TagsSection.present({}),
    )


def _value(snapshot: Snapshot, content_id: str) -> str:
    return str(snapshot.tags.by_subject[content_id]["txn.is_recurring"].value)


# --------------------------------------------------------------------------------------------- #
# THE NORMALISATION, WHERE THE REAL DATA BITES
# --------------------------------------------------------------------------------------------- #
def test_the_redaction_marker_does_not_split_one_obligation_into_two() -> None:
    """CAUGHT ON REAL DESCRIPTIONS, and it is not cosmetic. A 9+-digit identifier is replaced with
    "[REDACTED-ID]" at rest, so ONE occurrence of a monthly mortgage payment can carry the marker while
    the next carries a short reference the redactor left alone. Stripping digits alone left

        "UNITEDWHOLESALE LOAN PAYMT REDACTED ID"   vs   "UNITEDWHOLESALE LOAN PAYMT"

    — the same payment, in two groups, recurring in neither. Exactly the silent under-report this tag
    exists to prevent."""
    assert _payee_key("UNITEDWHOLESALE LOAN PAYMT 1234 [REDACTED-ID]") == _payee_key(
        "UNITEDWHOLESALE LOAN PAYMT 5678"
    )


def test_different_payees_do_not_collapse_together() -> None:
    """The normalisation must not be so aggressive that two obligations read as one."""
    assert _payee_key("CITI AUTOPAY PAYMENT") != _payee_key("DISCOVER E-PAYMENT")


# --------------------------------------------------------------------------------------------- #
# MONTHS, NOT OCCURRENCES
# --------------------------------------------------------------------------------------------- #
def test_the_same_payee_in_two_months_is_recurring() -> None:
    snapshot = produce_recurrence_tags(
        _snapshot(
            _txn("t1", "UNITEDWHOLESALE LOAN PAYMT # [REDACTED-ID]", "2025-02-03"),
            _txn("t2", "UNITEDWHOLESALE LOAN PAYMT # 7781", "2025-03-03"),
        )
    )

    assert _value(snapshot, "t1") == "yes"
    assert _value(snapshot, "t2") == "yes"


def test_two_charges_in_ONE_month_are_not_recurring() -> None:
    """MONTHS, NOT OCCURRENCES, DELIBERATELY. Two charges from the same merchant three days apart are
    a shopping habit; the same payee in two different months is the shape a monthly obligation makes,
    which is the only shape FR-5 asks about. Counting occurrences would let one busy month masquerade as
    a pattern — and on a file carrying one or two statements, that is the common case."""
    snapshot = produce_recurrence_tags(
        _snapshot(
            _txn("t1", "STARBUCKS STORE 123", "2025-02-03"),
            _txn("t2", "STARBUCKS STORE 456", "2025-02-06"),
        )
    )

    assert _value(snapshot, "t1") == "no"


@pytest.mark.parametrize(
    ("description", "date"),
    [("", "2025-02-03"), ("UNITEDWHOLESALE LOAN PAYMT", ""), ("12345 6789", "2025-02-03")],
)
def test_an_unreadable_payee_or_date_abstains_rather_than_answering_no(
    description: str, date: str
) -> None:
    """§8: absent is not "no". A payee we cannot name cannot be matched against one we can, and
    answering "no" would assert that an obligation does NOT recur on the strength of a missing field."""
    snapshot = produce_recurrence_tags(_snapshot(_txn("t1", description, date)))

    assert _value(snapshot, "t1") == "unknown"


def test_an_absent_tags_layer_stays_absent() -> None:
    """Stage A never ran, so there is no tags layer to extend — never fabricate one."""
    snapshot = _snapshot(_txn("t1", "X", "2025-02-03")).model_copy(
        update={"tags": TagsSection(absent=True, reason="stage A did not run")}
    )

    assert produce_recurrence_tags(snapshot).tags.absent

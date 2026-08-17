"""LP-519 — the split-deposit aggregate, and AS-13 which reads it.

THE GAP THIS CLOSES. LP-518 gave AS-12 a per-deposit materiality floor, which removed the noise and
opened a hole: a $20,000 gift split into five $4,000 transfers is five sub-threshold deposits and
produces ZERO findings. A `per_deposit` rule cannot see that — the judgment context carries one
transaction, the same wall LP-498 recorded for FR-5. So the pattern is found in a LOAN-subject derived
aggregate, where every transaction is visible at once.

WHY GROUP BY AMOUNT AND NOT BY THE FLOOR. The obvious shape — "sum the deposits AS-12's floor scoped
out" — is not buildable: a recipe receives only the snapshot, materialises BEFORE any rule runs, and
cannot read a spec's `reference_values`, so it has no way to know what floor AS-12 applied.
Reimplementing the floor in Python would put a threshold outside the spec and leave two copies to drift.
A split shows up as the same amount more than once, which needs neither a floor nor a counterparty.

⚠️ AS-13 IS INERT. Its bar is `calibratable-now` with `validated: false`, so the eligibility gate
refuses it and it is not in `ACTIVE_RULE_IDS`. Same-amount grouping is a heuristic that has never run
against a real snapshot; activating it would assert a sign-off on unobserved behaviour, which is how
LP-516 shipped a gate that did nothing on a real file. These tests are the constructed evidence; the
activation waits on a real run.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    DocumentEntry,
    DocumentsSection,
    Snapshot,
    TagsSection,
    TransactionRecord,
)
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.tag_materialization.derived import _stmt_repeated_money_in_max_total

_TAG = "stmt.repeated_money_in_max_total"


def _tag(value: str) -> Tag:
    return Tag(
        value=value,
        confidence=0.9,
        reasoning=f"fixture: {value}",
        source_facts=("raw",),
        produced_by=TagProducedBy.AI,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def _txn(
    amount: str | None,
    *,
    direction: str = "in",
    category: str = "transfer_third_party_in",
    day: int | None = 1,
    month: int = 3,
):
    """One tagged transaction. `day`/`month` place it in 2026 — the CADENCE matters now, so a fixture
    that means "a split" has to space its deposits inside the window and one that means "recurring
    income" has to space them a month apart. `day=None` omits the date tag (the abstain case)."""
    tags = {"txn.is_money_in": _tag(direction), "txn.apparent_category": _tag(category)}
    if amount is not None:
        tags["txn.amount"] = _tag(amount)
    if day is not None:
        tags["txn.date"] = _tag(f"2026-{month:02d}-{day:02d}")
    return tags


def _split(amount: str, count: int, *, category: str = "transfer_third_party_in", step: int = 2):
    """`count` deposits of one amount, `step` days apart — a CLUSTER, i.e. what a split looks like.
    Distinct dates also keep them distinct deposits: same amount + same date + same description is one
    deposit seen twice, which the aggregate deduplicates."""
    return [_txn(amount, category=category, day=1 + i * step) for i in range(count)]


def _monthly(amount: str, count: int, *, category: str = "transfer_third_party_in"):
    """`count` deposits of one amount, one per month — RECURRING INCOME, not a split."""
    return [_txn(amount, category=category, day=5, month=3 + i) for i in range(count)]


def _snapshot(*transactions, loan: dict[str, Tag] | None = None) -> Snapshot:
    subjects = {f"t{i}": tags for i, tags in enumerate(transactions)}
    subjects["loan"] = loan or {}
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 8, 17, tzinfo=UTC),
        tags=TagsSection.present(subjects),
    )


def _aggregate(*transactions) -> tuple[object, str]:
    return _stmt_repeated_money_in_max_total(_snapshot(*transactions), "loan", None)


# ------------------------------------------------------------------------------------------------ #
# THE AGGREGATE
# ------------------------------------------------------------------------------------------------ #
def test_a_split_deposit_is_summed() -> None:
    """The headline: five $4,000 transfers over nine days, each individually below any sensible floor,
    total $20,000."""
    value, reasoning = _aggregate(*_split("4000.00", 5))

    assert value == "20000.00"
    assert "5 money-in deposits of 4000.00" in reasoning


def test_the_largest_group_wins_not_the_most_frequent() -> None:
    """Three $100s ($300) vs two $5,000s ($10,000) — the aggregate reports SIZE, so the pair wins.

    A count-based "most repeated" would report the $100 group and miss the $10,000 entirely."""
    value, _ = _aggregate(*_split("100.00", 3), *_split("5000.00", 2))

    assert value == "10000.00"


def test_a_lone_deposit_is_not_a_repeat() -> None:
    """A group of one is not a pattern. Without this every file reports its largest single deposit and
    the rule becomes a worse duplicate of AS-1."""
    value, reasoning = _aggregate(
        _txn("9000.00", day=1), _txn("4000.00", day=3), _txn("100.00", day=5)
    )

    assert value == "0"
    assert "no non-exempt money-in amount repeats within 14 days" in reasoning


def test_payroll_is_excluded_or_every_w2_borrower_fires() -> None:
    """⚠️ NOT optional. A salary paid twice a month IS a repeated same-amount deposit, so counting
    payroll would fire this on essentially every W-2 file and say nothing. Mirrors AS-12's
    `exempt_when`, and for the guideline reason: payroll is readily identifiable on the statement."""
    value, _ = _aggregate(*_split("3300.00", 4, category="payroll"))

    assert value == "0"


def test_interest_postings_are_excluded_too() -> None:
    value, _ = _aggregate(*_split("0.03", 6, category="interest"))

    assert value == "0"


def test_an_own_account_transfer_is_excluded() -> None:
    """A standing savings-to-checking transfer of one round figure is the most common benign repeated
    credit there is, and `transfer_own` is Stage A's own label for it. Counting it produces a
    fraud-adjacent finding on a borrower moving their own money — the false positive the bar's `fp_fn`
    text names first. AS-12 can leave this unexempted because a model still judges each deposit; this
    rule asserts the pattern deterministically, so it cannot."""
    value, _ = _aggregate(*_monthly("2500.00", 3, category="transfer_own"))

    assert value == "0"

    # And clustered, in case a borrower sweeps an account over a few days.
    assert _aggregate(*_split("2500.00", 3, category="transfer_own"))[0] == "0"


def test_money_out_never_counts() -> None:
    """Repeated equal DEBITS are a recurring-liability signal (FR-5's question), not a deposit split.
    Counting them here would answer the wrong question with the right-looking number."""
    value, _ = _aggregate(*_split("450.00", 4))

    assert value == "1800.00"  # as credits they ARE a cluster — the direction is what excludes them
    assert _aggregate(*[_txn("450.00", direction="out", day=1 + i) for i in range(4)])[0] == "0"


# ------------------------------------------------------------------------------------------------ #
# "SAME AMOUNT" IS NOT "ARRANGED" — the three ways amount equality is a false signal
# ------------------------------------------------------------------------------------------------ #
def test_recurring_monthly_income_is_not_a_split() -> None:
    """Six $1,800 credits, one a month — rent, child support, a second job paid outside payroll. Summed,
    they are $10,800 and clear a 50% floor on any income under $21.6k/mo, so without a cadence test this
    rule accuses an income stream documented elsewhere in the file of being borrowed funds. A split is
    CLUSTERED; recurring income arrives a month apart."""
    value, reasoning = _aggregate(*_monthly("1800.00", 6))

    assert value == "0"
    assert "within 14 days" in reasoning


def test_a_cluster_inside_the_window_still_counts_when_it_spans_weeks() -> None:
    """The window is a CHAIN, not a fixed span: a split that dribbles out every 10 days over a month is
    still one cluster. A fixed 14-day span would see three separate pairs and report a third of it."""
    value, _ = _aggregate(*[_txn("3000.00", day=1 + i * 10, month=3) for i in range(2)])

    assert value == "6000.00"


def test_the_same_deposit_in_two_uploaded_statements_is_counted_once() -> None:
    """Two uploads of one statement are two DOCUMENTS with two content_ids, and `assign_content_ids`
    deliberately gives byte-identical content distinct ids, so nothing upstream collapses them. Without
    deduplication a single $9,000 deposit present in both copies becomes a 2-member group totalling
    $18,000 — duplication converted into a new claim about a pattern. AS-1/AS-12 are immune (they would
    emit the same per-deposit finding twice); this rule is not."""
    one_deposit = _txn("9000.00", day=4)
    value, _ = _aggregate(one_deposit, dict(one_deposit))

    assert value == "0"


def test_two_distinct_deposits_of_one_amount_on_different_days_still_count() -> None:
    """The other side of deduplication: it must key on the deposit, not the amount, or a real split
    (same amount, different days) would be collapsed to nothing."""
    value, _ = _aggregate(_txn("9000.00", day=4), _txn("9000.00", day=6))

    assert value == "18000.00"


def _snapshot_with_documents(*rows: tuple[str, str, str, str]) -> Snapshot:
    """A snapshot carrying REAL transaction records, so the deduplication key sees descriptions.

    The tags-only fixtures above leave the description empty and so deduplicate on amount and date
    alone; this is the production path, where two deposits that agree on amount and date are still
    distinct if the statement describes them differently.
    """
    records = tuple(
        TransactionRecord(
            content_id=cid,
            date=Field.present(day, source=FieldSource.EXTRACTED),
            amount=Field.present(amount, source=FieldSource.EXTRACTED),
            direction=Field.present("credit", source=FieldSource.EXTRACTED),
            description=Field.present(description, source=FieldSource.EXTRACTED),
        )
        for cid, day, amount, description in rows
    )
    doc = DocumentEntry(
        content_id="doc1", document_type="bank_statement", fields={}, transactions=records
    )
    subjects: dict[str, dict[str, Tag]] = {
        cid: {
            "txn.is_money_in": _tag("in"),
            "txn.apparent_category": _tag("transfer_third_party_in"),
            "txn.amount": _tag(amount),
            "txn.date": _tag(day),
        }
        for cid, day, amount, _description in rows
    }
    subjects["loan"] = {}
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 8, 17, tzinfo=UTC),
        documents=DocumentsSection.present([doc]),
        tags=TagsSection.present(subjects),
    )


def test_the_description_keeps_two_same_day_deposits_distinct() -> None:
    """Deduplication must not swallow a real repeat that happens to land on one day. Two $5,000 credits
    on 2026-03-04 from different senders are two deposits; the statement says so."""
    snapshot = _snapshot_with_documents(
        ("t0", "2026-03-04", "5000.00", "ZELLE FROM A PATEL"),
        ("t1", "2026-03-04", "5000.00", "ZELLE FROM R KUMAR"),
    )
    value, _ = _stmt_repeated_money_in_max_total(snapshot, "loan", None)

    assert value == "10000.00"


def test_one_deposit_duplicated_across_two_statement_uploads_is_counted_once() -> None:
    """The same line, same description, from two copies of one statement — one deposit, not a pattern."""
    snapshot = _snapshot_with_documents(
        ("t0", "2026-03-04", "9000.00", "WIRE FROM FIRST TRUST"),
        ("t1", "2026-03-04", "9000.00", "WIRE FROM FIRST TRUST"),
    )
    value, _ = _stmt_repeated_money_in_max_total(snapshot, "loan", None)

    assert value == "0"


# ------------------------------------------------------------------------------------------------ #
# ABSTENTION — every branch, because a wrong 0 reads as "we looked and there is no pattern"
# ------------------------------------------------------------------------------------------------ #
def test_no_deposit_detection_at_all_abstains_rather_than_reporting_zero() -> None:
    """⚠️ absent != none found. With `txn.is_money_in` on no subject, detection never ran; a 0 here
    would false-green the rule on every file whose Stage-A tags failed to materialize. The
    `_stmt_nsf_count` discipline, copied deliberately."""
    value, reasoning = _stmt_repeated_money_in_max_total(_snapshot(), "loan", None)

    assert value == "unknown"
    assert "deposit detection has not run" in reasoning


def test_an_unreadable_direction_abstains_when_its_amount_could_matter() -> None:
    value, _ = _aggregate(_txn("4000.00", day=1), _txn("4000.00", direction="unknown", day=3))

    assert value == "unknown"


def test_an_undetermined_category_abstains_when_its_amount_could_matter() -> None:
    """An unknown category cannot be told apart from an exempt payroll credit. Counting it could
    over-report; skipping it could under-report. Neither is assertable, so the tag abstains."""
    value, _ = _aggregate(_txn("4000.00", day=1), _txn("4000.00", category="unknown", day=3))

    assert value == "unknown"


def test_an_undetermined_deposit_whose_amount_appears_nowhere_else_does_not_abstain() -> None:
    """THE BOUND. Stage A is told to return `unknown` liberally and a real file carries dozens of
    transactions, so an all-or-nothing abstention made the tag LESS likely to be concrete the larger the
    file got — useless on exactly the files this rule is for. An unreadable deposit whose amount matches
    nothing cannot form or extend a repeat, so its category cannot change the answer and abstaining on
    it is theatre."""
    value, _ = _aggregate(*_split("4000.00", 2), _txn("777.00", category="unknown", day=9))

    assert value == "8000.00"


def test_two_undetermined_deposits_of_one_amount_still_abstain() -> None:
    """They match each other, so together they could BE the repeat."""
    value, _ = _aggregate(
        _txn("4000.00", category="unknown", day=1), _txn("4000.00", category="unknown", day=3)
    )

    assert value == "unknown"


def test_a_missing_amount_abstains_because_the_total_would_be_a_lower_bound() -> None:
    value, _ = _aggregate(_txn("4000.00"), _txn(None))

    assert value == "unknown"


def test_a_missing_date_abstains_because_the_deposit_cannot_be_placed_in_a_cluster() -> None:
    """Dates are parsed rather than perceived, so this is rare — but without one, a deposit can be
    neither included in a cluster nor ruled out of it."""
    value, reasoning = _aggregate(*_split("4000.00", 2), _txn("4000.00", day=None))

    assert value == "unknown"
    assert "amount or date" in reasoning


def test_absent_tags_abstain() -> None:
    snapshot = Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 8, 17, tzinfo=UTC),
        tags=TagsSection.missing(),
    )
    value, _ = _stmt_repeated_money_in_max_total(snapshot, "loan", None)

    assert value == "unknown"


# ------------------------------------------------------------------------------------------------ #
# AS-13 IS GONE — the tag is not
# ------------------------------------------------------------------------------------------------ #
def test_as13_is_not_in_the_catalog() -> None:
    """⚠️ AS-13 was WITHDRAWN, not held. As an inert rule whose input resolved on every file it exposed
    two latent defects in the pending-checks path and broke staging twice: the database could not store
    `pending_automation` (fixed, LP-521), and `reconcile_evaluation_findings` loads prior findings for
    ACTIVE rules only — so an inert rule's row is invisible on the SECOND run and collides on the
    uniqueness index.

    The tag below stays because it is harmless and correct; the RULE comes back once the reconciler is
    fixed with its own tests. This asserts the withdrawal so a half-reinstatement cannot happen quietly.
    """
    from app.verification.rules.kinds import kind_for
    from app.verification.rules.specs import RuleSpecNotFound

    assert "AS-13" not in ACTIVE_RULE_IDS
    assert kind_for("AS-13") is None
    with pytest.raises(RuleSpecNotFound):
        load_rule_spec("AS-13")


def test_the_aggregate_tag_survives_the_withdrawal() -> None:
    """The tag is declared and produced whether or not a rule reads it — it materializes on every run
    and nothing consumes it today. That is deliberate: it is the foundation AS-13 returns on."""
    from app.verification.tag_materialization.declarations import load_declarations

    assert _TAG in load_declarations()

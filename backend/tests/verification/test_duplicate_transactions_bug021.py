"""bug-021 — one statement uploaded twice, and every deposit on it judged twice.

LF-XMB2 shows one $19,039.08 deposit as two AS-1 findings and two AS-12 findings. Not two overlapping
statements: the same statement uploaded twice — both files 226,597 bytes, PNC Bank, account
XX-XXXX-1943, period 2026-02-06 to 2026-03-05, extracted once as 20 rows and once as 21.

A transaction's content id is scoped to its document by construction, so the second upload mints a
second id for every line and the reconciler (keyed on rule_id + subject_key) makes that two findings
for ever. This collapses them at emission, where the surviving row can still name BOTH uploads.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from app.services.verification_run import _collapse_duplicate_transactions
from app.verification.rule_engine.result import LoadBearingTag, RuleEvaluation, Verdict
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    DocumentEntry,
    DocumentsSection,
    Snapshot,
    TagsSection,
    TransactionRecord,
)


def _f(value: str) -> Field:
    return Field.present(value, source=FieldSource.EXTRACTED)


def _txn(
    content_id: str,
    *,
    amount: str = "19039.08",
    date: str = "2026-02-25",
    description: str = "Instpmntin Intuit Payments Inc.",
) -> TransactionRecord:
    # `description` is a parameter because the identity includes it, and the two real uploads differ in
    # exactly that field on four lines (bug-021 review). TransactionRecord is a pydantic model, not a
    # dataclass, so `dataclasses.replace` cannot build a variant of one.
    return TransactionRecord(
        content_id=content_id,
        date=_f(date),
        amount=_f(amount),
        direction=_f("credit"),
        description=_f(description),
    )


def _statement(
    content_id: str, txns: tuple[TransactionRecord, ...], *, masked: str = "XX-XXXX-1943"
) -> DocumentEntry:
    return DocumentEntry(
        content_id=content_id,
        document_type="bank_statement",
        fields={"bank_name": _f("PNC Bank"), "account_number_masked": _f(masked)},
        transactions=txns,
    )


def _snap(entries: list[DocumentEntry]) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 9, 11, tzinfo=UTC),
        documents=DocumentsSection.present(entries),
        tags=TagsSection.present({}),
    )


def _result(
    subject_id: str,
    *,
    rule_id: str = "AS-1",
    verdict: Verdict = Verdict.FIRED,
    tags: tuple[LoadBearingTag, ...] = (),
    sources: tuple[str, ...] = (),
) -> RuleEvaluation:
    return RuleEvaluation(
        rule_id=rule_id,
        subject_id=subject_id,
        verdict=verdict,
        verdict_confidence=None,
        load_bearing_tags=tags,
        threshold_used=None,
        priya_validated=False,
        gated_pending_signoff=False,
        reasoning="deposit 19039.08 exceeds the large-deposit threshold and is not sourced",
        how_to_fix="Document this deposit's source.",
        source_content_ids=sources,
    )


def _tag(value: str, tag_id: str = "txn.amount") -> LoadBearingTag:
    return LoadBearingTag(tag_id, value, None, "fixture", ("raw",))


_TWIN_SNAPSHOT = _snap(
    [
        _statement("stmt_a", (_txn("txn_a"),)),
        _statement("stmt_b", (_txn("txn_b"),)),  # the same line, the same account, uploaded twice
    ]
)


# --------------------------------------------------------------------------- #
# The collapse
# --------------------------------------------------------------------------- #
def test_the_same_deposit_on_two_uploads_becomes_one_finding() -> None:
    """THE LF-XMB2 SHAPE."""
    results = [
        _result("txn_a", sources=("stmt_a",)),
        _result("txn_b", sources=("stmt_b",)),
    ]

    collapsed = _collapse_duplicate_transactions(results, _TWIN_SNAPSHOT)

    assert len(collapsed) == 1
    assert collapsed[0].subject_id == "txn_a", "the first is kept, deterministically"


def test_the_survivor_does_not_depend_on_the_order_the_rows_arrive_in() -> None:
    """bug-024 review — A CORRECTION TO THIS TICKET'S OWN REVIEW, which let list order decide.

    The surviving row keeps its `subject_id`, and that becomes the finding's `subject_key`. If a later
    run picks the other twin, the reconciler meets a subject it has never seen: it mints a new finding
    and retires the old one, discarding its history and any disposition short of "resolved". Document
    order is `(document_type, created_at, id)`, so classifying a previously untyped statement reshuffles
    the group — the survivor cannot be "whichever came first in the list".
    """
    forward = [_result("txn_a", sources=("stmt_a",)), _result("txn_b", sources=("stmt_b",))]
    reversed_order = [_result("txn_b", sources=("stmt_b",)), _result("txn_a", sources=("stmt_a",))]

    (first,) = _collapse_duplicate_transactions(forward, _TWIN_SNAPSHOT)
    (second,) = _collapse_duplicate_transactions(reversed_order, _TWIN_SNAPSHOT)

    assert first.subject_id == second.subject_id == "txn_a", (
        "the same pair arriving in the other order chose a different survivor, which re-keys the "
        "finding and throws away its history"
    )
    assert set(first.source_content_ids) == set(second.source_content_ids) == {"stmt_a", "stmt_b"}


def test_the_surviving_row_names_both_uploads() -> None:
    """The point of collapsing at emission rather than in the enumerator: the processor can still see
    the deposit appears on two files, which is how the duplicate upload becomes visible at all."""
    results = [
        _result("txn_a", sources=("stmt_a",)),
        _result("txn_b", sources=("stmt_b",)),
    ]

    (survivor,) = _collapse_duplicate_transactions(results, _TWIN_SNAPSHOT)

    assert survivor.source_content_ids == ("stmt_a", "stmt_b")


def test_the_surviving_row_keeps_everything_else_it_had() -> None:
    """Kept whole, never rebuilt — the class of defect `_collapse_uniform_passes` recorded twice
    (bug-006 lost ratification_pending; bug-007 lost the tags that name the subject)."""
    first = _result("txn_a", tags=(_tag("19039.08"),), sources=("stmt_a",))
    results = [first, _result("txn_b", tags=(_tag("19039.08"),), sources=("stmt_b",))]

    (survivor,) = _collapse_duplicate_transactions(results, _TWIN_SNAPSHOT)

    assert survivor == replace(first, source_content_ids=("stmt_a", "stmt_b"))


def test_each_rule_collapses_independently() -> None:
    """AS-1 and AS-12 both judge the same deposit twice; each becomes one row, not one row between
    them — they are different questions about the same transaction."""
    results = [
        _result("txn_a", rule_id="AS-1", sources=("stmt_a",)),
        _result("txn_b", rule_id="AS-1", sources=("stmt_b",)),
        _result("txn_a", rule_id="AS-12", verdict=Verdict.NEEDS_REVIEW, sources=("stmt_a",)),
        _result("txn_b", rule_id="AS-12", verdict=Verdict.NEEDS_REVIEW, sources=("stmt_b",)),
    ]

    collapsed = _collapse_duplicate_transactions(results, _TWIN_SNAPSHOT)

    assert [(r.rule_id, r.subject_id) for r in collapsed] == [("AS-1", "txn_a"), ("AS-12", "txn_a")]


# --------------------------------------------------------------------------- #
# What must NOT merge
# --------------------------------------------------------------------------- #
def test_two_identical_lines_on_ONE_statement_stay_two_findings() -> None:
    """Two payments of the same amount on the same day are two real transactions. Merging them would
    hide one — the opposite failure, and the worse one."""
    snapshot = _snap([_statement("stmt_a", (_txn("txn_1"), _txn("txn_2")))])
    results = [_result("txn_1", sources=("stmt_a",)), _result("txn_2", sources=("stmt_a",))]

    assert len(_collapse_duplicate_transactions(results, snapshot)) == 2


def test_copies_the_extractor_read_differently_stay_two_findings() -> None:
    """The two LF-XMB2 uploads yielded 20 rows and 21, so the copies are demonstrably not identical.
    Where the tags disagree, a human should see both rather than one picked for them."""
    results = [
        _result("txn_a", tags=(_tag("19039.08"),), sources=("stmt_a",)),
        _result("txn_b", tags=(_tag("19038.08"),), sources=("stmt_b",)),  # read differently
    ]

    assert len(_collapse_duplicate_transactions(results, _TWIN_SNAPSHOT)) == 2


def test_copies_whose_DESCRIPTION_differs_stay_two_findings() -> None:
    """bug-021 review — MEASURED ON THE REAL FILE, and it is the identity's live edge.

    Comparing the two LF-XMB2 uploads through the read-only views: 16 of the 20 lines carry
    byte-identical (date, amount, description) and merge — including both pairs this ticket names. The
    other four differ in the DESCRIPTION only, in two shapes: one copy prefixes a card-sequence number
    ("1827 Debit Card Purchase Giv*Rccg Living Spring" vs "Debit Card Purchase Giv*Rccg Living
    Spring"), and two `Web Pmt` lines carry a trailing identifier in one copy alone.

    Those four stay two rows each, which is the fail-safe direction and is pinned here so nobody
    "fixes" it by stripping digits from descriptions: "Check 1827" and "Check 1828" on one day for one
    amount would then share an identity, and a real second cheque would disappear.
    """
    snapshot = _snap(
        [
            _statement("stmt_a", (_txn("txn_a"),)),
            _statement(
                "stmt_b", (_txn("txn_b", description="1827 Instpmntin Intuit Payments Inc."),)
            ),
        ]
    )
    results = [_result("txn_a", sources=("stmt_a",)), _result("txn_b", sources=("stmt_b",))]

    assert len(_collapse_duplicate_transactions(results, snapshot)) == 2


def test_a_verdict_disagreement_stays_two_findings() -> None:
    results = [
        _result("txn_a", verdict=Verdict.FIRED, sources=("stmt_a",)),
        _result("txn_b", verdict=Verdict.COULDNT_CHECK, sources=("stmt_b",)),
    ]

    assert len(_collapse_duplicate_transactions(results, _TWIN_SNAPSHOT)) == 2


def test_a_different_account_never_merges() -> None:
    """The account is part of the identity, so the same amount on the same day at another account is a
    different transaction — and two accounts at one bank cannot collide."""
    snapshot = _snap(
        [
            _statement("stmt_a", (_txn("txn_a"),)),
            _statement("stmt_b", (_txn("txn_b"),), masked="XX-XXXX-9413"),
        ]
    )
    results = [_result("txn_a", sources=("stmt_a",)), _result("txn_b", sources=("stmt_b",))]

    assert len(_collapse_duplicate_transactions(results, snapshot)) == 2


def test_an_unidentifiable_account_never_merges() -> None:
    """No institution or no masked number means no account identity. Fail closed: no identity, no
    duplicate — never a guessed grouping."""
    entries = [
        DocumentEntry(
            content_id=cid,
            document_type="bank_statement",
            fields={"bank_name": _f("PNC Bank")},  # no masked number
            transactions=(_txn(txn),),
        )
        for cid, txn in (("stmt_a", "txn_a"), ("stmt_b", "txn_b"))
    ]
    results = [_result("txn_a", sources=("stmt_a",)), _result("txn_b", sources=("stmt_b",))]

    assert len(_collapse_duplicate_transactions(results, _snap(entries))) == 2


def test_a_rule_a_processor_has_answered_is_left_alone() -> None:
    """bug-007's guard, adopted. Re-keying retires a resolved finding into fresh OPEN work, so once
    someone has applied or overridden a row for this rule on this file, it stays per subject."""
    results = [
        _result("txn_a", sources=("stmt_a",)),
        _result("txn_b", sources=("stmt_b",)),
    ]

    collapsed = _collapse_duplicate_transactions(
        results, _TWIN_SNAPSHOT, humanly_resolved_rule_ids=frozenset({"AS-1"})
    )

    assert len(collapsed) == 2


def test_a_loan_level_row_is_untouched() -> None:
    """Only transaction subjects have a duplicate identity; everything else passes through in order."""
    results = [
        _result("loan", rule_id="AS-10", verdict=Verdict.SATISFIED),
        _result("txn_a", sources=("stmt_a",)),
        _result("txn_b", sources=("stmt_b",)),
    ]

    collapsed = _collapse_duplicate_transactions(results, _TWIN_SNAPSHOT)

    assert [r.subject_id for r in collapsed] == ["loan", "txn_a"]

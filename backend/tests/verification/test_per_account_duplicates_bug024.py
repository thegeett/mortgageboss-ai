"""bug-024 — AS-6 asks about an account and answers once per statement.

LF-XMB2 carries three statements of PNC ****1943 and asked the same question three times: "this is a
joint account with an additional holder who is not a borrower — confirm the arrangement." One account,
one question, three rows.

`collapse_uniform` is the wrong instrument: it groups per RULE per FILE and stops at the first
dissenting verdict, so on LF-XMB2 (five satisfied, three needs_review) it does nothing at all. The
grouping has to be the ACCOUNT, because the account is what the sentence is about.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from app.services.verification_run import _collapse_per_account_duplicates
from app.verification.rule_engine.result import LoadBearingTag, RuleEvaluation, Verdict
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    DocumentEntry,
    DocumentsSection,
    Snapshot,
    TagsSection,
)


def _f(value: str) -> Field:
    return Field.present(value, source=FieldSource.EXTRACTED)


def _statement(content_id: str, *, masked: str = "XX-XXXX-1943") -> DocumentEntry:
    return DocumentEntry(
        content_id=content_id,
        document_type="bank_statement",
        fields={"bank_name": _f("PNC Bank"), "account_number_masked": _f(masked)},
    )


def _snap(entries: list[DocumentEntry]) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 9, 11, tzinfo=UTC),
        documents=DocumentsSection.present(entries),
        tags=TagsSection.present({}),
    )


def _tag(value: str, tag_id: str = "stmt.non_borrower_co_holder") -> LoadBearingTag:
    return LoadBearingTag(tag_id, value, None, "fixture", ("raw",))


def _result(
    subject_id: str,
    *,
    rule_id: str = "AS-6",
    verdict: Verdict = Verdict.NEEDS_REVIEW,
    tags: tuple[LoadBearingTag, ...] = (_tag("yes"),),
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
        reasoning="this is a joint account with an additional holder who is not a borrower on the loan",
        how_to_fix="Confirm the non-borrower co-holder's relationship to the borrower.",
        source_content_ids=sources or (subject_id,),
    )


# Three statements of ONE account — the LF-XMB2 shape.
_ONE_ACCOUNT = _snap([_statement("stmt_a"), _statement("stmt_b"), _statement("stmt_c")])


def test_the_survivor_does_not_depend_on_the_order_the_rows_arrive_in() -> None:
    """bug-024 review — THE RECONCILER'S EXPOSURE, closed.

    The surviving row keeps its own `subject_id`, and that IS the finding's `subject_key`. If a later
    run picks a different statement, the reconciler meets a subject it has never seen: it mints a fresh
    finding and retires the old one, taking its history and any disposition short of "resolved".

    List order cannot be trusted for that choice. Documents load ordered by
    `(document_type, created_at, id)`, so classifying a previously untyped statement — or a
    re-extraction that changes a type — moves a row within its group. Here the same three rows arrive
    in three different orders and the survivor must not move.
    """
    for order in (
        ("stmt_a", "stmt_b", "stmt_c"),
        ("stmt_c", "stmt_a", "stmt_b"),
        ("stmt_b", "stmt_c", "stmt_a"),
    ):
        (survivor,) = _collapse_per_account_duplicates(
            [_result(cid) for cid in order], _ONE_ACCOUNT
        )

        assert survivor.subject_id == "stmt_a", (
            f"arriving as {order} chose {survivor.subject_id!r}; the survivor must be the same "
            "statement on every run, or the finding is re-keyed and its history is discarded"
        )
        # Every statement stays named regardless of the order they arrived in.
        assert set(survivor.source_content_ids) == {"stmt_a", "stmt_b", "stmt_c"}


# --------------------------------------------------------------------------- #
# The collapse
# --------------------------------------------------------------------------- #
def test_three_statements_of_one_account_ask_the_question_once() -> None:
    """THE LF-XMB2 SHAPE."""
    results = [_result("stmt_a"), _result("stmt_b"), _result("stmt_c")]

    collapsed = _collapse_per_account_duplicates(results, _ONE_ACCOUNT)

    assert len(collapsed) == 1
    # bug-024 review — the LOWEST content id survives, not "the first in the list"; here they coincide.
    # The test above is the one that pins it, by feeding these same rows in other orders.
    assert collapsed[0].subject_id == "stmt_a"


def test_the_surviving_row_names_every_statement_it_covers() -> None:
    """The answer is about the account, so the row a processor opens must still show which statements
    it was read from — the same reason bug-021's collapse unions its sources."""
    results = [_result("stmt_a"), _result("stmt_b"), _result("stmt_c")]

    (survivor,) = _collapse_per_account_duplicates(results, _ONE_ACCOUNT)

    assert survivor.source_content_ids == ("stmt_a", "stmt_b", "stmt_c")


def test_the_surviving_row_keeps_everything_else_it_had() -> None:
    """Kept whole, never rebuilt — the defect class `_collapse_uniform_passes` recorded twice (bug-006
    lost ratification_pending; bug-007 lost the tags that name the subject)."""
    first = _result("stmt_a")
    results = [first, _result("stmt_b")]

    (survivor,) = _collapse_per_account_duplicates(results, _ONE_ACCOUNT)

    assert survivor == replace(first, source_content_ids=("stmt_a", "stmt_b"))


# --------------------------------------------------------------------------- #
# The opt-in — the guard that makes this safe to run over every statement rule
# --------------------------------------------------------------------------- #
def test_a_rule_that_does_not_declare_it_never_merges() -> None:
    """⚠️ THE GUARD THIS TICKET TURNS ON, and AS-9 is why it exists rather than a rule blacklist.

    Exactly two rules take a bank statement as their subject. AS-6's answer is about the ACCOUNT; AS-9
    ("declares 3 pages, 2 present") is about the STATEMENT. AS-9's page counts are not extracted today,
    so every one of its rows is a couldnt_check whose fact set is identically EMPTY on every statement
    of an account — an ungated collapse merges them TODAY. When the extraction lands it gets worse: three
    statements each declaring 3 pages with 2 present carry identical values, and three separate
    incomplete statements would become one row naming one of them.

    This reads the REAL spec, so deleting `answers_per_account: true` from AS-6 or adding it to AS-9
    fails here rather than in staging.
    """
    results = [
        _result("stmt_a", rule_id="AS-9", verdict=Verdict.COULDNT_CHECK, tags=()),
        _result("stmt_b", rule_id="AS-9", verdict=Verdict.COULDNT_CHECK, tags=()),
        _result("stmt_c", rule_id="AS-9", verdict=Verdict.COULDNT_CHECK, tags=()),
    ]

    assert len(_collapse_per_account_duplicates(results, _ONE_ACCOUNT)) == 3


def test_an_unknown_rule_id_never_merges() -> None:
    """No spec, no declaration, no collapse — fail closed rather than raise."""
    results = [_result("stmt_a", rule_id="ZZ-99"), _result("stmt_b", rule_id="ZZ-99")]

    assert len(_collapse_per_account_duplicates(results, _ONE_ACCOUNT)) == 2


# --------------------------------------------------------------------------- #
# What must NOT merge
# --------------------------------------------------------------------------- #
def test_two_accounts_are_two_answers() -> None:
    """Whatever they say. A file with a non-borrower co-holder on two accounts must not produce one row
    naming neither — which is exactly what a per-rule-per-file collapse would do."""
    snapshot = _snap([_statement("stmt_a"), _statement("stmt_b", masked="XX-XXXX-9413")])
    results = [_result("stmt_a"), _result("stmt_b")]

    assert len(_collapse_per_account_duplicates(results, snapshot)) == 2


def test_different_facts_on_one_account_stay_separate() -> None:
    """THE LF-AYK4 SHAPE, and the reason the key carries the facts at all.

    Five rows, one outcome, two fact sets: four say a co-holder is not a borrower, and one says the
    holder name did not resolve — a MISSPELLED holder ("Divyeshkuamr Patel"), which is a different
    question with a different remedy. Keyed on the account alone, that fifth row disappears.
    """
    results = [
        _result("stmt_a"),
        _result("stmt_b"),
        _result(
            "stmt_c",
            tags=(_tag("unknown", "stmt.owner_matches_borrower"),),
        ),
    ]

    collapsed = _collapse_per_account_duplicates(results, _ONE_ACCOUNT)

    assert [r.subject_id for r in collapsed] == ["stmt_a", "stmt_c"]


def test_a_verdict_disagreement_stays_separate() -> None:
    """One statement satisfied and another needing review disagree about something real."""
    results = [_result("stmt_a"), _result("stmt_b", verdict=Verdict.SATISFIED)]

    assert len(_collapse_per_account_duplicates(results, _ONE_ACCOUNT)) == 2


def test_an_unidentifiable_account_never_merges() -> None:
    """No institution or no masked number means no account identity. Fail closed: no identity, no
    grouping — never a guessed one."""
    entries = [
        DocumentEntry(
            content_id=cid,
            document_type="bank_statement",
            fields={"bank_name": _f("PNC Bank")},  # no masked number
        )
        for cid in ("stmt_a", "stmt_b")
    ]
    results = [_result("stmt_a"), _result("stmt_b")]

    assert len(_collapse_per_account_duplicates(results, _snap(entries))) == 2


def test_a_rule_a_processor_has_answered_is_left_alone() -> None:
    """bug-007's guard, adopted by bug-021 and kept here. Re-keying retires a resolved finding into
    fresh OPEN work, so once someone has applied or overridden a row for this rule on this file, it
    stays per subject."""
    results = [_result("stmt_a"), _result("stmt_b")]

    collapsed = _collapse_per_account_duplicates(
        results, _ONE_ACCOUNT, humanly_resolved_rule_ids=frozenset({"AS-6"})
    )

    assert len(collapsed) == 2


def test_a_non_statement_row_is_untouched() -> None:
    """Only statement subjects have an account, and everything else passes through in order."""
    results = [
        _result("loan", rule_id="AS-10", verdict=Verdict.SATISFIED),
        _result("stmt_a"),
        _result("stmt_b"),
    ]

    collapsed = _collapse_per_account_duplicates(results, _ONE_ACCOUNT)

    assert [r.subject_id for r in collapsed] == ["loan", "stmt_a"]

"""LP-597 — DT-8 stops overclaiming, and gains the one guard its own guideline text demands.

TWO CHANGES, AND THE VERDICT IS NOT ONE OF THEM. The satisfied branch stays satisfied on an ordinary
refinance: an application IS authoritative about the borrower's own intent, a refinance definitionally
retires the subject lien (B3-6-07 governs consumer debts paid off TO QUALIFY, not this), and making
this a review would put a permanent item on every refinance file where the form already answered.

What was wrong was the sentence and the missing guard:

1. WORDING. "its payment is CORRECTLY excluded from the BACK-END DEBT-TO-INCOME RATIO" claimed two
   things it had not established — that the lien sits on the subject property (nothing checked), and
   a property of a ratio that is GATED on any file whose taxes and insurance have not arrived.

2. THE GUARD. DT-8's own guideline text says "A mortgage secured by other property the borrower
   retains remains an obligation and stays in the ratio", and nothing tested it. An LO who ticks
   payoff on the wrong row silently removes that payment from the DTI. LP-596 put the 1003's
   owned-property schedule in the snapshot, so the contradiction is now checkable with NO threshold:
   a lien marked paid off whose property is marked Retain is the form disagreeing with itself.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.verification.rule_engine.deterministic import evaluate_deterministic_rule
from app.verification.rule_engine.enumerators import _per_liability as liability_rows_ids
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import MismoSection, Snapshot, TagsSection
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.tag_materialization.derived import _liability_payoff_contradicted
from app.verification.tag_materialization.subjects import subject_type

_DT8 = load_rule_spec("DT-8")


def _tag(value: str) -> Tag:
    return Tag(
        value=value,
        confidence=None,
        reasoning="fixture",
        source_facts=("raw",),
        produced_by=TagProducedBy.DERIVED,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def _evaluate(*, marked: str, contradicted: str | None):
    """DT-8 over one stated mortgage liability.

    The liability must exist as MISMO FACTS, not just tags: `per_liability` enumerates from
    `liability.<n>.*` and keys each subject by a content hash over its fields, so tags attached to a
    made-up subject id would be read by nothing. The id is discovered from the enumerator for exactly
    that reason (the contract `test_liability_subject_lp483` pins).
    """
    mismo: dict[str, Field] = {
        "loan.purpose": Field.present("refinance", source=FieldSource.PARSED),
    }
    for name, value in (
        ("type", "MortgageLoan"),
        ("holder_name", "UNITED WHSLE MORT"),
        ("monthly_payment", "3186.00"),
        ("unpaid_balance", "451829.00"),
    ):
        mismo[f"liability.1.{name}"] = Field.present(value, source=FieldSource.PARSED)

    base = Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 8, 20, tzinfo=UTC),
        mismo=MismoSection.present(mismo),
        tags=TagsSection.present({}),
    )
    subject_ids = [sid for sid, _ in liability_rows_ids(base)]
    assert len(subject_ids) == 1, subject_ids

    liability_tags = {
        "liab.stated_is_mortgage": _tag("yes"),
        "liab.payoff_marked": _tag(marked),
        "liab.creditor_name": _tag("UNITED WHSLE MORT"),
        "liab.monthly_payment": _tag("3186.00"),
    }
    if contradicted is not None:
        liability_tags["liab.payoff_contradicted"] = _tag(contradicted)

    snapshot = Snapshot(
        loan_file_id=base.loan_file_id,
        run_id=base.run_id,
        created_at=base.created_at,
        mismo=MismoSection.present(mismo),
        tags=TagsSection.present(
            {subject_ids[0]: liability_tags, "loan": {"loan.purpose": _tag("refinance")}}
        ),
    )
    return evaluate_deterministic_rule(_DT8, snapshot)


def test_the_ordinary_refinance_still_passes_quietly() -> None:
    """THE DECISION THIS TICKET DID NOT MAKE. LF-3CVT's shape: one mortgage, marked paid off, nothing
    contradicting it. Downgrading this would put a permanent item on every refinance file where the
    application already answered the question — alarm fatigue bought for nothing."""
    evaluations = _evaluate(marked="yes", contradicted="no")

    assert evaluations[0].verdict is Verdict.SATISFIED


def test_the_satisfied_wording_no_longer_overclaims() -> None:
    """Both overclaims, asserted as absences so a future edit that reintroduces either fails here."""
    reasoning = _evaluate(marked="yes", contradicted="no")[0].reasoning

    assert "correctly" not in reasoning.lower(), (
        "'correctly' asserts the lien sits on the SUBJECT property, which this branch never checks"
    )
    assert "back-end" not in reasoning.lower(), (
        "the back-end ratio is gated whenever taxes and insurance are missing — this branch must not "
        "assert a property of a calculation that did not run"
    )
    assert "the application marks this mortgage as paid off at closing" in reasoning


def test_a_retained_property_contradicting_the_payoff_reaches_a_human() -> None:
    """THE GUARD. The form says both "this lien is paid off at closing" and "the borrower keeps that
    property". DT-8's guideline text is explicit that which one is true decides the ratio."""
    evaluation = _evaluate(marked="yes", contradicted="yes")[0]

    assert evaluation.verdict is Verdict.NEEDS_REVIEW
    assert "retained" in evaluation.reasoning
    # needs_review carries an Apply (LP-576), which is the whole point — the human's answer becomes
    # an auditable applied_record rather than an inherited checkbox.
    assert evaluation.apply is not None


def test_the_guard_is_ordered_ahead_of_satisfied() -> None:
    """First match wins, so the guard must precede the branch it guards or it never runs."""
    verdicts = [o.verdict for o in _DT8.deterministic.outcomes]

    assert verdicts.index("needs_review") < verdicts.index("satisfied")


def test_an_absent_guard_tag_leaves_dt8_exactly_where_it_was() -> None:
    """CONTAINMENT, and why `liab.payoff_contradicted` is load-bearing but NOT gated. A file whose
    export omits the owned-property schedule must still get DT-8's answer, not a couldnt_check."""
    evaluations = _evaluate(marked="yes", contradicted=None)

    assert evaluations[0].verdict is Verdict.SATISFIED


def test_an_unmarked_mortgage_still_asks_the_original_question() -> None:
    """The pre-existing needs_review branch is untouched: nobody has said whether this survives
    closing, which is the case DT-8 was written for."""
    evaluation = _evaluate(marked="no", contradicted="no")[0]

    assert evaluation.verdict is Verdict.NEEDS_REVIEW
    assert evaluation.apply is not None


# --------------------------------------------------------------------------- #
# The producer — the balance join that makes the contradiction detectable
# --------------------------------------------------------------------------- #


def _producer_snapshot(owned: list[dict[str, str]], balance: str = "451829.00"):
    """One stated mortgage liability plus an owned-property schedule, as LP-596 projects it."""
    mismo: dict[str, Field] = {}
    for name, value in (
        ("type", "MortgageLoan"),
        ("holder_name", "UNITED WHSLE MORT"),
        ("monthly_payment", "3186.00"),
        ("unpaid_balance", balance),
    ):
        mismo[f"liability.1.{name}"] = Field.present(value, source=FieldSource.PARSED)
    for index, row in enumerate(owned, start=1):
        for field, value in row.items():
            mismo[f"owned_property.{index}.{field}"] = Field.present(
                value, source=FieldSource.PARSED
            )
    snapshot = Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 8, 20, tzinfo=UTC),
        mismo=MismoSection.present(mismo),
        tags=TagsSection.present({}),
    )
    subject_id, raw = next(iter(subject_type("liability").enumerate(snapshot)))
    return snapshot, subject_id, raw


def test_a_retained_property_at_the_same_balance_is_a_contradiction() -> None:
    """The join is BY BALANCE, which is what links the two sections: in the real export the
    OwnedPropertyLienUPBAmount values equal the LiabilityUnpaidBalanceAmount values exactly.

    LP-600 — THE SCHEDULE MUST IDENTIFY A SUBJECT SOMEWHERE for a `false` to mean anything, so the
    fixture now carries a second row that does. The first version of this test asserted a
    contradiction from `is_subject: "False"` alone, which encoded the ambiguity instead of resolving
    it: on an export that never sets the flag, the row would be the subject property itself.
    """
    snapshot, subject_id, raw = _producer_snapshot(
        [
            {"is_subject": "True", "disposition_status": "Retain", "lien_upb": "300000.00"},
            {"is_subject": "False", "disposition_status": "Retain", "lien_upb": "451829.00"},
        ]
    )

    value, reason = _liability_payoff_contradicted(snapshot, subject_id, raw)

    assert value == "yes"
    assert "retained" in reason


def test_a_schedule_that_never_marks_a_subject_establishes_no_contradiction() -> None:
    """LP-600 — THE FALSE POSITIVE THIS CLOSES, and it fires on the ordinary refinance.

    `OwnedPropertyDispositionStatusType` describes the PROPERTY, not the lien. A borrower refinancing
    their home retains it — of course — while the lien is retired at closing. So on an export that
    never sets the subject indicator, the subject's own row matched the refinanced lien and DT-8
    announced that "the schedule marks the property securing this lien as retained" about the very
    lien being paid off.
    """
    snapshot, subject_id, raw = _producer_snapshot(
        [{"is_subject": "False", "disposition_status": "Retain", "lien_upb": "451829.00"}]
    )

    value, reason = _liability_payoff_contradicted(snapshot, subject_id, raw)

    assert value == "no"
    assert "does not identify which property this loan is against" in reason


def test_a_schedule_entry_marked_subject_corroborates_rather_than_contradicts() -> None:
    """Only a TRUE marks the subject (LP-596). When the schedule DOES identify the lien as the
    subject's, the payoff marking is confirmed, not contradicted."""
    snapshot, subject_id, raw = _producer_snapshot(
        [{"is_subject": "True", "disposition_status": "Retain", "lien_upb": "451829.00"}]
    )

    assert _liability_payoff_contradicted(snapshot, subject_id, raw)[0] == "no"


def test_a_property_being_sold_is_not_a_contradiction() -> None:
    """Selling the property retires the lien too — consistent with a payoff marking."""
    snapshot, subject_id, raw = _producer_snapshot(
        [{"is_subject": "False", "disposition_status": "Sell", "lien_upb": "451829.00"}]
    )

    assert _liability_payoff_contradicted(snapshot, subject_id, raw)[0] == "no"


def test_no_matching_balance_establishes_nothing() -> None:
    """ "no" means UNESTABLISHED, not "verified fine". A file whose export omits the schedule, or whose
    balances do not line up, must leave DT-8 exactly where it was rather than inventing a conflict."""
    snapshot, subject_id, raw = _producer_snapshot(
        [{"is_subject": "False", "disposition_status": "Retain", "lien_upb": "999999.00"}]
    )

    value, reason = _liability_payoff_contradicted(snapshot, subject_id, raw)

    assert value == "no"
    assert "no owned property on the schedule matches" in reason


def test_an_absent_schedule_establishes_nothing() -> None:
    snapshot, subject_id, raw = _producer_snapshot([])

    assert _liability_payoff_contradicted(snapshot, subject_id, raw)[0] == "no"

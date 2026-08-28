"""LP-573 — DT-8: a refinanced lien still counted in the debt-to-income ratio.

DTI is FORWARD-LOOKING — it measures what the borrower owes AFTER this loan funds. On a refinance the
mortgage being replaced is paid off at closing, so counting its payment alongside the new housing
payment charges the same property twice.

LF-WCHG, a rate/term refinance: income 13,166.67, new PITI 4,418.785, liabilities 3,186.00 (a
MortgageLoan held by the servicer named on the file's mortgage statement) + 49 + 35 + 25. The engine
reported a back-end DTI of 58.59%; worked by hand with the resident domain expert, the correct figure
is 34.39%. That difference flips the file from failing most conventional overlays to passing.

THE RULE ASKS; IT DOES NOT CONCLUDE. It never proves WHICH property secures a mortgage, and it can
never `fire`. Excluding a debt that is actually retained understates the DTI and can pass a loan that
should fail, so the judgment stays with a human and Apply is their affirmation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.verification.rule_engine.deterministic import evaluate_deterministic_rule
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import MismoSection, Snapshot
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio

_DT8 = load_rule_spec("DT-8")


def _snapshot(
    *,
    purpose: str | None = "refinance",
    liability_type: str = "MortgageLoan",
    paid_off: str | None = None,
) -> Snapshot:
    """One stated liability on a file whose purpose is settable."""
    facts = {
        "liability.1.type": Field.present(liability_type, source=FieldSource.PARSED),
        "liability.1.monthly_payment": Field.present("3186.00", source=FieldSource.PARSED),
        "liability.1.unpaid_balance": Field.present("435012.22", source=FieldSource.PARSED),
        "liability.1.holder_name": Field.present("UNITED WHSLE MORT", source=FieldSource.PARSED),
    }
    if paid_off is not None:
        facts["liability.1.paid_off_at_closing"] = Field.present(
            paid_off, source=FieldSource.PARSED
        )
    if purpose is not None:
        facts["loan.purpose"] = Field.present(purpose, source=FieldSource.PARSED)
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime.now(UTC),
        mismo=MismoSection(facts=facts),
    )


async def _evaluate(**kw):
    materialized = await materialize_tags(_snapshot(**kw), only_groups=frozenset())
    evaluations = evaluate_deterministic_rule(_DT8, materialized)
    assert len(evaluations) == 1, f"expected one liability subject, got {len(evaluations)}"
    return evaluations[0]


async def test_an_unmarked_mortgage_on_a_refinance_is_surfaced() -> None:
    """THE HEADLINE — the LF-WCHG case. A mortgage counted in the ratio with nothing saying it is
    retired at closing."""
    evaluation = await _evaluate()

    assert evaluation.verdict is Verdict.NEEDS_REVIEW
    assert "3186.00" in evaluation.reasoning
    assert "charging the same property twice" in evaluation.reasoning


async def test_it_can_never_fire() -> None:
    """A mortgage liability on a refinance is a QUESTION, not a defect — a borrower may hold
    mortgages on property being retained, whose payments belong in the ratio. Pinned as a design
    property, the same way DT-6 pins its own."""
    assert all(o.verdict != "fired" for o in _DT8.deterministic.outcomes)


async def test_an_already_marked_mortgage_is_satisfied() -> None:
    """Answered already — by the application's payoff indicator or by a processor. `satisfied`, not
    `not_applicable`: the rule DID apply and found nothing wrong."""
    evaluation = await _evaluate(paid_off="True")

    assert evaluation.verdict is Verdict.SATISFIED


async def test_a_non_mortgage_is_out_of_scope() -> None:
    """A credit card survives closing and belongs in the ratio, so the rule is irrelevant to it by
    NATURE — scope-false, not a pass. §8's distinction, and the engine enforces it: `not_applicable`
    can only come from the applicability predicate, never an outcome."""
    evaluation = await _evaluate(liability_type="Revolving")

    assert evaluation.verdict is Verdict.NOT_APPLICABLE


async def test_a_purchase_is_out_of_scope() -> None:
    """The defect is not refinance-only — a purchase reaches it through a departing residence being
    sold, or a debt cleared to qualify — but detecting THOSE needs different evidence. Scoping here
    is honest about what this rule asks, and the liabilities editor's control (LP-571) remains the
    path for the rest."""
    evaluation = await _evaluate(purpose="purchase")

    assert evaluation.verdict is Verdict.NOT_APPLICABLE


async def test_an_unstated_purpose_is_not_absorbed_into_scope_false() -> None:
    """§8: absent is not the same as known-false. A file that does not state its purpose has not
    said "this is a purchase", and must not be silently scoped out."""
    evaluation = await _evaluate(purpose=None)

    assert evaluation.verdict is not Verdict.NOT_APPLICABLE
    assert evaluation.verdict is Verdict.COULDNT_CHECK


async def test_the_apply_targets_the_holder() -> None:
    """The Apply writes to `stated_liabilities`, but a governed rule's subjects are content hashes,
    never DB primary keys — so the holder is the business key both sides share, exactly as
    `correct_liability_payment` resolved the same problem."""
    apply = _DT8.deterministic.apply

    assert apply is not None
    assert apply.action == "exclude_liability_paid_off"
    assert apply.fields["holder_name"].tag == "liab.creditor_name"


def test_dt8_is_scoped_to_the_applications_own_liabilities() -> None:
    """bug-003 — `per_liability` unions credit-report tradelines with MISMO stated liabilities, and
    `liab.stated_is_mortgage` reads MISMO's LiabilityType, so it DECLINES on a tradeline. An unknown
    applicability predicate is couldnt_check, not not_applicable, so LF-AWBB's 24 tradelines produced
    24 findings asking whether a Rooms To Go store card was the mortgage being refinanced.

    CR-12 carries the same predicate in the mirror direction for the same reason.
    """
    from app.verification.rules.specs import load_rule_spec

    applicability = load_rule_spec("DT-8").deterministic.applicability
    assert isinstance(applicability, tuple)
    predicates = {(c.tag or c.loan_tag, c.op, c.value) for c in applicability}
    assert ("loan.purpose", "eq", "refinance") in predicates
    assert ("liability.source", "eq", "mismo_stated") in predicates
    assert ("liab.stated_is_mortgage", "eq", "yes") in predicates


def test_cr8_is_scoped_to_credit_report_tradelines() -> None:
    """bug-005 — the same defect as DT-8's, in a rule whose own prose already stated the scope.

    CR-8's `applicability.scope` has said "each credit-report tradeline the model identifies as a
    mortgage" since it was written, but the predicate only gated on `liab.is_mortgage`. `per_liability`
    unions tradelines with the application's MISMO liabilities, so the stated liability got a subject
    too and LF-AWBB produced THREE findings for ONE mortgage — two tradelines and the MISMO row, all
    asking for the same UWM payment history.

    A payment history is a credit-report fact; MISMO carries type, payment, balance and holder and
    nothing else, so that subject could only ever ask for something it cannot receive.
    """
    from app.verification.rules.specs import load_rule_spec

    spec = load_rule_spec("CR-8")
    assert spec.judgment is not None
    applicability = spec.judgment.applicability
    assert isinstance(applicability, tuple)
    predicates = {(c.tag or c.loan_tag, c.op, c.value) for c in applicability}
    assert ("liability.source", "eq", "credit_report_reported") in predicates
    assert ("liab.is_mortgage", "eq", "yes") in predicates


def test_cr8_is_not_scoped_on_materiality() -> None:
    """THE OPPOSITE CALL TO bug-002's, and it has to stay that way.

    `liab.is_payment_bearing` is right for CR-1, where a $0/$0 account is not a debt to disclose. It is
    wrong here: a mortgage transferred to a new servicer leaves the old tradeline at a zero balance,
    and that tradeline still carries the borrower's payment history for the months it covers. The
    lookback is about the BORROWER's twelve months, not the account's current balance — so filtering on
    materiality would hide a delinquency on a transferred loan, which is the one thing CR-8 exists to
    catch.
    """
    from app.verification.rules.specs import load_rule_spec

    spec = load_rule_spec("CR-8")
    assert spec.judgment is not None
    applicability = spec.judgment.applicability
    assert isinstance(applicability, tuple)
    assert not any(c.tag == "liab.is_payment_bearing" for c in applicability)

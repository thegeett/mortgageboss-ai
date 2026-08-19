"""LP-576 — the two rules that can never fire get their Apply buttons.

TWO SEPARATE DEFECTS, ONE SYMPTOM. Both DT-6 and DT-8 are `needs_review`-only by design: their
question is "which branch is this?", not "here is a defect". Neither could offer a remediation.

1. THE GATE. `_result` attached an apply only when the verdict was FIRED. That was an
   over-correction of a real LP-564 finding (CR-1's couldnt_check offered an Apply that would insert
   a duplicate liability off an ABSTENTION), and it swept up `needs_review` — the one verdict where
   an Apply is the whole point, because the finding IS a question and the Apply is the human's
   answer. DT-8 shipped with a declared apply that could never reach a processor.

2. DT-6 DECLARED NO APPLY AT ALL. `correct_liability_payment` was implemented in
   `finding_resolution.py`, given an undo, and covered by tests — and named by no spec. DT-6 could
   tell a processor to raise a stated payment and could not do it for them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from app.verification.rule_engine.deterministic import evaluate_deterministic_rule
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    DocumentEntry,
    DocumentsSection,
    MismoSection,
    Snapshot,
)
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio


def _snapshot(*, lender: str = "United Wholesale Mortgage") -> Snapshot:
    """LF-WCHG's shape: the app states 3,186.00; the servicer bills 4,148.28 (escrow 544.39 WITHIN)."""
    statement = DocumentEntry(
        content_id="ms1",
        document_type="mortgage_statement",
        fields={
            "lender_name": Field.present(lender, source=FieldSource.EXTRACTED),
            "monthly_payment": Field.present("4148.28", source=FieldSource.EXTRACTED),
            "escrow_amount": Field.present("544.39", source=FieldSource.EXTRACTED),
        },
    )
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime.now(UTC),
        mismo=MismoSection(
            facts={
                "liability.1.type": Field.present("MortgageLoan", source=FieldSource.PARSED),
                "liability.1.monthly_payment": Field.present("3186.00", source=FieldSource.PARSED),
                "liability.1.holder_name": Field.present(
                    "UNITED WHSLE MORT", source=FieldSource.PARSED
                ),
            }
        ),
        documents=DocumentsSection.present([statement]),
    )


async def _dt6(**kw):
    materialized = await materialize_tags(_snapshot(**kw), only_groups=frozenset())
    (evaluation,) = evaluate_deterministic_rule(load_rule_spec("DT-6"), materialized)
    return evaluation


async def test_dt6_offers_its_apply_on_needs_review() -> None:
    """THE HEADLINE for both defects: a needs_review verdict now carries the remediation."""
    evaluation = await _dt6()

    assert evaluation.verdict is Verdict.NEEDS_REVIEW
    assert evaluation.apply == {
        "action": "correct_liability_payment",
        "holder_name": "UNITED WHSLE MORT",
        "monthly_payment": "4148.28",
    }


async def test_the_applied_figure_is_the_total_not_the_total_plus_escrow() -> None:
    """DT-6's single most important correctness point, now with money at stake. The statement's
    `monthly_payment` IS the PITIA; `escrow_amount` is a PORTION within it. Summing them would write
    4,692.67 onto the loan and overstate the DTI — and unlike a wrong reasoning line, an Apply
    persists it."""
    evaluation = await _dt6()

    assert evaluation.apply is not None
    assert Decimal(evaluation.apply["monthly_payment"]) == Decimal("4148.28")
    assert Decimal(evaluation.apply["monthly_payment"]) != Decimal("4148.28") + Decimal("544.39")


async def test_an_unmatched_statement_offers_no_apply() -> None:
    """The resolver drops the whole block when a field is unresolvable, which is right: with no
    matched liability there is no row to raise, and a button that edited "whichever" would be worse
    than no button."""
    evaluation = await _dt6(lender="Some Other Servicer LLC")

    assert evaluation.verdict is Verdict.COULDNT_CHECK
    assert evaluation.apply is None


async def test_an_abstention_never_carries_an_apply() -> None:
    """THE LP-564 FINDING MUST STAY FIXED. Widening the gate to needs_review must not let
    couldnt_check back in — that was CR-1 offering to insert a duplicate liability off "I could not
    tell". This asserts the exclusion directly rather than trusting the verdict above."""
    import inspect

    from app.verification.rule_engine import deterministic

    source = inspect.getsource(deterministic._result)
    assert "Verdict.FIRED, Verdict.NEEDS_REVIEW" in source
    assert "Verdict.COULDNT_CHECK" not in source.split("apply=")[1].split(",")[0]


async def test_dt8_apply_is_reachable_too() -> None:
    """The gate blocked BOTH rules that can never fire. DT-8's apply was declared and unreachable."""
    from app.verification.rule_engine.deterministic import evaluate_deterministic_rule as ev

    snap = Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime.now(UTC),
        mismo=MismoSection(
            facts={
                "liability.1.type": Field.present("MortgageLoan", source=FieldSource.PARSED),
                "liability.1.monthly_payment": Field.present("3186.00", source=FieldSource.PARSED),
                "liability.1.holder_name": Field.present(
                    "UNITED WHSLE MORT", source=FieldSource.PARSED
                ),
                "loan.purpose": Field.present("refinance", source=FieldSource.PARSED),
            }
        ),
    )
    materialized = await materialize_tags(snap, only_groups=frozenset())
    (evaluation,) = ev(load_rule_spec("DT-8"), materialized)

    assert evaluation.verdict is Verdict.NEEDS_REVIEW
    assert evaluation.apply == {
        "action": "exclude_liability_paid_off",
        "holder_name": "UNITED WHSLE MORT",
    }

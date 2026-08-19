"""LP-575 — DT-6 stops asking once the payoff question has been answered.

THE CONTRADICTION. DT-6 and DT-8 are about the SAME debt and point opposite ways. DT-6 says the
stated payment is too low and should be raised to the servicer's full PITIA; DT-8 says the payment
should not be in the ratio at all. They are two branches of ONE question — is the obligation retained
past closing, or paid off at it?

On LF-WCHG the answer is paid off (confirmed by hand with the domain expert: 34.39%, not 58.59%), so
DT-6's remedy is the wrong branch. Left unscoped, a processor who applies DT-8 would still be looking
at DT-6 telling them to raise the payment they just removed.

WHY `not_applicable` AND NOT `satisfied`. The stated 3,186.00 and the billed 4,148.28 genuinely
disagree, and always will — marking that `satisfied` would assert the figures reconcile. What changed
is that the disagreement stopped mattering for the ratio, which is scope-false: the rule is
irrelevant to this subject's nature (§8), not passing on its merits.
"""

from __future__ import annotations

from datetime import UTC, datetime
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

_DT6 = load_rule_spec("DT-6")


def _snapshot(*, paid_off: str | None, lender: str = "United Wholesale Mortgage") -> Snapshot:
    """One mortgage statement matched to one stated mortgage liability — LF-WCHG's shape."""
    facts = {
        "liability.1.type": Field.present("MortgageLoan", source=FieldSource.PARSED),
        "liability.1.monthly_payment": Field.present("3186.00", source=FieldSource.PARSED),
        "liability.1.unpaid_balance": Field.present("435012.22", source=FieldSource.PARSED),
        "liability.1.holder_name": Field.present("UNITED WHSLE MORT", source=FieldSource.PARSED),
    }
    if paid_off is not None:
        facts["liability.1.paid_off_at_closing"] = Field.present(
            paid_off, source=FieldSource.PARSED
        )
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
        mismo=MismoSection(facts=facts),
        documents=DocumentsSection.present([statement]),
    )


async def _evaluate(**kw) -> Verdict:
    materialized = await materialize_tags(_snapshot(**kw), only_groups=frozenset())
    evaluations = evaluate_deterministic_rule(_DT6, materialized)
    assert len(evaluations) == 1
    return evaluations[0].verdict


async def test_an_unmarked_liability_still_gets_dt6s_question() -> None:
    """THE BASELINE. Nothing has answered the payoff question, so DT-6 asks its own — the stated
    payment is short of the billed PITIA. This is the state LF-WCHG is in right now."""
    assert await _evaluate(paid_off=None) is Verdict.NEEDS_REVIEW


async def test_a_paid_off_liability_scopes_dt6_out() -> None:
    """THE HEADLINE. Once DT-8's Apply (or the liabilities editor) marks the debt retired at closing,
    DT-6 stops recommending the opposite."""
    assert await _evaluate(paid_off="True") is Verdict.NOT_APPLICABLE


async def test_it_is_not_marked_satisfied() -> None:
    """Explicit, because `satisfied` is the tempting shortcut and it is a false all-clear: 3,186.00
    and 4,148.28 do not reconcile and never will. Only their RELEVANCE changed."""
    assert await _evaluate(paid_off="True") is not Verdict.SATISFIED


async def test_an_explicit_not_paid_off_keeps_dt6_asking() -> None:
    """A processor who says "this property is retained" is answering DT-6's question in the
    affirmative — the payment comparison matters MORE then, not less."""
    assert await _evaluate(paid_off="False") is Verdict.NEEDS_REVIEW


async def test_an_unmatched_statement_is_not_laundered_into_scope_false() -> None:
    """§8, and the reason the predicate is `ne yes` rather than `eq no`. A statement matching no
    stated liability has no marking to read — that is an ABSTAIN, and it must stay in scope and
    resolve to DT-6's own couldnt_check rather than disappear as out-of-scope."""
    verdict = await _evaluate(paid_off=None, lender="Some Other Servicer LLC")

    assert verdict is not Verdict.NOT_APPLICABLE
    assert verdict is Verdict.COULDNT_CHECK


def test_dt6_reads_the_one_matcher_rather_than_a_second() -> None:
    """ADR-375. If the scope tag paired the statement with a different liability than the payment
    comparison used, DT-6 could be scoped out on the strength of a DIFFERENT debt's marking."""
    import inspect

    from app.verification.tag_materialization import derived

    source = inspect.getsource(derived._reo_statement_liability_paid_off)
    assert "_reo_match_statement(snapshot, subject_raw)" in source

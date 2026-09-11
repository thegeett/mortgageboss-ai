"""bug-019 — AS-12 refused to judge a deposit whose source it had already verified.

Four of AS-12's seven findings on LF-XMB2 were couldnt_check, and one of them was an $8,000 deposit
whose own tags read:

    txn.has_identified_source = yes
    txn.source_strength       = verified   ("a matching own-account transfer of exactly $8,000.00
                                             posting on the same date")
    txn.apparent_category     = unknown    ("Description only states 'DEPOSIT ID NUMBER 56195'")

AS-12 asks one question — could this money be BORROWED? — and the file had already answered it. A
judgment rule's gate abstains on any load_bearing tag reading "unknown" BEFORE the model is asked, and
`txn.apparent_category` was in that list: the input the model can least often resolve from a bank line
held a veto over the rule's whole question.

It now sits in `reasoned_over` (the model still sees it, the provenance still carries it) and in
`exempt_when` (which still needs a DEFINITE payroll/interest), while direction and source stay gated.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.ai.rule_judgment import RuleJudgment, RuleJudgmentResult
from app.verification.rule_engine.judgment import evaluate_judgment_rule
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    BorrowerRef,
    DocumentEntry,
    DocumentsSection,
    Snapshot,
    TagsSection,
    TransactionRecord,
)
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio

_AS12 = load_rule_spec("AS-12")


def _f(value: str) -> Field:
    return Field.present(value, source=FieldSource.EXTRACTED)


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


class _Reasoner:
    def __init__(self, value: str = "no") -> None:
        self.value = value
        self.calls = 0

    async def __call__(self, _context_json: str) -> RuleJudgmentResult:
        self.calls += 1
        return RuleJudgmentResult(RuleJudgment(self.value, 0.9, "because"), 1, 1, "stub", False)


async def _evaluate(subject_tags: dict[str, Tag], *, answer: str = "no"):
    """One deposit through the REAL AS-12 spec. $8,000 against a $2,000 income clears the
    materiality floor (50% x 2,000 = 1,000), so every case here reaches the gate."""
    txn = TransactionRecord(
        content_id="t1",
        amount=_f("8000.00"),
        date=_f("2026-03-16"),
        direction=_f("credit"),
        description=_f("DEPOSIT ID NUMBER 56195"),
    )
    doc = DocumentEntry(
        content_id="bs",
        document_type="bank_statement",
        belongs_to=(BorrowerRef(borrower_id=uuid4(), name="Sam"),),
        transactions=(txn,),
    )
    snapshot = Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 9, 11, tzinfo=UTC),
        documents=DocumentsSection.present([doc]),
        tags=TagsSection.present(
            {
                "t1": subject_tags,
                "loan": {
                    "loan.purpose": _tag("purchase"),
                    "dti.qualifying_income_monthly": _tag("2000.00"),
                },
            }
        ),
    )
    materialized = await materialize_tags(snapshot, only_groups=frozenset())
    reasoner = _Reasoner(answer)
    evaluations = await evaluate_judgment_rule(_AS12, materialized, reasoner=reasoner)
    assert len(evaluations) == 1
    return evaluations[0].evaluation, reasoner


# --------------------------------------------------------------------------- #
# The fix
# --------------------------------------------------------------------------- #
async def test_an_unknown_category_with_a_verified_source_is_judged() -> None:
    """THE LF-XMB2 $8,000 DEPOSIT. Its source was found and matched; only the category was unreadable,
    and that alone stopped the rule from saying so."""
    evaluation, reasoner = await _evaluate(
        {
            "txn.is_money_in": _tag("in"),
            "txn.apparent_category": _tag("unknown"),
            "txn.has_identified_source": _tag("yes"),
            "txn.source_strength": _tag("verified"),
        }
    )

    assert evaluation.verdict is Verdict.NEEDS_REVIEW  # a judgment never auto-ships
    assert evaluation.ratification_pending
    assert reasoner.calls == 1, "the model must be asked — the category was never its question"


async def test_an_unknown_category_is_never_exempted() -> None:
    """`exempt_when` clears a deposit on a DEFINITE payroll or interest. Ungating the tag must not turn
    an unreadable category into a free pass: the exemption still fails closed."""
    evaluation, _ = await _evaluate(
        {
            "txn.is_money_in": _tag("in"),
            "txn.apparent_category": _tag("unknown"),
            "txn.has_identified_source": _tag("yes"),
        },
        answer="no",
    )

    assert evaluation.verdict is Verdict.NEEDS_REVIEW
    assert evaluation.ratification_pending, (
        "only a definite payroll/interest may clear without a human"
    )


async def test_a_definite_payroll_still_clears_by_the_guideline() -> None:
    """LP-516 is untouched: the tag still reaches `exempt_when`, so the readily-identifiable exemption
    works exactly as before."""
    evaluation, _ = await _evaluate(
        {
            "txn.is_money_in": _tag("in"),
            "txn.apparent_category": _tag("payroll"),
            "txn.has_identified_source": _tag("yes"),
        },
        answer="no",
    )

    assert evaluation.verdict is Verdict.SATISFIED
    assert evaluation.ratification_pending is False


# --------------------------------------------------------------------------- #
# What must still abstain
# --------------------------------------------------------------------------- #
async def test_an_unknown_direction_still_abstains_with_no_ai_call() -> None:
    """Direction stays gated: a transaction that may be money OUT is not a deposit to judge."""
    evaluation, reasoner = await _evaluate(
        {
            "txn.is_money_in": _tag("unknown"),
            "txn.apparent_category": _tag("transfer_own"),
            "txn.has_identified_source": _tag("yes"),
        }
    )

    assert evaluation.verdict is Verdict.COULDNT_CHECK
    assert reasoner.calls == 0


async def test_an_unknown_source_still_abstains_with_no_ai_call() -> None:
    """The tag that answers AS-12's actual question stays gated. Borrowed-or-not cannot be judged
    without it, and guessing is the one thing this rule must not do."""
    evaluation, reasoner = await _evaluate(
        {
            "txn.is_money_in": _tag("in"),
            "txn.apparent_category": _tag("unknown"),
            "txn.has_identified_source": _tag("unknown"),
        }
    )

    assert evaluation.verdict is Verdict.COULDNT_CHECK
    assert reasoner.calls == 0

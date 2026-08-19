"""LP-551 — FR-5's ratification proof and its scoping, through the real evaluator.

FR-5 is the FIRST rule that reads money OUT. Every other transaction rule scopes
`txn.is_money_in eq in`, so a debt visible only as a recurring bank debit — a private or family loan,
a rent-to-own, anything not reported to the bureaus — was invisible.

IT ACTIVATED ON A SELF-CONSISTENCY RATE, NOT ON MEASURED ACCURACY, so ratification is the entire
safety substitute (ADR-378): every finding it produces must carry `ratification_pending`, or an
unmeasured judgment ships with no human in the loop. That is what the first test proves.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.ai.rule_judgment import RuleJudgment, RuleJudgmentResult
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS, evaluate_rules
from app.verification.rule_engine.result import Verdict
from app.verification.snapshot.model import (
    DocumentEntry,
    DocumentsSection,
    Field,
    Snapshot,
    TagsSection,
    TransactionRecord,
)
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage

pytestmark = pytest.mark.anyio


def _tag(value: str) -> Tag:
    return Tag(
        value=value,
        confidence=None,
        reasoning="fixture",
        source_facts=("t1",),
        produced_by=TagProducedBy.DERIVED,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.B,
    )


def _snapshot(
    *, category: str = "debt_payment", recurring: str = "yes", match: str = "none"
) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 8, 18, tzinfo=UTC),
        documents=DocumentsSection(
            entries=[
                DocumentEntry(
                    content_id="bs",
                    document_type="bank_statement",
                    transactions=(
                        TransactionRecord(
                            content_id="t1",
                            date=Field(value="2025-03-03", source="extracted"),
                            amount=Field(value="451.00", source="extracted"),
                            description=Field(value="CARVANA PAYMENT", source="extracted"),
                            direction=Field(value="debit", source="derived"),
                        ),
                    ),
                )
            ]
        ),
        tags=TagsSection.present(
            {
                "t1": {
                    "txn.is_money_in": _tag("out"),
                    "txn.apparent_category": _tag(category),
                    "txn.is_recurring": _tag(recurring),
                    "txn.stated_liability_match": _tag(match),
                    "txn.amount": _tag("451.00"),
                    "txn.date": _tag("2025-03-03"),
                }
            }
        ),
    )


async def _judge(_context_json: str) -> RuleJudgmentResult:
    return RuleJudgmentResult(
        judgment=RuleJudgment(value="yes", confidence=0.9, reasoning="stub"),
        input_tokens=0,
        output_tokens=0,
        model="stub",
        truncated=False,
    )


async def _evaluate(snapshot: Snapshot):
    results, _ = await evaluate_rules(
        snapshot, judgment_reasoners={"FR-5": _judge}, consistency_reasoners={}, rule_ids=("FR-5",)
    )
    return results


# --------------------------------------------------------------------------------------------- #
# THE RATIFICATION PROOF (LP-490a discipline)
# --------------------------------------------------------------------------------------------- #
async def test_every_fr5_verdict_carries_ratification() -> None:
    """Activated on self-consistency, so a human signs every finding — it can never auto-assert."""
    evaluations = await _evaluate(_snapshot())

    assert evaluations and all(e.ratification_pending is True for e in evaluations)
    assert (
        evaluations[0].verdict is Verdict.NEEDS_REVIEW
    )  # never `fired` — it surfaces, never accuses


def test_fr5_is_live() -> None:
    assert "FR-5" in ACTIVE_RULE_IDS


# --------------------------------------------------------------------------------------------- #
# THE SCOPING — what makes it a finding rather than a list of the borrower's bills
# --------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("match", ["exact", "probable"])
async def test_a_payment_matching_a_disclosed_liability_is_SATISFIED(match: str) -> None:
    """SATISFIED, NOT not_applicable — and the first version had this wrong.

    `not_applicable` means the rule is irrelevant to this loan's NATURE: AS-2's earnest money on a
    refinance, where no earnest money exists. A recurring creditor payment that turns out to be on the
    1003 is not that. The rule APPLIED, looked at it, and found nothing wrong — which is a verdict.

    Putting the comparison in `applicability` made FR-5 silent on a file it had genuinely checked: all
    four of LF-WCHG's recurring payees are disclosed, so the rule examined seven transactions and
    reported nothing at all. It now reports four passes that name the liability each matched."""
    evaluations = await _evaluate(_snapshot(match=match))

    assert evaluations and all(e.verdict is Verdict.SATISFIED for e in evaluations)
    # The exemption clears DETERMINISTICALLY, so no human is asked to ratify a pass a predicate made.
    assert all(e.ratification_pending is False for e in evaluations)


async def test_the_pass_names_the_liability_it_matched() -> None:
    """A processor reading "satisfied" on a fraud-adjacent check is entitled to know WHAT cleared it —
    a deterministic predicate, and which one — rather than trusting that something did."""
    evaluations = await _evaluate(_snapshot(match="exact"))

    assert "stated_liability_match" not in evaluations[0].reasoning  # never the raw tag id
    assert "exact" in evaluations[0].reasoning


async def test_an_application_with_no_liabilities_abstains_rather_than_clearing() -> None:
    """ "unknown" MUST NOT EXEMPT, and the FAIL-CLOSED GATE is what stops it — not the exemption.

    The comparison tag is load-bearing, so an "unknown" value short-circuits to couldnt_check before
    the judgment runs at all. That is the §8 answer and a stronger guarantee than the exemption could
    give: "we could not compare" is a GAP, not a pass and not a review. Treating it as a match would
    hand back a silent all-clear on every recurring creditor payment, on precisely the files carrying
    the least information."""
    evaluations = await _evaluate(_snapshot(match="unknown"))

    assert evaluations and all(e.verdict is Verdict.COULDNT_CHECK for e in evaluations)


async def test_a_one_off_creditor_payment_is_out_of_scope() -> None:
    """A single card payment is ordinary. The rule is about what RECURS."""
    evaluations = await _evaluate(_snapshot(recurring="no"))

    assert all(e.verdict is Verdict.NOT_APPLICABLE for e in evaluations)


async def test_a_recurring_NON_creditor_payment_is_out_of_scope() -> None:
    """A utility or a subscription recurs monthly and is not a debt."""
    evaluations = await _evaluate(_snapshot(category="vendor"))

    assert all(e.verdict is Verdict.NOT_APPLICABLE for e in evaluations)

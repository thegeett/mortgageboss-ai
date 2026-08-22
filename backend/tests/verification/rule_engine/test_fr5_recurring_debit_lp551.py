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


# --------------------------------------------------------------------------- #
# bug-001 — the Apply that adds the liability FR-5's fix text already asks for.
# --------------------------------------------------------------------------- #
async def test_an_undisclosed_payment_carries_the_add(monkeypatch) -> None:
    """The reported case: a recurring creditor payment the 1003 does not state."""
    snapshot = _snapshot(match="none")
    tags = dict(snapshot.tags.by_subject)
    tags["t1"] = dict(tags["t1"]) | {"txn.counterparty": _tag("Carvana")}
    snapshot = snapshot.model_copy(update={"tags": TagsSection.present(tags)})

    (evaluation,) = await _evaluate(snapshot)

    assert evaluation.verdict is Verdict.NEEDS_REVIEW
    assert evaluation.apply == {
        "action": "add_liability",
        "holder_name": "Carvana",
        "monthly_payment": "451.00",
        "liability_type": "Other",
    }


@pytest.mark.parametrize("match", ["exact", "probable"])
async def test_a_disclosed_payment_offers_no_add(match: str) -> None:
    """THE SAFETY, and it is structural rather than a second guard that could drift: `exempt_when`
    clears a matched payee to SATISFIED, and an apply is gated on fired/needs_review — so FR-5
    cannot offer to add a debt the application already states. That is the LP-564 trap, where an
    Apply on an abstention would have duplicated a liability and inflated the very ratio it exists
    to correct."""
    snapshot = _snapshot(match=match)
    tags = dict(snapshot.tags.by_subject)
    tags["t1"] = dict(tags["t1"]) | {"txn.counterparty": _tag("Carvana")}
    snapshot = snapshot.model_copy(update={"tags": TagsSection.present(tags)})

    (evaluation,) = await _evaluate(snapshot)

    assert evaluation.verdict is Verdict.SATISFIED
    assert evaluation.apply is None


async def test_no_payee_means_no_button_rather_than_a_debt_owed_to_nobody() -> None:
    """`_resolve_apply` drops the WHOLE apply when a declared field is unresolvable. A bank fee or a
    cash withdrawal names nobody, and a liability with a payment and no holder is worse than no
    button — the processor could not tell which debt it was."""
    snapshot = _snapshot(match="none")  # no txn.counterparty tag at all

    (evaluation,) = await _evaluate(snapshot)

    assert evaluation.verdict is Verdict.NEEDS_REVIEW  # the finding still stands...
    assert evaluation.apply is None  # ...it just cannot be actioned in one click


async def test_an_unknown_payee_is_not_written_as_a_creditor_called_unknown() -> None:
    snapshot = _snapshot(match="none")
    tags = dict(snapshot.tags.by_subject)
    tags["t1"] = dict(tags["t1"]) | {"txn.counterparty": _tag("unknown")}
    snapshot = snapshot.model_copy(update={"tags": TagsSection.present(tags)})

    (evaluation,) = await _evaluate(snapshot)

    assert evaluation.apply is None

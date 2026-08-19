"""LP-516 — AS-12's readily-identifiable exemption, and the guide's escape hatch.

THE PROBLEM. AS-12 asks, per deposit, whether it suggests an undisclosed BORROWED source. Being a
judgment rule it assigned `NEEDS_REVIEW` unconditionally, so a deposit the model was 95% sure was
payroll still reached a processor. On the first real file that was 10 findings — 4 payroll direct
deposits from the borrower's employer and 6 transfers between the borrower's own accounts — none of
them borrowed-funds candidates, 33% of everything left on the file.

THE GUIDELINE. Fannie B3-4.2-02 (page dated 12/14/2022) exempts a deposit whose source is readily
identifiable on the statement — *"a direct deposit from an employer (payroll), the Social Security
Administration, or IRS or state income tax refund, or a transfer of funds between verified accounts"* —
from needing further explanation. It then adds the escape hatch this file exists to protect:

    "However, if the source of the deposit is printed on the statement, but the lender still has
     questions as to whether the funds may have been borrowed, the lender should obtain additional
     documentation."

SO: ASK-THEN-SUPPRESS. The model is still consulted on every deposit; only a non-"yes" answer is
suppressed. The clearing is done by a DETERMINISTIC predicate, so this is not "auto-clearing a
confident no" — the model's answer can only ever ADD a review, never remove one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.ai.rule_judgment import RuleJudgment, RuleJudgmentResult
from app.verification.rule_engine.judgment import evaluate_judgment_rule
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import _as_conditions, load_rule_spec
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
    """Replays one judgment answer, and records the context it was handed."""

    def __init__(self, value: str) -> None:
        self.value, self.contexts = value, []

    async def __call__(self, context_json: str) -> RuleJudgmentResult:
        self.contexts.append(context_json)
        return RuleJudgmentResult(RuleJudgment(self.value, 0.9, "because"), 1, 1, "stub", False)


async def _evaluate(
    category: str,
    answer: str,
    *,
    amount: str = "2000.00",
    purpose: str | None = "purchase",
    income: str | None = "2000.00",
):
    """One deposit through AS-12.

    LP-518 gave the rule a materiality floor, so the loan tags it sizes the floor from are part of every
    fixture now: at the defaults the floor is 50% x $2,000 = $1,000 and the $2,000 deposit clears it, so
    these cases still reach the model and keep testing what LP-516 wrote them to test. `purpose=None` /
    `income=None` drop a tag to exercise the gate's fail-closed branches.
    """
    txn = TransactionRecord(
        content_id="t1",
        amount=_f(amount),
        date=_f("2026-01-05"),
        direction=_f("credit"),
        description=_f("DIRECT DEP"),
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
        created_at=datetime(2026, 8, 16, tzinfo=UTC),
        documents=DocumentsSection.present([doc]),
        tags=TagsSection.present(
            {
                "t1": {
                    "txn.is_money_in": _tag("in"),
                    "txn.apparent_category": _tag(category),
                    "txn.has_identified_source": _tag("yes"),
                },
                # LP-518 — the LOAN subject, which the materiality floor reads (loan purpose picks the
                # fraction, qualifying income is what the fraction is OF).
                "loan": {
                    **({"loan.purpose": _tag(purpose)} if purpose is not None else {}),
                    **(
                        {"dti.qualifying_income_monthly": _tag(income)}
                        if income is not None
                        else {}
                    ),
                },
            }
        ),
    )
    materialized = await materialize_tags(snapshot, only_groups=frozenset())
    reasoner = _Reasoner(answer)
    evaluations = await evaluate_judgment_rule(_AS12, materialized, reasoner=reasoner)
    assert len(evaluations) == 1
    return evaluations[0].evaluation, reasoner


async def test_a_payroll_deposit_the_model_clears_is_satisfied_not_ratified() -> None:
    """The headline: 4 of LF-WCHG's 10 were exactly this — a direct deposit from the employer."""
    evaluation, _ = await _evaluate("payroll", "no")

    assert evaluation.verdict is Verdict.SATISFIED
    assert evaluation.ratification_pending is False
    # The message must say WHY it cleared. A processor reading "satisfied" on a borrowed-funds check is
    # entitled to know the GUIDELINE did the clearing, not a model.
    assert "no further review is required" in evaluation.reasoning
    assert "payroll" in evaluation.reasoning


async def test_the_guides_escape_hatch_survives_the_exemption() -> None:
    """⚠️ THE DECISIVE TEST. B3-4.2-02: "if ... the lender still has questions as to whether the funds
    may have been borrowed, the lender should obtain additional documentation."

    A readily-identifiable source the model still flags MUST reach a human. If the exemption scoped the
    subject out before the AI were asked, there would be no answer to respect — which is precisely why
    this is ask-then-suppress rather than an applicability predicate.
    """
    evaluation, reasoner = await _evaluate("payroll", "yes")

    assert evaluation.verdict is Verdict.NEEDS_REVIEW
    assert evaluation.ratification_pending is True
    assert reasoner.contexts, "the model must still be ASKED about an exempt-category deposit"


async def test_an_own_account_transfer_is_not_exempt() -> None:
    """⚠️ NOT exempt, deliberately — 6 of LF-WCHG's 10 are this category.

    The guide's exemption is for a transfer between VERIFIED accounts, and nothing in the snapshot can
    establish that (LP-516-A2): `stmt.account_masked` is documented "display only, non-matchable" and a
    transaction's description has every 9+-digit identifier redacted, so neither side of the match
    survives. Exempting on the category alone would apply the guide's conclusion while dropping its
    condition — and on the file this came from the distinction is real: those transfers arrive from a
    credit union whose statements appear nowhere in the file.
    """
    evaluation, _ = await _evaluate("transfer_own", "no")

    assert evaluation.verdict is Verdict.NEEDS_REVIEW
    assert evaluation.ratification_pending is True


async def test_an_undetermined_category_never_exempts() -> None:
    """Fail-closed (§8): an unknown category is data-missing, not scope-false. It must never clear."""
    evaluation, _ = await _evaluate("unknown", "no")

    assert evaluation.verdict is not Verdict.SATISFIED
    assert evaluation.verdict is Verdict.COULDNT_CHECK


async def test_the_model_now_receives_the_amount_and_date_its_prompt_asks_for() -> None:
    """AS-12's prompt asks for "a large round-dollar deposit" and "funds appearing just before closing",
    and the rule was handed neither the amount nor the date — three signals it could not observe.

    `judgment._build_context` builds the context from `reasoned_over` alone, so this asserts the tags
    reach the model rather than merely being declared.
    """
    _, reasoner = await _evaluate("transfer_own", "no", amount="2000.00")

    context = reasoner.contexts[0]
    assert "txn.amount" in context and "2000.00" in context
    assert "txn.date" in context and "2026-01-05" in context


def test_as12_declares_the_exemption_and_its_override() -> None:
    judgment = _AS12.judgment
    assert judgment is not None
    assert judgment.exempt_when is not None
    # LP-517: predicates on the category Stage A/B already produces — a derived `transaction`
    # tag would never materialize on a real run (see the spec comment).
    # LP-518: now a LIST of alternatives (payroll | interest), so every condition is checked.
    conditions = _as_conditions(judgment.exempt_when)
    assert [c.tag for c in conditions] == ["txn.apparent_category"] * len(conditions)
    assert {c.value for c in conditions} == {"payroll", "interest"}
    assert judgment.exempt_unless_judgment_in == ("yes",)
    assert {"txn.amount", "txn.date"} <= set(judgment.reasoned_over)


def test_a_rule_without_an_exemption_still_ratifies_every_verdict() -> None:
    """The change is ADDITIVE. Every other judgment rule must be untouched — a spec declaring no
    exemption keeps the unconditional-ratification behaviour ADR-378 relies on."""
    from app.verification.rule_engine.registry import ACTIVE_RULE_IDS

    exempting = [
        rule_id
        for rule_id in ACTIVE_RULE_IDS
        if (spec := load_rule_spec(rule_id)).judgment is not None
        and spec.judgment.exempt_when is not None
    ]
    # LP-551 — FR-5 JOINED, deliberately and for the same reason. A recurring creditor payment that
    # turns out to be ON the 1003 is the rule applying and finding nothing wrong — a pass, not a scope
    # exclusion — and `exempt_when` is what turns a deterministic predicate into a `satisfied` a human
    # never has to ratify. The invariant this test protects is unchanged: the clearing is done by a
    # PREDICATE, and the model can only ever add a review, never remove one.
    assert exempting == ["AS-12", "FR-5"], (
        "only AS-12 declares a guideline exemption; another judgment rule gaining one silently would "
        f"change what ratification means across the engine (found: {exempting})"
    )


def test_an_override_list_without_a_predicate_is_rejected_at_load() -> None:
    """`exempt_unless_judgment_in` names the answers that OVERRIDE an exemption. With no exemption to
    override it silently does nothing while reading as though it guards something — so it fails loud."""
    from app.verification.rules.specs import JudgmentEval
    from pydantic import ValidationError

    base = {
        "subject": "per_deposit",
        "load_bearing_tags": ("txn.apparent_category",),
        "reasoned_over": ("txn.apparent_category",),
        "output_tag": "as.borrowed_funds",
        "value_domain": ("yes", "no", "unknown"),
        "system_prompt": "x",
    }
    with pytest.raises(ValidationError, match="requires an `exempt_when` predicate"):
        JudgmentEval(**base, exempt_unless_judgment_in=("yes",))


def test_an_override_outside_the_value_domain_is_rejected_at_load() -> None:
    """A typo'd override value would silently never match, leaving the exemption unconditional — the
    exact failure mode this ticket exists to prevent, inverted."""
    from app.verification.rules.specs import JudgmentEval, TagCondition
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="outside value_domain"):
        JudgmentEval(
            subject="per_deposit",
            load_bearing_tags=("txn.apparent_category",),
            reasoned_over=("txn.apparent_category",),
            output_tag="as.borrowed_funds",
            value_domain=("yes", "no", "unknown"),
            system_prompt="x",
            exempt_when=TagCondition(tag="txn.readily_identifiable_source", op="eq", value="yes"),
            exempt_unless_judgment_in=("YES",),
        )

"""LP-518 — AS-12's materiality floor, sized per loan purpose.

THE PROBLEM. LP-516 stopped AS-12 ratifying payroll deposits, but left it asking its borrowed-funds
question of every remaining money-in transaction at ANY amount. A $0.03 savings-interest posting and a
$20,000 wire produced the same review item, because the rule had no notion of size at all.

THE FLOOR, AND WHY IT HAS TWO NUMBERS. Fannie B3-4.2-02 defines the test on a PURCHASE: "A large deposit
is defined as a single deposit that exceeds 50% of the total monthly qualifying income for the loan."
The same page WAIVES it on a refinance — "Documentation or explanation for large deposits is not
required; however, the lender remains responsible for ensuring that any borrowed funds, including any
related liability, are considered." So on a refinance the 50% test is precisely the part set aside, and
the surviving borrowed-funds duty carries no threshold of its own. Inheriting 50% there would import a
test the guide withdrew; the 10% used instead is a deliberate overlay, and the finding shows its
arithmetic so a processor can judge the number rather than take it on faith.

⚠️ These tests do NOT call `materialize_tags`. `dti.qualifying_income_monthly` derives from MISMO stated
income, so materializing a fixture with no MISMO overwrites the injected figure with "unknown" — the
same pattern `test_as1_income_via_loan_tag.py` follows. The derivation itself is covered by
`tag_materialization/test_qualifying_income.py`; what is under test here is the GATE.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
import yaml
from app.ai.rule_judgment import RuleJudgment, RuleJudgmentResult
from app.verification.rule_engine.judgment import evaluate_judgment_rule
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import _SPECS_DIR, load_rule_spec
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

pytestmark = pytest.mark.anyio

_AS12 = load_rule_spec("AS-12")
# $10,000/month makes both floors round numbers: purchase 50% -> $5,000, refinance 10% -> $1,000.
_INCOME = "10000.00"


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
    """Replays one judgment answer, and records whether it was consulted at all."""

    def __init__(self, value: str = "no") -> None:
        self.value, self.calls = value, 0

    async def __call__(self, context_json: str) -> RuleJudgmentResult:
        self.calls += 1
        return RuleJudgmentResult(RuleJudgment(self.value, 0.9, "because"), 1, 1, "stub", False)


async def _evaluate(
    *,
    amount: str,
    purpose: str | None = "purchase",
    income: str | None = _INCOME,
    category: str = "transfer_third_party_in",
    answer: str = "no",
):
    txn = TransactionRecord(
        content_id="t1",
        amount=_f(amount),
        date=_f("2026-01-05"),
        direction=_f("credit"),
        description=_f("ZELLE FROM R PATEL"),
    )
    doc = DocumentEntry(
        content_id="bs",
        document_type="bank_statement",
        belongs_to=(BorrowerRef(borrower_id=uuid4(), name="Sam"),),
        transactions=(txn,),
    )
    loan_tags: dict[str, Tag] = {}
    if purpose is not None:
        loan_tags["loan.purpose"] = _tag(purpose)
    if income is not None:
        loan_tags["dti.qualifying_income_monthly"] = _tag(income)
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
                    "txn.has_identified_source": _tag("no"),
                    "txn.amount": _tag(amount),
                    "txn.date": _tag("2026-01-05"),
                },
                "loan": loan_tags,
            }
        ),
    )
    reasoner = _Reasoner(answer)
    evaluations = await evaluate_judgment_rule(_AS12, snapshot, reasoner=reasoner)
    assert len(evaluations) == 1
    return evaluations[0].evaluation, reasoner


async def test_a_deposit_below_the_purchase_floor_is_scoped_out_silently() -> None:
    """The headline. $2,000 against a $5,000 floor is not a large deposit, so it never reaches a
    processor AND never costs a model call — the gate runs before the AI, which is the whole saving.

    `not_applicable` is never persisted, so this deposit is invisible rather than filed under
    "satisfied". That is deliberate: a processor asked to look at a list of screened-and-cleared small
    deposits is back to the noise the floor exists to remove."""
    evaluation, reasoner = await _evaluate(amount="2000.00")

    assert evaluation.verdict is Verdict.NOT_APPLICABLE
    assert reasoner.calls == 0, "the floor must scope out BEFORE the AI call, not after"


async def test_a_deposit_above_the_purchase_floor_reaches_the_model_and_shows_the_arithmetic() -> (
    None
):
    """⚠️ THE TRANSPARENCY REQUIREMENT. A bare threshold is unauditable — a processor who cannot see
    where $5,000 came from cannot judge whether it is the right number. The finding must carry the
    derivation, not just the verdict."""
    evaluation, reasoner = await _evaluate(amount="8000.00")

    assert evaluation.verdict is Verdict.NEEDS_REVIEW
    assert reasoner.calls == 1
    assert "$8,000 is above the $5,000 (50% of $10,000 qualifying income)" in evaluation.reasoning


async def test_the_same_deposit_is_out_on_a_purchase_and_in_on_a_refinance() -> None:
    """⚠️ THE DECISIVE TEST — the two fractions are not decoration.

    $2,000 sits between the refinance floor ($1,000) and the purchase floor ($5,000). Identical deposit,
    identical income, opposite outcomes. If both purposes ever resolved to one fraction this is the test
    that would catch it, and it encodes the guideline's actual asymmetry: the 50% test is WAIVED on a
    refinance, so the floor that still runs there is a deliberately lower overlay, not an inherited one.
    """
    on_purchase, _ = await _evaluate(amount="2000.00", purpose="purchase")
    on_refinance, reasoner = await _evaluate(amount="2000.00", purpose="refinance")

    assert on_purchase.verdict is Verdict.NOT_APPLICABLE
    assert on_refinance.verdict is Verdict.NEEDS_REVIEW
    assert reasoner.calls == 1
    assert "10% of $10,000 qualifying income" in on_refinance.reasoning


async def test_the_floor_is_strict_so_a_deposit_exactly_at_it_is_out_of_scope() -> None:
    """B3-4.2-02 says a large deposit "EXCEEDS 50%" — at the floor is not over it. Matches AS-1's own
    hard-fire branch on the same guideline, so the two rules cannot disagree at the boundary."""
    evaluation, _ = await _evaluate(amount="5000.00")

    assert evaluation.verdict is Verdict.NOT_APPLICABLE


async def test_an_unknown_income_reviews_at_any_amount_rather_than_reporting_a_gap() -> None:
    """⚠️ THE REGRESSION GUARD, and the reason this gate never emits couldnt_check.

    `dti.qualifying_income_monthly` derives from MISMO STATED income and abstains to "unknown" whenever
    no import states an income line — a large share of real files. The floor is a TRIAGE FILTER this
    rule added, not an input its question needs: "does this deposit suggest borrowed funds?" is still
    answerable from the transaction tags. Failing these subjects to couldnt_check would stop asking the
    model and hand the processor LESS than they had before the gate existed.

    So the deposit proceeds exactly as it did pre-LP-518 — and the finding SAYS the floor did not apply,
    so a quiet degradation can never look like a clean pass."""
    evaluation, reasoner = await _evaluate(amount="1.00", income=None)

    assert evaluation.verdict is Verdict.NEEDS_REVIEW
    assert reasoner.calls == 1
    assert "no materiality floor could be sized" in evaluation.reasoning
    assert "qualifying income is not established" in evaluation.reasoning


async def test_an_unknown_loan_purpose_also_reviews_at_any_amount() -> None:
    """Same contract on the other input: with no purpose there is no fraction to pick, and a rule that
    cannot size its filter must fall back to asking, not to abstaining."""
    evaluation, reasoner = await _evaluate(amount="1.00", purpose=None)

    assert evaluation.verdict is Verdict.NEEDS_REVIEW
    assert reasoner.calls == 1
    assert "no materiality floor could be sized" in evaluation.reasoning


async def test_a_bank_interest_posting_is_exempt_by_citation_not_by_size() -> None:
    """LP-518 added `interest` alongside `payroll` as an ALTERNATIVE exemption.

    The floor already removes the $0.03 case, so this earns its keep in the one place the floor does
    not reach: a low-income refinance, where 10% of a small income can sit BELOW a month's interest on a
    large balance. Clearing that by the guide's readily-identifiable clause is citable; clearing it by
    size is not. The message must name the exemption that actually matched, not the rule's first one."""
    evaluation, _ = await _evaluate(
        amount="900.00", purpose="refinance", income="5000.00", category="interest"
    )

    assert evaluation.verdict is Verdict.SATISFIED
    assert evaluation.ratification_pending is False
    assert "interest" in evaluation.reasoning


async def test_the_guides_escape_hatch_still_overrides_the_widened_exemption() -> None:
    """LP-516's escape hatch must survive the list form: a model answering "yes" on an exempt CATEGORY
    still reaches a human. Asserted on `interest` specifically — the newly added alternative is the one
    that could have been wired to clear unconditionally."""
    evaluation, _ = await _evaluate(
        amount="900.00", purpose="refinance", income="5000.00", category="interest", answer="yes"
    )

    assert evaluation.verdict is Verdict.NEEDS_REVIEW
    assert evaluation.ratification_pending is True


def test_the_purpose_map_covers_every_loan_purpose_the_vocabulary_allows() -> None:
    """⚠️ TOTALITY. A purpose with no entry falls through to "reviewed at any amount" — safe, but it
    silently disables the floor for that whole loan type. If the vocabulary ever gains a third purpose
    (construction, cash-out as its own value), this fails and forces a decision about its fraction."""
    materiality = _AS12.judgment.materiality if _AS12.judgment else None
    assert materiality is not None
    vocabulary = yaml.safe_load(
        (_SPECS_DIR.parent / "vocabulary_extra.yaml").read_text(encoding="utf-8")
    )
    allowed = set(vocabulary["tags"]["loan.purpose"]["allowed_values"])

    assert set(materiality.fraction_by_loan_purpose) == allowed


def test_both_fractions_are_declared_and_the_refinance_one_is_lower() -> None:
    """The ORDERING is the design, not an accident: the refinance floor must be lower, because it is the
    only test still running on that purpose once the guide waives large-deposit documentation."""
    values = _AS12.reference_values.values
    purchase = Decimal(values["materiality_floor_pct_purchase"].rstrip("%"))
    refinance = Decimal(values["materiality_floor_pct_refinance"].rstrip("%"))

    assert purchase == Decimal(50)
    assert refinance < purchase


def test_a_materiality_naming_an_undeclared_reference_key_fails_at_load() -> None:
    """A typo'd key resolves to None at eval time, which degrades EVERY subject to "reviewed at any
    amount" — the rule would look wired while filtering nothing. Catch it at load."""
    from app.verification.rules.specs import RuleSpec
    from pydantic import ValidationError

    body = yaml.safe_load((_SPECS_DIR / "AS-12.yaml").read_text(encoding="utf-8"))
    body["judgment"]["materiality"]["fraction_by_loan_purpose"]["purchase"] = "no_such_key"

    with pytest.raises(ValidationError, match="materiality references reference_values key"):
        RuleSpec(**body)


def test_an_empty_exemption_list_fails_at_load() -> None:
    """`exempt_when: []` is not None, so it would read as "this rule has an exemption" at every site
    while exempting nothing — the LP-516 failure mode (a gate that looks wired and does nothing)."""
    from app.verification.rules.specs import JudgmentEval
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="empty list"):
        JudgmentEval(
            subject="per_deposit",
            load_bearing_tags=("txn.apparent_category",),
            reasoned_over=("txn.apparent_category",),
            output_tag="as.borrowed_funds",
            value_domain=("yes", "no", "unknown"),
            system_prompt="x",
            exempt_when=(),
        )

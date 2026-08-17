"""LP-519 — the split-deposit aggregate, and AS-13 which reads it.

THE GAP THIS CLOSES. LP-518 gave AS-12 a per-deposit materiality floor, which removed the noise and
opened a hole: a $20,000 gift split into five $4,000 transfers is five sub-threshold deposits and
produces ZERO findings. A `per_deposit` rule cannot see that — the judgment context carries one
transaction, the same wall LP-498 recorded for FR-5. So the pattern is found in a LOAN-subject derived
aggregate, where every transaction is visible at once.

WHY GROUP BY AMOUNT AND NOT BY THE FLOOR. The obvious shape — "sum the deposits AS-12's floor scoped
out" — is not buildable: a recipe receives only the snapshot, materialises BEFORE any rule runs, and
cannot read a spec's `reference_values`, so it has no way to know what floor AS-12 applied.
Reimplementing the floor in Python would put a threshold outside the spec and leave two copies to drift.
A split shows up as the same amount more than once, which needs neither a floor nor a counterparty.

⚠️ AS-13 IS INERT. Its bar is `calibratable-now` with `validated: false`, so the eligibility gate
refuses it and it is not in `ACTIVE_RULE_IDS`. Same-amount grouping is a heuristic that has never run
against a real snapshot; activating it would assert a sign-off on unobserved behaviour, which is how
LP-516 shipped a gate that did nothing on a real file. These tests are the constructed evidence; the
activation waits on a real run.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.verification.rule_engine.deterministic import evaluate_deterministic_rule
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.model import Snapshot, TagsSection
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.tag_materialization.derived import _stmt_repeated_money_in_max_total

_TAG = "stmt.repeated_money_in_max_total"


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


def _txn(amount: str, *, direction: str = "in", category: str = "transfer_third_party_in"):
    tags = {"txn.is_money_in": _tag(direction), "txn.apparent_category": _tag(category)}
    if amount is not None:
        tags["txn.amount"] = _tag(amount)
    return tags


def _snapshot(*transactions, loan: dict[str, Tag] | None = None) -> Snapshot:
    subjects = {f"t{i}": tags for i, tags in enumerate(transactions)}
    subjects["loan"] = loan or {}
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 8, 17, tzinfo=UTC),
        tags=TagsSection.present(subjects),
    )


def _aggregate(*transactions) -> tuple[object, str]:
    return _stmt_repeated_money_in_max_total(_snapshot(*transactions), "loan", None)


# ------------------------------------------------------------------------------------------------ #
# THE AGGREGATE
# ------------------------------------------------------------------------------------------------ #
def test_a_split_deposit_is_summed() -> None:
    """The headline: five $4,000 transfers, each individually below any sensible floor, total $20,000."""
    value, reasoning = _aggregate(*[_txn("4000.00") for _ in range(5)])

    assert value == "20000.00"
    assert "5 money-in deposits of 4000.00" in reasoning


def test_the_largest_group_wins_not_the_most_frequent() -> None:
    """Three $100s ($300) vs two $5,000s ($10,000) — the aggregate reports SIZE, so the pair wins.

    A count-based "most repeated" would report the $100 group and miss the $10,000 entirely."""
    value, _ = _aggregate(
        *[_txn("100.00") for _ in range(3)],
        *[_txn("5000.00") for _ in range(2)],
    )

    assert value == "10000.00"


def test_a_lone_deposit_is_not_a_repeat() -> None:
    """A group of one is not a pattern. Without this every file reports its largest single deposit and
    the rule becomes a worse duplicate of AS-1."""
    value, reasoning = _aggregate(_txn("9000.00"), _txn("4000.00"), _txn("100.00"))

    assert value == "0"
    assert "no non-exempt money-in amount appears more than once" in reasoning


def test_payroll_is_excluded_or_every_w2_borrower_fires() -> None:
    """⚠️ NOT optional. A salary paid twice a month IS a repeated same-amount deposit, so counting
    payroll would fire this on essentially every W-2 file and say nothing. Mirrors AS-12's
    `exempt_when`, and for the guideline reason: payroll is readily identifiable on the statement."""
    value, _ = _aggregate(*[_txn("3300.00", category="payroll") for _ in range(4)])

    assert value == "0"


def test_interest_postings_are_excluded_too() -> None:
    value, _ = _aggregate(*[_txn("0.03", category="interest") for _ in range(6)])

    assert value == "0"


def test_money_out_never_counts() -> None:
    """Repeated equal DEBITS are a recurring-liability signal (FR-5's question), not a deposit split.
    Counting them here would answer the wrong question with the right-looking number."""
    value, _ = _aggregate(*[_txn("450.00", direction="out") for _ in range(4)])

    assert value == "0"


# ------------------------------------------------------------------------------------------------ #
# ABSTENTION — every branch, because a wrong 0 reads as "we looked and there is no pattern"
# ------------------------------------------------------------------------------------------------ #
def test_no_deposit_detection_at_all_abstains_rather_than_reporting_zero() -> None:
    """⚠️ absent != none found. With `txn.is_money_in` on no subject, detection never ran; a 0 here
    would false-green the rule on every file whose Stage-A tags failed to materialize. The
    `_stmt_nsf_count` discipline, copied deliberately."""
    value, reasoning = _stmt_repeated_money_in_max_total(_snapshot(), "loan", None)

    assert value == "unknown"
    assert "deposit detection has not run" in reasoning


def test_an_unreadable_direction_abstains() -> None:
    value, _ = _aggregate(_txn("4000.00"), _txn("4000.00", direction="unknown"))

    assert value == "unknown"


def test_an_undetermined_category_abstains_rather_than_assuming_it_is_countable() -> None:
    """An unknown category cannot be told apart from an exempt payroll credit. Counting it could
    over-report; skipping it could under-report. Neither is assertable, so the tag abstains."""
    value, _ = _aggregate(_txn("4000.00"), _txn("4000.00", category="unknown"))

    assert value == "unknown"


def test_a_missing_amount_abstains_because_the_total_would_be_a_lower_bound() -> None:
    value, _ = _aggregate(_txn("4000.00"), _txn(None))

    assert value == "unknown"


def test_absent_tags_abstain() -> None:
    snapshot = Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 8, 17, tzinfo=UTC),
        tags=TagsSection.missing(),
    )
    value, _ = _stmt_repeated_money_in_max_total(snapshot, "loan", None)

    assert value == "unknown"


# ------------------------------------------------------------------------------------------------ #
# AS-13
# ------------------------------------------------------------------------------------------------ #
def _evaluate_as13(repeated: str, income: str = "10000.00"):
    loan = {_TAG: _tag(repeated), "dti.qualifying_income_monthly": _tag(income)}
    snapshot = _snapshot(loan=loan)
    [result] = evaluate_deterministic_rule(load_rule_spec("AS-13"), snapshot)
    return result


def test_as13_surfaces_a_repeated_total_above_the_threshold() -> None:
    """$8,000 of repeats against a $5,000 threshold (50% of $10,000)."""
    result = _evaluate_as13("8000.00")

    assert result.verdict is Verdict.NEEDS_REVIEW
    assert "8000.00" in result.reasoning and "5000.00" in result.reasoning


def test_as13_never_fires_only_ever_asks() -> None:
    """⚠️ needs_review, never `fired` (which persists as `open`, a VIOLATION). Repeated equal deposits have ordinary explanations — a standing
    transfer, a second job paid outside payroll — and this is a fraud-adjacent question where a false
    accusation costs a borrower real time. The rule surfaces a pattern; a human decides."""
    assert _evaluate_as13("8000.00").verdict is not Verdict.FIRED

    outcomes = load_rule_spec("AS-13").deterministic
    assert outcomes is not None
    assert {o.verdict for o in outcomes.outcomes} == {"needs_review", "satisfied"}


def test_as13_is_satisfied_below_the_threshold() -> None:
    assert _evaluate_as13("3000.00").verdict is Verdict.SATISFIED


def test_as13_is_satisfied_when_nothing_repeated() -> None:
    assert _evaluate_as13("0").verdict is Verdict.SATISFIED


def test_as13_abstains_when_the_aggregate_abstained() -> None:
    """The gate must carry the tag's abstention through — an `unknown` aggregate is a gap, not a pass."""
    assert _evaluate_as13("unknown").verdict is Verdict.COULDNT_CHECK


def test_as13_abstains_when_income_is_unknown() -> None:
    """No income, no threshold. Fail-closed: never a 0 threshold, which would surface every file."""
    assert _evaluate_as13("8000.00", income="unknown").verdict is Verdict.COULDNT_CHECK


def test_as13_is_deliberately_inert() -> None:
    """⚠️ THE HOLD, asserted so it cannot be lost. Same-amount grouping is a heuristic that has never
    run against a real snapshot. Activating on constructed cases alone would repeat LP-516, which
    shipped on a prediction and did nothing on the real file. Flip the bar's `validated` after a real
    run — and update this test in the same commit, deliberately."""
    from app.verification.rule_engine.activation_bars import load_activation_bars

    assert "AS-13" not in ACTIVE_RULE_IDS
    bar = load_activation_bars()["AS-13"]
    assert bar.status == "calibratable-now"
    assert bar.validated is False


@pytest.mark.parametrize("rule_id", ["AS-1", "AS-12", "AS-13"])
def test_the_three_deposit_rules_size_on_the_same_income_basis(rule_id: str) -> None:
    """AS-1 (one large deposit), AS-12 (is this one borrowed) and AS-13 (do several add up) must not
    disagree about what "large" means on a file, so all three read the same income tag."""
    spec = load_rule_spec(rule_id)
    text = spec.model_dump_json()

    assert "dti.qualifying_income_monthly" in text

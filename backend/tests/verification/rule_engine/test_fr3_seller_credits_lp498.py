"""LP-498 — FR-3 (unusual seller credits / side agreements), the fraud cohort's one survivor.

EVERY VERDICT ASSERTION RUNS THROUGH A REAL RULE EVALUATION (LP-487's standing rule).

BOTH SEAMS ARE SUPPLIED. A judgment rule calls the model at rule time AS WELL AS at materialization,
so a test must stub `ai_reasoners=` AND pass `judgment_reasoners=`. Stubbing only the first lets the
rule-time call reach the real provider (LP-495b).

WHAT THESE FIXTURES ESTABLISH, stated because it is easy to overclaim: the plumbing works and every
branch is reachable. They establish NOTHING about detecting a real unusual credit — the author knows
the intended answer, so scoring self-authored cases against self-authored logic measures
self-consistency, not correctness (ADR-332, LP-487's amendment). Amounts are invented; no borrower PII.
"""

from __future__ import annotations

import pytest
from app.verification.eval.fire_path_scenarios import (
    build_fr3_fields_absent_snapshot,
    build_fr3_large_unclear_credit_snapshot,
    build_fr3_no_contract_snapshot,
    build_fr3_ordinary_credit_snapshot,
    build_fr3_side_agreement_snapshot,
)
from app.verification.eval.stubs import stub_materialization_reasoners
from app.verification.rule_engine.activation_bars import is_eligible, load_activation_bars
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS, evaluate_rules
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.tag_materialization.declarations import _allowed_values_by_tag
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio


def _judge(value: str):
    """A rule-time judgment reasoner returning a fixed verdict — the SECOND seam."""
    from app.ai.rule_judgment import RuleJudgment, RuleJudgmentResult

    async def _reason(_context_json: str) -> RuleJudgmentResult:
        return RuleJudgmentResult(
            judgment=RuleJudgment(value=value, confidence=0.9, reasoning="scripted"),
            input_tokens=1,
            output_tokens=1,
            model="stub-fr3",
            truncated=False,
        )

    return _reason


async def _evaluate(builder, *, tag_value: str | None, judge: str = "yes"):
    """Materialize with the tag pinned to `tag_value` (None = the group abstains), then evaluate."""

    async def _group(context_json: str):
        import json

        from app.verification.tag_materialization.ai import (
            AiGroupResult,
            AiSubjectJudgment,
            AiTagJudgment,
        )

        subjects = json.loads(context_json).get("subjects", [])
        value = tag_value if tag_value is not None else "unknown"
        return AiGroupResult(
            [
                AiSubjectJudgment(
                    index=int(s["index"]),
                    tags={"unusual_credits": AiTagJudgment(value, 0.9, "stub")},
                )
                for s in subjects
            ],
            input_tokens=1,
            output_tokens=1,
            model="stub",
            truncated=False,
        )

    reasoners = {**stub_materialization_reasoners(), "contract_credits": _group}
    snapshot = await materialize_tags(builder(), ai_reasoners=reasoners)
    return await evaluate_rules(
        snapshot, rule_ids=("FR-3",), judgment_reasoners={"FR-3": _judge(judge)}
    )


# --------------------------------------------------------------------------- #
# The rule SURFACES — it never asserts, and never auto-clears
# --------------------------------------------------------------------------- #
async def test_a_side_agreement_routes_to_needs_review_never_fired() -> None:
    """A judgmental rule has no `fired` and no `satisfied` path — LP-376-B routes every verdict to a
    human. Asserted rather than assumed, and asserted as `is not FIRED` too: a fraud-adjacent rule
    that could fire on its own would be accusing without a human in the loop."""
    evaluations, _ = await _evaluate(
        build_fr3_side_agreement_snapshot, tag_value="yes", judge="yes"
    )
    assert len(evaluations) == 1
    assert evaluations[0].verdict is Verdict.NEEDS_REVIEW
    assert evaluations[0].verdict is not Verdict.FIRED


async def test_every_verdict_carries_ratification() -> None:
    """FR-3's ratification proof, through a real rule evaluation (the LP-490a discipline)."""
    evaluations, _ = await _evaluate(build_fr3_side_agreement_snapshot, tag_value="yes")
    assert evaluations and all(e.ratification_pending is True for e in evaluations)


async def test_an_ordinary_credit_still_routes_to_a_human_not_to_a_clean_pass() -> None:
    """Even a "no" judgment reaches needs_review — the rule reports to a person either way. It does
    not hand back a silent all-clear on a contract it looked at."""
    evaluations, _ = await _evaluate(build_fr3_ordinary_credit_snapshot, tag_value="no", judge="no")
    assert evaluations[0].verdict is Verdict.NEEDS_REVIEW


# --------------------------------------------------------------------------- #
# THE MIRROR — it cannot fire on thin evidence. This cohort's specific requirement.
# --------------------------------------------------------------------------- #
async def test_an_unreadable_contract_abstains_and_costs_nothing() -> None:
    """A contract whose credit fields did not extract must ABSTAIN, never be read as carrying no
    credits and never be surfaced as suspicious.

    Two things are asserted at once. The verdict is couldnt_check — and the applicability predicate is
    the load-bearing tag itself, so the gate resolves "unknown" BEFORE any rule-time model call. The
    judgment reasoner below raises if invoked: an unreadable document must accuse nobody AND cost
    nothing. This is the branch nearly every real corpus file takes today (0/2 field fill).
    """

    async def _must_not_run(_context_json: str):
        raise AssertionError(
            "FR-3 made a rule-time model call on a contract whose fields did not extract — the "
            "applicability predicate should have scoped it off at the gate"
        )

    async def _abstaining_group(context_json: str):
        import json

        from app.verification.tag_materialization.ai import (
            AiGroupResult,
            AiSubjectJudgment,
            AiTagJudgment,
        )

        subjects = json.loads(context_json).get("subjects", [])
        return AiGroupResult(
            [
                AiSubjectJudgment(
                    index=int(s["index"]),
                    tags={"unusual_credits": AiTagJudgment("unknown", 0.9, "fields absent")},
                )
                for s in subjects
            ],
            input_tokens=1,
            output_tokens=1,
            model="stub",
            truncated=False,
        )

    reasoners = {**stub_materialization_reasoners(), "contract_credits": _abstaining_group}
    snapshot = await materialize_tags(build_fr3_fields_absent_snapshot(), ai_reasoners=reasoners)
    evaluations, _ = await evaluate_rules(
        snapshot, rule_ids=("FR-3",), judgment_reasoners={"FR-3": _must_not_run}
    )
    assert evaluations[0].verdict is Verdict.COULDNT_CHECK
    assert evaluations[0].verdict is not Verdict.NEEDS_REVIEW, (
        "an unreadable contract must not be surfaced for review — that is accusing on an absence"
    )


async def test_no_purchase_contract_produces_no_finding_at_all() -> None:
    """A file with no contract has no terms to review. It must not surface: 'we could not check your
    contract' on a file that never had one is noise, and on a fraud-adjacent rule it is worse."""
    evaluations, _ = await _evaluate(build_fr3_no_contract_snapshot, tag_value=None)
    assert evaluations == [] or all(e.verdict is Verdict.NOT_APPLICABLE for e in evaluations), (
        f"expected no finding or not_applicable, got {[e.verdict for e in evaluations]}"
    )


async def test_the_large_credit_route_is_reachable_independently() -> None:
    """The second "yes" route. Both `yes` fixtures must not rest on the side-agreement field alone, or
    the branch would be proven only once."""
    evaluations, _ = await _evaluate(
        build_fr3_large_unclear_credit_snapshot, tag_value="yes", judge="yes"
    )
    assert evaluations[0].verdict is Verdict.NEEDS_REVIEW


# --------------------------------------------------------------------------- #
# The declaration fix, and the bar
# --------------------------------------------------------------------------- #
def test_the_malformed_declaration_is_resolved() -> None:
    """`contract.unusual_credits` was declared `enum: yes | no + detail`, which parsed to the LITERAL
    value "no + detail" — a value no model would return and no rule could match. LP-495c catalogued it
    and left it because the tag was unmaterialized; materializing it required fixing it first."""
    allowed = _allowed_values_by_tag()["contract.unusual_credits"]
    assert allowed == ("yes", "no", "unknown")
    assert "no + detail" not in allowed


def test_fr3_carries_no_threshold_by_design() -> None:
    """ "Side agreement" has no guideline threshold, and the IPC cap is PC-4's question (agency-gated to
    LP-509). A number here would be invented, which ADR-361 forbids."""
    spec = load_rule_spec("FR-3")
    assert spec.reference_values.values == {}
    assert spec.reference_values.threshold_needs_signoff is False
    assert spec.numeric_check is False


def test_fr3_is_active_on_a_measured_self_consistency_rate() -> None:
    bars = load_activation_bars()
    bar = bars["FR-3"]
    assert "FR-3" in ACTIVE_RULE_IDS
    assert is_eligible(bar)
    assert bar.status == "ratify-pending"
    assert bar.ships == "ratify", "a judgmental rule never auto-ships"
    assert bar.self_consistency_rate == 1.0
    assert bar.self_consistency_cases == 4
    assert bar.measured_accuracy is None, (
        "the rate is self-consistency, not accuracy against labels — conflating them is what "
        "ratify-pending exists to prevent"
    )


def test_the_other_five_fraud_rules_are_held() -> None:
    """Each is held for a reason established in Phase A. This fails if one is activated without that
    reason being addressed."""
    for rule_id in ("FR-1", "FR-2", "FR-4", "FR-5", "FR-6"):
        assert rule_id not in ACTIVE_RULE_IDS, f"{rule_id} activated — see LP-498 Phase A"

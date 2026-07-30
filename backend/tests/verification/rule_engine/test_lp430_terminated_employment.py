"""LP-430 — the terminated-employment documentation rule (IN-15), Priya's B14 SEPARATE check.

Her ruling (LP-393-6 → LP-430): a terminated job's 2 years still count as HISTORY (IN-11's concern), but
whether it is documented as CURRENT is a separate check — ANY past VOE end date requires a subsequent pay
stub. DETERMINISTIC (income.terminated_employment, derived per-borrower from income.employment_end +
income.pay_date — two date facts) → no AI, no calibration (ADR-334). These tests pin every branch (fire /
satisfy / future-n/a / no-VOE-n/a), the reason DISCIPLINE (asks for the document, never asserts unemployment,
distinct from IN-11), per-borrower isolation, the borrower-subject match, and the activation (no-ai-dependency,
34 -> 35). The live-reasoner IN-11 boundary observation is in docs/tickets/LP-430.md.
"""

from __future__ import annotations

import pytest
from app.verification.eval.fire_path_scenarios import (
    _terminated_borrower,
    build_terminated_employment_snapshot,
)
from app.verification.eval.stubs import stub_materialization_reasoners
from app.verification.rule_engine.activation_bars import (
    eligible_rule_ids,
    is_eligible,
    load_activation_bars,
)
from app.verification.rule_engine.registry import _BASE_ACTIVE, ACTIVE_RULE_IDS, evaluate_rules
from app.verification.rule_engine.result import Verdict
from app.verification.tag_materialization.producer import materialize_tags
from tests.expected_active import EXPECTED_ACTIVE_RULE_COUNT

pytestmark = pytest.mark.anyio


async def _verdicts() -> dict[str, tuple[Verdict, str]]:
    """IN-15's verdict + reason per borrower on the terminated-employment scenario (keyless: parsed +
    derived are deterministic; the AI stub is irrelevant — IN-15 reads only the derived tag)."""
    snap = await materialize_tags(
        build_terminated_employment_snapshot(), ai_reasoners=stub_materialization_reasoners()
    )
    results, _ = await evaluate_rules(snap, rule_ids=("IN-15",))
    by_borrower = {str(_terminated_borrower(i)): i for i in range(1, 5)}
    return {
        f"B{by_borrower[r.subject_id]}": (r.verdict, r.reasoning)
        for r in results
        if r.subject_id in by_borrower
    }


# ======================================================================= #
# The four branches (Priya's ruling: any past end date fires; one subsequent pay stub clears)
# ======================================================================= #
async def test_past_end_date_no_pay_stub_fires() -> None:
    verdict, reason = (await _verdicts())["B1"]
    assert verdict is Verdict.FIRED
    assert "2026-05-01" in reason  # the end date is interpolated (the IH-3/PC-7 pattern)


async def test_past_end_date_with_subsequent_pay_stub_is_satisfied() -> None:
    verdict, _ = (await _verdicts())["B2"]
    assert (
        verdict is Verdict.SATISFIED
    )  # a pay stub dated after the end date (any employer) clears it


async def test_future_end_date_is_not_applicable() -> None:
    # a FUTURE end date is a continuation concern (IN-13's territory), NOT a termination → out of scope.
    verdict, _ = (await _verdicts())["B3"]
    assert verdict is Verdict.NOT_APPLICABLE


async def test_no_voe_is_not_applicable_not_a_finding() -> None:
    # D4: no VOE → the rule cannot apply → not_applicable, NEVER a finding on a missing document.
    verdict, _ = (await _verdicts())["B4"]
    assert verdict is Verdict.NOT_APPLICABLE


# ======================================================================= #
# The reason DISCIPLINE — asks for the document, never asserts unemployment, distinct from IN-11
# ======================================================================= #
async def test_the_fired_reason_asks_for_the_document_never_asserts_unemployment() -> None:
    _verdict, reason = (await _verdicts())["B1"]
    low = reason.lower()
    assert "pay stub dated after" in low  # it ASKS FOR THE DOCUMENT (a file gap, not a fact)
    assert "confirm current employment" in low
    for forbidden in ("unemploy", "not employed", "no longer employed", "lost"):
        assert forbidden not in low, forbidden  # NEVER a claim about the borrower


async def test_the_reason_is_distinct_from_in11() -> None:
    # The IN-11 boundary (D2): a terminated job must never surface TWO overlapping findings. IN-11 speaks to
    # 2-year HISTORY; IN-15 speaks to the pay-stub DOCUMENTATION — provably distinct wording + distinct tags.
    from app.verification.rules.specs import load_rule_spec

    _verdict, in15_reason = (await _verdicts())["B1"]
    assert "history" not in in15_reason.lower()  # not IN-11's concern
    in11 = load_rule_spec("IN-11").deterministic
    in15 = load_rule_spec("IN-15").deterministic
    assert in11 is not None and in15 is not None
    assert set(in11.load_bearing_tags).isdisjoint(
        in15.load_bearing_tags
    )  # different tags, no overlap


# ======================================================================= #
# Per-borrower isolation + the subject match (anti-structural-death)
# ======================================================================= #
async def test_per_borrower_isolation_b2_pay_stub_does_not_clear_b1() -> None:
    # B1 (a terminated job, no pay stub) FIRES even though B2 HAS a pay stub — a borrower's documents never
    # speak for another's (belongs_to attribution). If isolation broke, B1 would read as cleared.
    v = await _verdicts()
    assert v["B1"][0] is Verdict.FIRED and v["B2"][0] is Verdict.SATISFIED


async def test_the_derived_tag_materializes_at_the_borrower_subject() -> None:
    # The subject match (ID-5 anti-structural-death): the per-document VOE/pay-stub facts promote to a
    # per-BORROWER income.terminated_employment tag, which the per-borrower rule reads.
    snap = await materialize_tags(
        build_terminated_employment_snapshot(), ai_reasoners=stub_materialization_reasoners()
    )
    for i, expected in (
        (1, "needs_pay_stub"),
        (2, "cleared"),
        (3, "not_terminated"),
        (4, "not_terminated"),
    ):
        tags = snap.tags.by_subject.get(str(_terminated_borrower(i)), {})
        assert "income.terminated_employment" in tags  # produced at the borrower subject
        assert tags["income.terminated_employment"].value == expected


# ======================================================================= #
# Activation — no-ai-dependency, deterministic → live (34 -> 35); IN-11/IN-12 untouched
# ======================================================================= #
def test_in15_is_active_and_the_invariant_holds() -> None:
    bar = load_activation_bars()["IN-15"]
    assert bar.status == "no-ai-dependency" and bar.threshold is None
    assert bar.ships == "auto" and not bar.load_bearing_ai_tags  # deterministic, no AI tag
    assert is_eligible(bar) and "IN-15" in ACTIVE_RULE_IDS
    assert len(ACTIVE_RULE_IDS) == EXPECTED_ACTIVE_RULE_COUNT == 35
    assert set(ACTIVE_RULE_IDS) - set(_BASE_ACTIVE) == set(eligible_rule_ids())


def test_in11_and_in12_are_untouched_and_still_live() -> None:
    assert {"IN-11", "IN-12"} <= set(ACTIVE_RULE_IDS)

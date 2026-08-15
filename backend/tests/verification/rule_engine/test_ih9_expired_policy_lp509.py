"""LP-509-D1 — IH-9, the expired hazard policy. The finding LF-WCHG should have produced and did not.

That file carried an ACORD 27 running 06/25/2024 to 06/25/2025 — THIRTEEN MONTHS LAPSED while it was being
processed — and none of its 162 findings mentioned it. It is the single thing a processor would most want to
know about the file, and the engine was silent.

WHY. IH-3 was the only rule reading that binder's dates, and it compares the EFFECTIVE date to the CLOSING
date. LF-WCHG has no closing date, so IH-3's gate abstained before reaching any outcome — a couldnt_check
ABOUT CLOSING swallowed a fact that is true regardless of closing.

That is why IH-9 is a separate rule and not an extra outcome on IH-3: an outcome there would sit behind the
same gate on `contract.loan_closing_date` and reproduce the defect exactly. The decisive test below is
`test_fires_with_no_closing_date_on_the_file` — the LF-WCHG shape, where IH-3 must still abstain and IH-9 must
fire anyway.
"""

from __future__ import annotations

import pytest
from app.verification.eval.fire_path_scenarios import (
    build_insurance_current_snapshot,
    build_insurance_expired_no_closing_date_snapshot,
    build_insurance_expired_snapshot,
)
from app.verification.eval.lf6t3n_fixture import build_lf6t3n_snapshot
from app.verification.rule_engine.deterministic import evaluate_deterministic_rule
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.model import Snapshot
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio

_LOAN = "loan"
_IH9 = load_rule_spec("IH-9")
_IH3 = load_rule_spec("IH-3")


async def _materialize(snap: Snapshot) -> Snapshot:
    """Parsed + derived only — IH-9's whole chain is keyless, which is why it needs no calibration."""
    return await materialize_tags(snap, only_groups=frozenset())


async def _verdict(snap: Snapshot, spec=_IH9) -> Verdict:
    results = evaluate_deterministic_rule(spec, await _materialize(snap))
    assert len(results) == 1, f"expected one loan-level evaluation, got {len(results)}"
    return results[0].verdict


async def test_an_expired_policy_fires() -> None:
    mat = await _materialize(build_insurance_expired_snapshot())
    tag = mat.tags.by_subject[_LOAN]["ins.policy_expired"]
    assert str(tag.value) == "yes"
    # The processor is shown the dates and the size of the lapse, not just a conclusion.
    assert "2025-06-25" in tag.reasoning and "2026-07-01" in tag.reasoning
    assert "371 day(s)" in tag.reasoning

    (result,) = evaluate_deterministic_rule(_IH9, mat)
    assert result.verdict is Verdict.FIRED
    assert result.how_to_fix


async def test_fires_with_no_closing_date_on_the_file() -> None:
    """⚠️ THE DEFECT, DIRECTLY. The LF-WCHG shape: a lapsed policy, no closing date.

    IH-3 must abstain — it genuinely cannot compare an effective date to a closing date that is not
    there. IH-9 must fire regardless. If a future change ever routes the expiry conclusion through a
    closing-date gate, this is the test that fails.
    """
    snap = build_insurance_expired_no_closing_date_snapshot()
    assert await _verdict(snap, _IH3) is Verdict.COULDNT_CHECK
    assert await _verdict(snap, _IH9) is Verdict.FIRED


async def test_a_current_policy_does_not_fire() -> None:
    """The must-not-fire direction — a rule that fires on everything reports nothing."""
    assert await _verdict(build_insurance_current_snapshot()) is Verdict.SATISFIED


async def test_no_binder_abstains_and_never_clears() -> None:
    """A missing binder is couldnt_check, NEVER satisfied.

    Hazard insurance is required on every mortgage, so an absent binder is an honest gap and not
    scope-false. Clearing on absence would report "the policy has not expired" about a file that has
    no policy at all — the §8 rule that a check must never pass on missing evidence. LF-6T3N carries
    no binder, which makes it the real fixture for this.
    """
    assert await _verdict(build_lf6t3n_snapshot()) is Verdict.COULDNT_CHECK


async def test_the_expiry_tag_reads_only_homeowners_binders() -> None:
    """`expiration_date` is a field name several extractors emit (flood policy, insurance quote), and a
    document tag is scoped by FIELD NAME rather than document type — so an unscoped read would let a
    flood policy's date decide the hazard verdict, or manufacture a false disagreement that suppresses
    it. The same leak `_loan_effective_date` guards against.
    """
    from app.verification.eval.fire_path_scenarios import _doc, _snapshot

    snap = _snapshot(
        build_insurance_expired_snapshot().loan_file_id,
        [
            # A FLOOD policy that expired long ago — must not drive the HAZARD verdict.
            _doc(
                "95-flood-old",
                "flood_insurance_policy",
                policy_number="FL-1",
                expiration_date="2020-01-01",
            )
        ],
    )
    mat = await _materialize(snap)
    tag = mat.tags.by_subject.get(_LOAN, {}).get("ins.policy_expired")
    assert tag is not None and str(tag.value) == "unknown"
    assert "no homeowners insurance binder states an expiration date" in tag.reasoning


def test_ih9_is_live_and_earned_it_through_the_activation_gate() -> None:
    """Eligible on `no-ai-dependency` alone: a parsed binder date and an exact compare — no AI tag in the
    chain to calibrate and no threshold to sign off (the IH-3 shape)."""
    from app.verification.rule_engine.activation_bars import eligible_rule_ids

    assert "IH-9" in ACTIVE_RULE_IDS
    assert "IH-9" in eligible_rule_ids()


def test_ih9_does_not_depend_on_the_closing_date_tag() -> None:
    """Structural, not behavioural: the closing date must not appear anywhere in IH-9's inputs.

    The behavioural test above proves today's wiring; this one states the CONSTRAINT, so that adding a
    closing-date operand "for context" fails loudly rather than quietly re-gating the rule.
    """
    assert _IH9.deterministic is not None
    tags = set(_IH9.deterministic.load_bearing_tags) | set(_IH9.deterministic.gated_tags)
    assert tags == {"ins.policy_expired"}
    assert not any("closing" in t for t in tags)

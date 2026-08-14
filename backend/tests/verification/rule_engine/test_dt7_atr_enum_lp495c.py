"""LP-495c — the AI-enum abstain reconciliation, and DT-7's activation on it.

THE DEFECT, in three composing facts:
  1. `_build_tag` coerces any model value outside a tag's declared `allowed_values` to
     `_unknown_tag(...)`, which sets **confidence=None**. A genuine IN-vocabulary "unknown" instead
     keeps the model's own confidence.
  2. `_scan_tag_degradations` matches the fail-closed marker STRUCTURALLY: value == "unknown" AND
     produced_by == AI AND confidence is None.
  3. `VerificationRun.degraded` is `bool(self.degradations)`.

So for any tag whose PROMPT sanctions "unknown" but whose DECLARATION omits it, every run in which
the model honestly abstained was reported as a degraded run — and degradation is meant to signal a
broken pipeline (logged at ERROR), not a legitimate abstain.

FOUR tags had it. The fix is one word each, upstream in `docs/snapshot-fact-tags.xlsx`, with
`fact_tags.csv` regenerated from it — the CSV cannot be hand-edited (the next regeneration silently
reverts it) and `vocabulary_extra.yaml` refuses to shadow an xlsx tag by design.
"""

from __future__ import annotations

import pytest
from app.verification.eval.lf6t3n_fixture import build_lf6t3n_snapshot
from app.verification.eval.stubs import stub_materialization_reasoners
from app.verification.rule_engine.activation_bars import load_activation_bars
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS, evaluate_rules
from app.verification.tag_materialization.ai import AiTagJudgment, _build_tag
from app.verification.tag_materialization.declarations import _allowed_values_by_tag
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio

# The four tags whose prompt sanctioned an abstain their declaration omitted. Found by auditing every
# AI-produced enum against its producer prompt with a WINDOW match, not a line match — the original
# line-based pass missed `stmt.is_reserve_eligible`, whose prompt puts the sanctioned "unknown" on a
# different line from the tag name.
_RECONCILED = {
    "dti.atr_factors_documented": ("complete", "incomplete", "unknown"),
    "txn.is_nsf_or_overdraft": ("yes", "no", "unknown"),
    "liab.in_application": ("yes", "no", "unknown"),
    "stmt.is_reserve_eligible": ("yes", "no", "partial", "unknown"),
}


def test_all_four_declarations_carry_the_abstain_their_prompt_sanctions() -> None:
    allowed = _allowed_values_by_tag()
    for tag_id, expected in _RECONCILED.items():
        assert allowed[tag_id] == expected, f"{tag_id} lost its abstain"


def test_an_in_vocabulary_abstain_keeps_its_confidence_and_stops_degrading() -> None:
    """THE MECHANISM, proven rather than asserted.

    A model returning "unknown" with real confidence must produce a tag that KEEPS that confidence, so
    it no longer matches the degradation scan's structural marker. This is the whole ticket in one
    assertion — before the reconciliation each of these produced confidence=None.
    """
    allowed = _allowed_values_by_tag()
    for tag_id in _RECONCILED:
        judgment = AiTagJudgment("unknown", 0.9, "cannot determine from this document")
        tag = _build_tag(judgment, allowed[tag_id], "subject-1", "absent")
        assert tag.value == "unknown"
        assert tag.confidence == 0.9, f"{tag_id}: an in-vocabulary abstain must keep its confidence"
        marker = tag.value == "unknown" and tag.produced_by.value == "ai" and tag.confidence is None
        assert not marker, f"{tag_id} still matches the degradation marker"


def test_the_fix_is_targeted_not_a_blanket_disabling() -> None:
    """THE CONTROL CASE, and it matters as much as the fix.

    `income.voe_present` is declared yes|no and its prompt genuinely offers NO abstain, so declaration
    and prompt agree and there is nothing to reconcile. A model returning "unknown" there IS
    off-vocabulary, and it must still fail closed. If this ever starts keeping its confidence, the
    reconciliation has been over-applied and the fail-closed mechanism is silently disabled.
    """
    allowed = _allowed_values_by_tag()
    assert allowed["income.voe_present"] == ("yes", "no")
    tag = _build_tag(
        AiTagJudgment("unknown", 0.9, "n/a"), allowed["income.voe_present"], "s", "absent"
    )
    assert tag.confidence is None, "an off-vocabulary value must still fail closed"


async def test_none_of_the_four_degrades_a_real_run() -> None:
    """End to end through the real degradation scan, not the mechanism in isolation.

    The stubs abstain honestly for all four now (they previously emitted a substantive "no" precisely
    to dodge this), so a full stubbed run must carry no tag-level degradation from any of them.
    """
    from app.services.verification_run import _scan_tag_degradations

    snapshot = await materialize_tags(
        build_lf6t3n_snapshot(), ai_reasoners=stub_materialization_reasoners()
    )
    degraded_subjects = {d.subject for d in _scan_tag_degradations(snapshot) if d.subject}
    for tag_id in _RECONCILED:
        assert not any(s.endswith(tag_id) for s in degraded_subjects), (
            f"{tag_id} still degrades a run"
        )


async def test_every_dt7_verdict_carries_ratification() -> None:
    """DT-7's ratification proof, through a REAL rule evaluation (the LP-490a discipline).

    DT-7 is judgmental and ships `ratify`, so LP-376-B routes every verdict to a human — there is no
    auto-satisfied path. This runs the real evaluator rather than calling the ratification mechanism.
    """
    snapshot = await materialize_tags(
        build_lf6t3n_snapshot(), ai_reasoners=stub_materialization_reasoners()
    )
    evaluations, _tags = await evaluate_rules(snapshot, rule_ids=("DT-7",))
    assert evaluations, "DT-7 is loan-scoped and must produce an evaluation"
    for evaluation in evaluations:
        assert evaluation.ratification_pending is True, (
            "a ratify-pending judgment rule must route every verdict to a human"
        )


def test_dt7_activated_on_the_rate_lp495b_measured() -> None:
    """Activated on the EXISTING measurement — nothing was re-derived and no model was called here.

    `measured_accuracy` stays null: the 1.0000 is a SELF-CONSISTENCY rate (does the model agree with
    itself across a fresh-context re-derivation), not an accuracy against labels, and conflating the
    two is what the ratify-pending status exists to avoid.
    """
    bar = load_activation_bars()["DT-7"]
    assert "DT-7" in ACTIVE_RULE_IDS
    assert bar.status == "ratify-pending"
    assert bar.ships == "ratify"
    assert bar.self_consistency_rate == 1.0
    assert bar.self_consistency_cases == 4
    assert bar.self_consistency_disagreements == 0
    assert bar.measured_accuracy is None

"""LP-495a — OC-1 (occupancy consistency), activated on a SELF-CONSISTENCY rate (ADR-378).

⚠️ EVERY VERDICT ASSERTION RUNS THROUGH A REAL RULE EVALUATION (LP-487's standing rule), and the
RATIFICATION PROOF in particular runs through `materialize_tags()` → `evaluate_rules()` rather than
calling `ratifies_every_finding` — ratification is the ENTIRE safety substitute for the missing
measurement, so proving it by calling the mechanism would prove nothing (LP-508's lesson).

⚠️ THE TAG IS NOT RE-KINDED. `occupancy.consistent_with_signals` stays `ai`. It is SHARED with LIVE
OC-2, so re-kinding it is a behaviour change on shipped code and needs its own regression evidence — a
test below pins that it is still declared `ai` and still consumed by both rules.

⚠️ THE LP-406-4 ACTIVATION PRECONDITION IS RESOLVED BY THE STATUS, NOT BY CHANGING OC-2. The precondition
was that OC-1 would AUTO-ship while live OC-2 RATIFIES the same tag. On `ratify-pending` both rules route
to a human, so the double-surface is two ratified prompts rather than an auto-assertion racing a
ratification. Live OC-2 is untouched.

⚠️ THE SEAM IS ALWAYS FULL: `{**stub_materialization_reasoners(), "occupancy": ...}`. A partial seam is
not a seam — LP-490 spent real money discovering that, and LP-494 repeated it.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from app.verification.eval.stubs import stub_materialization_reasoners
from app.verification.rule_engine.activation_bars import (
    is_eligible,
    load_activation_bars,
    ratifies_every_finding,
)
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS, evaluate_rules
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    DocumentsSection,
    MismoSection,
    Snapshot,
    TagsSection,
)
from app.verification.tag_materialization.ai import (
    AiGroupResult,
    AiSubjectJudgment,
    AiTagJudgment,
)
from app.verification.tag_materialization.declarations import load_declarations
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio

_LOAN = UUID("95000000-0000-4000-8000-0000000000a1")
_TAG = "occupancy.consistent_with_signals"
_FILE_DATE = datetime(2026, 7, 1, tzinfo=UTC)


def _occupancy_reasoner(value: str):
    """A seam returning ONE occupancy answer, in-vocabulary."""

    async def reasoner(context_json: str) -> AiGroupResult:
        subjects = json.loads(context_json).get("subjects", [])
        return AiGroupResult(
            [
                AiSubjectJudgment(
                    index=int(s["index"]),
                    tags={
                        "consistent_with_signals": AiTagJudgment(
                            value, 0.95, "the declarations were compared"
                        )
                    },
                )
                for s in subjects
            ],
            input_tokens=1,
            output_tokens=1,
            model="stub",
            truncated=False,
        )

    return reasoner


def _snapshot(occupancy: str | None = "primary_residence") -> Snapshot:
    mismo = (
        {"property.occupancy": Field.present(occupancy, source=FieldSource.PARSED)}
        if occupancy is not None
        else {}
    )
    return Snapshot(
        loan_file_id=_LOAN,
        run_id=uuid4(),
        created_at=_FILE_DATE,
        documents=DocumentsSection.present([]),
        mismo=MismoSection.present(mismo),
        tags=TagsSection.present({}),
    )


async def _evaluate(value: str, occupancy: str | None = "primary_residence"):
    # ⚠️ THE FULL SEAM — every declared group stubbed, then `occupancy` overridden.
    reasoners = {**stub_materialization_reasoners(), "occupancy": _occupancy_reasoner(value)}
    snapshot = await materialize_tags(_snapshot(occupancy), ai_reasoners=reasoners)
    evaluations, _tags = await evaluate_rules(snapshot, rule_ids=("OC-1",))
    return evaluations


# --------------------------------------------------------------------------- #
# The verdicts, through a real evaluation
# --------------------------------------------------------------------------- #
async def test_agreeing_declarations_are_satisfied() -> None:
    evaluations = await _evaluate("yes")
    assert [e.verdict for e in evaluations] == [Verdict.SATISFIED]


async def test_a_contradicting_declaration_fires() -> None:
    """⚠️ Unlike RE-1/DT-6/LO-2, OC-1 DOES fire — a borrower's own 1003 declarations contradicting each
    other is a defect the file must resolve, not an inference handed to a processor."""
    evaluations = await _evaluate("no")
    assert [e.verdict for e in evaluations] == [Verdict.FIRED]


async def test_an_unknown_signal_couldnt_checks_and_never_clears() -> None:
    """⚠️ THE ABSTAIN THAT MATTERS, and it is 9 of the 19 real files: a loan stating an occupancy with NO
    other declaration to compare it against must not read as consistent."""
    evaluations = await _evaluate("unknown")
    assert [e.verdict for e in evaluations] == [Verdict.COULDNT_CHECK]
    assert all(e.verdict is not Verdict.SATISFIED for e in evaluations)


async def test_no_stated_occupancy_never_clears() -> None:
    evaluations = await _evaluate("yes", occupancy=None)
    assert all(e.verdict is not Verdict.SATISFIED for e in evaluations)


# --------------------------------------------------------------------------- #
# ⚠️ THE RATIFICATION PROOF — through a real evaluation, per LP-490a's requirement
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("value,expected", [("no", Verdict.FIRED), ("yes", Verdict.SATISFIED)])
async def test_every_oc1_finding_carries_ratification(value: str, expected: Verdict) -> None:
    """⚠️ RATIFICATION IS THE ENTIRE SAFETY SUBSTITUTE for the missing measurement (ADR-378), so it is
    proven HERE — through materialisation and the real evaluator — not by calling the mechanism.

    Including `satisfied`: a wrong `satisfied` is exactly what would clear a file whose occupancy
    declarations conflict, and occupancy is the borrower-side defect that pricing, LTV limits and the
    reps-and-warrants all key on."""
    evaluations = await _evaluate(value)
    findings = [e for e in evaluations if e.verdict is not Verdict.NOT_APPLICABLE]
    assert findings, "OC-1 produced no findings to check"
    assert [e.verdict for e in findings] == [expected]
    assert all(e.ratification_pending for e in findings), (
        "OC-1 shipped a finding with no human in the loop: "
        f"{[(e.subject_id, e.verdict.value) for e in findings if not e.ratification_pending]}"
    )


# --------------------------------------------------------------------------- #
# The activation record
# --------------------------------------------------------------------------- #
def test_oc1_is_active_on_a_self_consistency_rate() -> None:
    assert "OC-1" in ACTIVE_RULE_IDS
    bar = load_activation_bars()["OC-1"]
    assert bar.status == "ratify-pending"
    assert bar.self_consistency_rate == pytest.approx(0.9474, abs=1e-4)
    assert bar.self_consistency_cases == 19
    assert bar.self_consistency_disagreements == 1
    assert bar.self_consistency_model == "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    assert bar.input_resolves is True
    # ⚠️ LOAD-BEARING: a rule whose tag was MEASURED and FAILED is measured-and-failing, not unmeasured,
    # and must stay held. A self-consistency rate must never override a real measurement.
    assert bar.measured_accuracy is None
    assert is_eligible(bar)
    assert ratifies_every_finding("OC-1")


def test_the_occupancy_tag_is_not_rekinded_and_is_shared_with_live_oc2() -> None:
    """⚠️ THE FENCE. `occupancy.consistent_with_signals` is SHARED with LIVE OC-2. Re-kinding it to
    deterministic is a behaviour change on shipped code and needs its own Phase A and regression
    evidence — it was explicitly NOT done here. If someone re-kinds it, this fails."""
    from app.verification.tag_materialization.declarations import ProductionMode

    decl = load_declarations()[_TAG]
    assert decl.mode is ProductionMode.AI, (
        "occupancy.consistent_with_signals was re-kinded — it is shared with LIVE OC-2, so that is a "
        "behaviour change on shipped code and needs its own ticket"
    )
    assert "OC-2" in ACTIVE_RULE_IDS
    assert _TAG in load_rule_spec("OC-1").deterministic.load_bearing_tags
    # OC-2 is a judgment rule that reasons over the same tag — the shared consumption this fence is about.
    assert _TAG in load_rule_spec("OC-2").judgment.reasoned_over


def test_oc1_and_oc2_both_route_to_a_human() -> None:
    """⚠️ THE LP-406-4 ACTIVATION PRECONDITION, RESOLVED. It warned that activating OC-1 would
    double-surface a "no" file as OC-1 AUTO + OC-2 ratify. On `ratify-pending` OC-1 ratifies too, so the
    double-surface is two ratified prompts and no auto-assertion. Live OC-2 is UNCHANGED."""
    assert ratifies_every_finding("OC-1")
    spec = load_rule_spec("OC-2")
    assert spec.judgment is not None, "OC-2 is still the judgment rule that ratifies every verdict"

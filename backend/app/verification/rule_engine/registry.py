"""The rule registry + GENERIC dispatch (LP-324/325) — the orchestrator runs the rule SET.

Adding a rule is now a SPEC (+ its tags) and a line in ``ACTIVE_RULE_IDS`` — never new evaluation
Python. Each active rule is dispatched by WHICH EVALUATION BLOCK its spec carries: ``consistency`` →
the generic cross-source consistency evaluator; ``deterministic`` (calculative/structural) → the
generic deterministic evaluator; ``judgment`` (judgmental) → the generic judgment evaluator; none
(out_of_scope) → nothing evaluates (it resolves to ``not_applicable`` — §8 Tab 4, not a couldnt_check).
Dispatch is by block (not bare kind) because a STRUCTURAL rule may carry either a deterministic OR a
consistency body.
"""

from __future__ import annotations

from app.ai.rule_judgment import Reasoner
from app.verification.rule_engine.consistency import evaluate_consistency_rule
from app.verification.rule_engine.deterministic import evaluate_deterministic_rule
from app.verification.rule_engine.judgment import evaluate_judgment_rule
from app.verification.rule_engine.result import RuleEvaluation
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.model import Snapshot
from app.verification.snapshot.tag import Tag

# The rules wired for evaluation (each has a spec + its tags). A wave adds a rule_id here + a spec.
# ID-2/ID-4 (cross-source consistency) went LIVE at LP-326; LP-323-ID-B added ID-1 (name), ID-3 (DOB),
# ID-6 (1003 completeness); LP-329 adds ID-7 (marital/title, deterministic per_document) + ID-9 (POA
# acceptability, judgment per_document) — both DOCUMENT-TYPE scoped (GAP-C), so a non-matching document
# resolves to not_applicable, never a couldnt_check flood. All authored as DATA.
# The BASE set — the rules live before LP-389's first activation pass. A wave adds a rule_id + a spec.
_BASE_ACTIVE: tuple[str, ...] = (
    "AS-1",
    "OC-2",
    "ID-2",
    "ID-4",
    "ID-1",
    "ID-3",
    "ID-6",
    "ID-7",
    "ID-9",
    # LP-332 — ID-8 (citizenship/residency eligibility): its inputs (id.citizenship parsed under the
    # borrower subject, program.type parsed under loan) are deterministic passthroughs (no uncalibrated
    # AI), and its judgment is ratification-pending — genuinely live.
    "ID-8",
    # LP-333 — IN-2 (pay-stub recency): parsed-only (income.pay_date → the loan-level days-since-pay
    # derived tag), no AI, no calibration risk; verified to produce real verdicts end-to-end.
    "IN-2",
)

# LP-389 — the FIRST activation pass. Two inert rules EARNED activation via the eligibility gate
# (activation_bars.is_eligible), fail-closed: a rule activates only when its AI-tag accuracy meets a
# Priya-VALIDATED bar, or its parsed input RESOLVES to real values AT THE SUBJECT THE RULE READS. An unmeasured
# tag, an unvalidated bar, or an unresolved input holds the rule — the inverse of this session's run-level fail-opens.
#   IN-1 — income.documented_monthly measured 100% (LP-379-D); bar 0.98 auto, validated by Priya (LP-380). This
#          SUPERSEDES the LP-333 deferral: documented_monthly is now calibrated (100%) and the derived producer
#          is fixed. Auto, fraud-adjacent — a real income discrepancy is a finding a human sees. (On LF-6T3N it
#          couldnt_checks — that fixture's MISMO carries no borrower STATED income — but the AI side is
#          calibrated and the chain is correct; it resolves on a file that states income. A DATA gap, not a defect.)
#   IN-5 — income.employer_normalized measured 100% (LP-379-D); bar 0.95 auto, validated (LP-380). Auto.
#          Resolves end-to-end on LF-6T3N: SATISFIED on both borrowers.
# ID-5 was PROPOSED for this pass but HELD (LP-389 Phase 2, fail-closed): its parsed inputs (id.id_expiration,
# contract.closing_date) are declared subject:document and materialize on the ID/contract DOCUMENTS, but ID-5
# reads them at tags.by_subject["loan"] — a producer/consumer SUBJECT MISMATCH, so it couldnt_checks on EVERY
# file (LP-381 measured the inputs at the document subject, not the loan subject ID-5 consumes). Its bar's
# input_resolves is therefore false, the gate holds it, and its subject model is a flagged follow-up (the
# two-borrower "which ID is the loan-level expiration" is a Priya call, out of this small pass).
# The OTHER 21 inert rules FAIL the gate (unmeasured tag / validated:false / input unresolved / no producer) and
# are HELD. test_activation_gate_lp389 asserts EXACTLY these two pass and the 21 fail — a rule CANNOT enter this
# set without meeting the gate (the declared safety; not a hand-list that can drift).
_LP389_ACTIVATED: tuple[str, ...] = ("IN-1", "IN-5")

ACTIVE_RULE_IDS: tuple[str, ...] = (*_BASE_ACTIVE, *_LP389_ACTIVATED)


async def evaluate_rules(
    snapshot: Snapshot,
    *,
    judgment_reasoners: dict[str, Reasoner] | None = None,
    consistency_reasoners: dict[str, Reasoner] | None = None,
    confidence_floor: float | None = None,
    rule_ids: tuple[str, ...] = ACTIVE_RULE_IDS,
) -> tuple[list[RuleEvaluation], dict[str, dict[str, Tag]]]:
    """Evaluate every requested rule generically (by evaluation block, from its spec).

    Returns the evaluations + any ``rule_judgment`` tags produced, keyed ``{subject_id: {tag_id: Tag}}``
    (LP-327 — a judgment rule may produce a tag PER SUBJECT, so the tags are subject-scoped) for the
    caller to write back into the tags layer. ``judgment_reasoners`` / ``consistency_reasoners`` inject
    a keyless stub per rule (tests). Each rule GATES itself (LP-315/319): the dispatcher lets them all
    run and never skips one silently.
    """
    judge_reasoners = judgment_reasoners or {}
    con_reasoners = consistency_reasoners or {}
    results: list[RuleEvaluation] = []
    judgment_tags: dict[str, dict[str, Tag]] = {}

    for rule_id in rule_ids:
        spec = load_rule_spec(rule_id)
        if spec.consistency is not None:
            results.extend(
                await evaluate_consistency_rule(
                    spec,
                    snapshot,
                    reasoner=con_reasoners.get(rule_id),
                    confidence_floor=confidence_floor,
                )
            )
        elif spec.deterministic is not None:
            results.extend(
                evaluate_deterministic_rule(spec, snapshot, confidence_floor=confidence_floor)
            )
        elif spec.judgment is not None:
            output_tag = spec.judgment.output_tag
            for evaluation in await evaluate_judgment_rule(
                spec,
                snapshot,
                reasoner=judge_reasoners.get(rule_id),
                confidence_floor=confidence_floor,
            ):
                results.append(evaluation.evaluation)
                if evaluation.judgment_tag is not None:
                    # Key the produced verdict tag under ITS subject (LP-327); OC-2's loan subject
                    # lands under LOAN_SUBJECT exactly as before (equivalence).
                    subject = evaluation.evaluation.subject_id
                    judgment_tags.setdefault(subject, {})[output_tag] = evaluation.judgment_tag
        # No evaluation block (out_of_scope) → nothing evaluates (not_applicable; no finding).

    return results, judgment_tags


__all__ = ["ACTIVE_RULE_IDS", "evaluate_rules"]

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

# LP-389 / LP-389-A — the FIRST activation pass (+ its follow-up). Three inert rules EARNED activation via the
# eligibility gate (activation_bars.is_eligible), fail-closed: a rule activates only when its AI-tag accuracy
# meets a Priya-VALIDATED bar, or its parsed input RESOLVES to real values AT THE SUBJECT THE RULE READS. An
# unmeasured tag, an unvalidated bar, or an unresolved input holds the rule — the inverse of the run-level fail-opens.
#   IN-1 — income.documented_monthly measured 100% (LP-379-D); bar 0.98 auto, validated by Priya (LP-380). This
#          SUPERSEDES the LP-333 deferral: documented_monthly is now calibrated (100%) and the derived producer
#          is fixed. Auto, fraud-adjacent — a real income discrepancy is a finding a human sees. (On LF-6T3N it
#          couldnt_checks — that fixture's MISMO carries no borrower STATED income — but the AI side is
#          calibrated and the chain is correct; it resolves on a file that states income. A DATA gap, not a defect.)
#   IN-5 — income.employer_normalized measured 100% (LP-379-D); bar 0.95 auto, validated (LP-380). Auto.
#          Resolves end-to-end on LF-6T3N: SATISFIED on both borrowers.
#   ID-5 — LP-389 HELD it: a producer/consumer SUBJECT MISMATCH (its inputs materialized on the DOCUMENT subject
#          but ID-5 read them at "loan"), so it couldnt_checked on every file. LP-389-A FIXED it — ID-5 is now
#          PER BORROWER, reading the borrower's belongs_to-attributed ID expiration (id.borrower_id_expiration,
#          derived) against the loan's one closing date (contract.loan_closing_date, derived). The input now
#          resolves at the subject the rule reads (input_resolves flipped true), so the gate lets it through.
#          Resolves end-to-end on LF-6T3N: SATISFIED for both borrowers (both DLs unexpired at closing).
_LP389_ACTIVATED: tuple[str, ...] = ("IN-1", "IN-5", "ID-5")

# LP-384 — the SECOND activation pass: three STUCK deterministic (no-AI) rules whose inputs LF-6T3N lacked
# now resolve, verified on the fixture, so the gate (input_resolves) admits them. Each proves a KNOWN answer.
#   AS-10 — stmt.min_account_months ALREADY resolves on the BASE LF-6T3N (its statements grew account identity
#           + period dates as the fixture matured; LP-381's "input absent" went stale). SATISFIED — every
#           account has >= 2 months. No fixture change needed.
#   AS-9  — stmt.page_count_declared/present. build_lf6t3n_plus adds a statement that declares 5 pages but has
#           4 present → AS-9 FIRES ("a page is missing"); a complete statement satisfies. Input resolves.
#   IN-4  — income.max_employment_gap_days. build_lf6t3n_plus adds two VOEs with a deliberate 77-day gap →
#           IN-4 FIRES (beyond the 30-day window); a no-gap variant satisfies. Input resolves.
# STILL HELD (fail-closed): AS-3 (no §3B cash-to-close calculator — its recipe is a stub, LP-383), and IN-3
# (its derived recipe reads income.documented_monthly (AI) — a transitive AI dependency like IN-1, an
# income-wave rule; its no-ai bar is a MISCLASSIFICATION reported in activation_bars.yaml).
_LP384_ACTIVATED: tuple[str, ...] = ("AS-9", "IN-4", "AS-10")

# The gate is the source of truth: test_activation_gate_lp389 asserts ACTIVE_RULE_IDS - _BASE_ACTIVE ==
# eligible_rule_ids() — a rule CANNOT enter this set without meeting the eligibility gate (not a hand-list).
ACTIVE_RULE_IDS: tuple[str, ...] = (*_BASE_ACTIVE, *_LP389_ACTIVATED, *_LP384_ACTIVATED)


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

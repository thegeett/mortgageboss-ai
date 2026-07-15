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
# ID-2/ID-4 (cross-source consistency) are LIVE as of LP-326 — the generic producers now materialize
# their ``id.*`` load-bearing tags, so they evaluate for real instead of uniformly couldnt_check.
ACTIVE_RULE_IDS: tuple[str, ...] = ("AS-1", "OC-2", "ID-2", "ID-4")


async def evaluate_rules(
    snapshot: Snapshot,
    *,
    judgment_reasoners: dict[str, Reasoner] | None = None,
    consistency_reasoners: dict[str, Reasoner] | None = None,
    confidence_floor: float | None = None,
    rule_ids: tuple[str, ...] = ACTIVE_RULE_IDS,
) -> tuple[list[RuleEvaluation], dict[str, Tag]]:
    """Evaluate every requested rule generically (by evaluation block, from its spec).

    Returns the evaluations + any ``rule_judgment`` tags produced (keyed by tag id) for the caller to
    write back into the tags layer. ``judgment_reasoners`` / ``consistency_reasoners`` inject a keyless
    stub per rule (tests). Each rule GATES itself (LP-315/319): the dispatcher lets them all run and
    never skips one silently.
    """
    judge_reasoners = judgment_reasoners or {}
    con_reasoners = consistency_reasoners or {}
    results: list[RuleEvaluation] = []
    judgment_tags: dict[str, Tag] = {}

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
            evaluation = await evaluate_judgment_rule(
                spec,
                snapshot,
                reasoner=judge_reasoners.get(rule_id),
                confidence_floor=confidence_floor,
            )
            results.append(evaluation.evaluation)
            if evaluation.judgment_tag is not None and spec.judgment is not None:
                judgment_tags[spec.judgment.output_tag] = evaluation.judgment_tag
        # No evaluation block (out_of_scope) → nothing evaluates (not_applicable; no finding).

    return results, judgment_tags


__all__ = ["ACTIVE_RULE_IDS", "evaluate_rules"]

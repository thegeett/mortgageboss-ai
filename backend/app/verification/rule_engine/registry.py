"""The rule registry + GENERIC dispatch (LP-324) — the orchestrator runs the rule SET by KIND.

Adding a rule is now a SPEC (+ its tags) and a line in ``ACTIVE_RULE_IDS`` — never new evaluation
Python. Each active rule is dispatched by its ``kind``: deterministic (calculative/structural) → the
generic deterministic evaluator; judgment (judgmental) → the generic judgment evaluator; out_of_scope
→ nothing evaluates (it resolves to ``not_applicable`` — §8 Tab 4, not a couldnt_check).
"""

from __future__ import annotations

from app.verification.rule_engine.deterministic import evaluate_deterministic_rule
from app.verification.rule_engine.judgment import Reasoner, evaluate_judgment_rule
from app.verification.rule_engine.result import RuleEvaluation
from app.verification.rules.kinds import RuleKindName
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.model import Snapshot
from app.verification.snapshot.tag import Tag

# The rules wired for evaluation (each has a spec + its tags). A wave adds a rule_id here + a spec.
ACTIVE_RULE_IDS: tuple[str, ...] = ("AS-1", "OC-2")

_DETERMINISTIC_KINDS = (RuleKindName.CALCULATIVE, RuleKindName.STRUCTURAL)


async def evaluate_rules(
    snapshot: Snapshot,
    *,
    judgment_reasoners: dict[str, Reasoner] | None = None,
    confidence_floor: float | None = None,
    rule_ids: tuple[str, ...] = ACTIVE_RULE_IDS,
) -> tuple[list[RuleEvaluation], dict[str, Tag]]:
    """Evaluate every active rule generically (by kind, from its spec).

    Returns the evaluations + any ``rule_judgment`` tags produced (keyed by tag id) for the caller to
    write back into the tags layer. ``judgment_reasoners`` injects a keyless stub per judgment rule.
    Each rule GATES itself (LP-315/319): the dispatcher lets them all run and never skips one silently.
    """
    reasoners = judgment_reasoners or {}
    results: list[RuleEvaluation] = []
    judgment_tags: dict[str, Tag] = {}

    for rule_id in rule_ids:
        spec = load_rule_spec(rule_id)
        if spec.kind in _DETERMINISTIC_KINDS:
            results.extend(
                evaluate_deterministic_rule(spec, snapshot, confidence_floor=confidence_floor)
            )
        elif spec.kind is RuleKindName.JUDGMENTAL:
            evaluation = await evaluate_judgment_rule(
                spec,
                snapshot,
                reasoner=reasoners.get(rule_id),
                confidence_floor=confidence_floor,
            )
            results.append(evaluation.evaluation)
            if evaluation.judgment_tag is not None and spec.judgment is not None:
                judgment_tags[spec.judgment.output_tag] = evaluation.judgment_tag
        # RuleKindName.OUT_OF_SCOPE → nothing evaluates (not_applicable; no finding).

    return results, judgment_tags


__all__ = ["ACTIVE_RULE_IDS", "evaluate_rules"]

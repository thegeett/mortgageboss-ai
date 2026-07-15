"""OC-2 — occupancy reasonableness. DECISION LOGIC is now DATA (LP-324).

OC-2's judgment flow lives in ``OC-2.yaml``'s ``judgment`` block and is run by the generic judgment
evaluator (:mod:`app.verification.rule_engine.judgment`). NO per-rule flow code remains here; only
the spec-derived identifiers a few call sites + tests reference, plus a thin ``evaluate_oc2`` wrapper
(same signature + result type, so callers are unchanged). The former ``evaluate_oc2`` flow (gate →
prompt → ratification), the prompt, and the parse are deleted — they are the spec + the generic
evaluator now.
"""

from __future__ import annotations

from app.verification.rule_engine.engine import DEFAULT_CONFIDENCE_FLOOR
from app.verification.rule_engine.enumerators import LOAN_SUBJECT
from app.verification.rule_engine.judgment import (
    JudgmentEvaluation,
    Reasoner,
    evaluate_judgment_rule,
)
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.model import Snapshot

RULE_ID = "OC-2"

_JUDGMENT = load_rule_spec(RULE_ID).judgment
assert _JUDGMENT is not None, "OC-2 must carry a judgment evaluation block"

# Spec-derived identifiers (names, not logic).
JUDGMENT_TAG = _JUDGMENT.output_tag
REASONED_OVER = tuple(_JUDGMENT.reasoned_over)

# Backward-compatible alias — the generic judgment result under OC-2's historical name.
Oc2Evaluation = JudgmentEvaluation


async def evaluate_oc2(
    snapshot: Snapshot,
    *,
    reasoner: Reasoner | None = None,
    confidence_floor: float = DEFAULT_CONFIDENCE_FLOOR,
) -> JudgmentEvaluation:
    """Evaluate OC-2 — a thin wrapper: load the OC-2 spec → the generic judgment evaluator.

    Identical results to the former per-rule module (the LP-324/327 equivalence property); the flow +
    prompt now live in ``OC-2.yaml``, not in code. OC-2 declares ``subject_enumeration: loan`` → the
    multi-subject evaluator (LP-327) yields exactly ONE evaluation, returned here (single-subject
    signature unchanged, so callers + the eval harness are untouched).
    """
    evaluations = await evaluate_judgment_rule(
        load_rule_spec(RULE_ID), snapshot, reasoner=reasoner, confidence_floor=confidence_floor
    )
    return evaluations[0]


__all__ = [
    "JUDGMENT_TAG",
    "LOAN_SUBJECT",
    "REASONED_OVER",
    "Oc2Evaluation",
    "Reasoner",
    "evaluate_oc2",
]

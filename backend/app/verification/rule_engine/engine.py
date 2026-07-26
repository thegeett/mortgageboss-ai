"""The rule-engine entry points (LP-315 → generalized in LP-324).

AS-1 is now DATA — ``AS-1.yaml``'s ``deterministic`` block — run by the GENERIC deterministic
evaluator (:mod:`app.verification.rule_engine.deterministic`). This module keeps the historical
``evaluate_as1_rule`` entry point as a THIN spec-loading wrapper, so the eval harness + tests + the
orchestrator are unchanged, while the per-rule decision logic that lived here (and in ``as1.py``) is
gone. Adding a deterministic rule is now a SPEC, not new Python.
"""

from __future__ import annotations

from app.verification.rule_engine.deterministic import evaluate_deterministic_rule
from app.verification.rule_engine.result import RuleEvaluation
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.model import Snapshot

# The confidence floor below which a load-bearing tag routes a verdict to needs_review. Kept here as
# the shared default (the orchestrator + judgment path import it); a spec may override per rule.
DEFAULT_CONFIDENCE_FLOOR = 0.5


def evaluate_as1_rule(
    snapshot: Snapshot, *, confidence_floor: float = DEFAULT_CONFIDENCE_FLOOR
) -> list[RuleEvaluation]:
    """Evaluate AS-1 — a thin wrapper: load the AS-1 spec → the generic deterministic evaluator.

    Identical results to the former per-rule module (the LP-324 equivalence property); the decision
    tree now lives in ``AS-1.yaml``, not in code.
    """
    return evaluate_deterministic_rule(
        load_rule_spec("AS-1"), snapshot, confidence_floor=confidence_floor
    )


__all__ = ["DEFAULT_CONFIDENCE_FLOOR", "evaluate_as1_rule"]

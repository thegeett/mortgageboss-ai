"""The rule engine — rules are SPECS run by GENERIC evaluators (LP-315 → generalized LP-324).

A rule READS the fact-tags (LP-313/314) and produces a verdict — no per-rule Python. The generic
deterministic evaluator runs any calculative/structural rule from its spec (behind the reusable
fail-closed gate); the generic judgment evaluator runs any AI-at-rule-time rule with mandatory
ratification. AS-1 + OC-2 are re-expressed as data on top. Produces in-memory
:class:`RuleEvaluation` results; persistence (findings) is LP-316.
"""

from app.verification.rule_engine.as1 import LOAD_BEARING_TAGS, RULE_ID
from app.verification.rule_engine.deterministic import evaluate_deterministic_rule
from app.verification.rule_engine.engine import DEFAULT_CONFIDENCE_FLOOR, evaluate_as1_rule
from app.verification.rule_engine.gate import GateResult, GateStatus, evaluate_gate
from app.verification.rule_engine.result import (
    LoadBearingTag,
    RuleEvaluation,
    Verdict,
)

__all__ = [
    "DEFAULT_CONFIDENCE_FLOOR",
    "LOAD_BEARING_TAGS",
    "RULE_ID",
    "GateResult",
    "GateStatus",
    "LoadBearingTag",
    "RuleEvaluation",
    "Verdict",
    "evaluate_as1_rule",
    "evaluate_deterministic_rule",
    "evaluate_gate",
]

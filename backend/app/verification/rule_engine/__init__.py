"""The thin deterministic rule engine + fail-closed gate (LP-315).

A rule finally READS the fact-tags (LP-313/314) and produces a verdict — no AI, no
``direction==`` label filter. AS-1 is a thin query over ``is_money_in`` + ``amount`` +
``has_identified_source`` + the spec threshold, run behind the generic fail-closed gate. Produces
in-memory :class:`RuleEvaluation` results; persistence (findings) is LP-316.
"""

from app.verification.rule_engine.as1 import LOAD_BEARING_TAGS, RULE_ID, evaluate_as1
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
    "evaluate_as1",
    "evaluate_as1_rule",
    "evaluate_gate",
]

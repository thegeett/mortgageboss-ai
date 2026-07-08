"""Applicability filter (LP-119) — the first data-driven engine piece that RUNS.

Classifies each verification rule against a loan file's fact snapshot into
DOESNT_APPLY / COULDNT_CHECK / READY_TO_RUN by reading the rule's applicability (scope / triggers /
required_inputs) as DATA. The three-valued honesty contract lives in
:mod:`app.verification.applicability.engine`. This package classifies only — it runs no evaluator
and produces no finding (LP-120/121).
"""

from dataclasses import dataclass, field

from app.models.verification_rule import VerificationRule
from app.verification.applicability.engine import classify, classify_from_json
from app.verification.applicability.schema import (
    Applicability,
    ApplicabilityState,
    Classification,
)
from app.verification.fact_namespace.snapshot import FactNamespace


@dataclass(frozen=True)
class RuleClassification:
    """One rule's classification (its stable ``rule_id`` + the result)."""

    rule_id: str
    classification: Classification


@dataclass
class ClassifiedRules:
    """The three applicability groups for a file — the LP-121 runner reads ``ready_to_run``."""

    doesnt_apply: list[RuleClassification] = field(default_factory=list)
    couldnt_check: list[RuleClassification] = field(default_factory=list)
    ready_to_run: list[RuleClassification] = field(default_factory=list)


_GROUP = {
    ApplicabilityState.DOESNT_APPLY: "doesnt_apply",
    ApplicabilityState.COULDNT_CHECK: "couldnt_check",
    ApplicabilityState.READY_TO_RUN: "ready_to_run",
}


def classify_rules(rules: list[VerificationRule], snapshot: FactNamespace) -> ClassifiedRules:
    """Classify a set of rules (from ``verification_rules``) against one file's snapshot.

    Reads each rule's stored ``applicability`` JSON — no rule-specific logic. Read-only; runs
    nothing. The runner (LP-121) evaluates only the ``ready_to_run`` group; the trust surface
    (LP-140) surfaces ``couldnt_check`` (never a silent pass).
    """
    out = ClassifiedRules()
    for rule in rules:
        result = classify_from_json(rule.applicability, snapshot)
        getattr(out, _GROUP[result.state]).append(RuleClassification(rule.rule_id, result))
    return out


__all__ = [
    "Applicability",
    "ApplicabilityState",
    "Classification",
    "ClassifiedRules",
    "RuleClassification",
    "classify",
    "classify_from_json",
    "classify_rules",
]

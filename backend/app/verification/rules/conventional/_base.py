"""Shared builders for the Conventional rule content (LP-82/83).

The Conventional investor rules (income/asset in :mod:`__init__`, credit/DTI/property/
doc in :mod:`credit_property_docs`) are GROUNDED STARTERS — researched against the
current Fannie Mae Selling Guide (retrieved 2026-06) with real B-section citations,
clearly marked ``starter=True`` and pending the domain expert's validation. These
helpers keep the citation + starter posture consistent across both files.
"""

from __future__ import annotations

from app.models.finding import FindingCategory
from app.models.lender import LoanProgram
from app.verification.rules.schema import (
    Applicability,
    ApplicabilityScope,
    Condition,
    RuleGate,
    RuleLayer,
    RuleSeverity,
    RuleSource,
    VerificationRule,
)

CONVENTIONAL = Applicability(scope=ApplicabilityScope.PROGRAM, program=LoanProgram.CONVENTIONAL)


def sg(section: str, *, to_verify: bool = False) -> RuleSource:
    """A structured Fannie Mae Selling Guide citation (durable section, retrieved date)."""
    return RuleSource(
        type="fannie_selling_guide",
        citation=f"Fannie Mae Selling Guide {section}",
        section=section,
        retrieved="2026-06",
        to_verify=to_verify,
    )


def conv_rule(
    rule_id: str,
    *,
    reads: tuple[str, ...],
    condition: Condition,
    severity: RuleSeverity,
    category: FindingCategory,
    description: str,
    source: RuleSource,
    notes: str,
    gate: RuleGate | None = None,
) -> VerificationRule:
    """A Conventional investor rule, always marked ``starter=True`` (validate with Priya)."""
    return VerificationRule(
        rule_id=rule_id,
        layer=RuleLayer.INVESTOR,
        applicability=CONVENTIONAL,
        reads=reads,
        condition=condition,
        severity=severity,
        category=category,
        description=description,
        source=source,
        starter=True,
        notes=notes,
        gate=gate,
    )

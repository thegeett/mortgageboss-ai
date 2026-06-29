"""Shared builders for the FHA rule content (LP-84/85).

The FHA investor rules (credit/DTI in :mod:`credit_dti`, income/asset in
:mod:`income_assets`, MIP in :mod:`mip`) are GROUNDED STARTERS — researched against
the current **HUD Handbook 4000.1** (the Single Family Housing Policy Handbook,
retrieved 2026-06) with real section citations + current values, clearly marked
``starter=True`` and pending the domain expert's (Priya's) validation against the
live handbook for her lenders/scenarios (she works FHA with Sun-West).

FHA is a SEPARATE program (``program=fha``), not a clone of the Conventional rules:
the source is HUD 4000.1 (not the Fannie Selling Guide), and FHA has structures with
no Conventional analog — a tiered minimum decision credit score (MDCS) keyed to the
down payment, a compensating-factors DTI model (mitigable, not a hard ceiling), and
MIP (mortgage insurance premium). These helpers keep the HUD citation + FHA program +
starter posture consistent across the three content files.
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

FHA = Applicability(scope=ApplicabilityScope.PROGRAM, program=LoanProgram.FHA)


def hud(section: str, *, to_verify: bool = False) -> RuleSource:
    """A structured HUD Handbook 4000.1 citation (durable section, retrieved date).

    ``type="hud_handbook_4000_1"`` distinguishes the FHA source from the Fannie
    Selling Guide (``"fannie_selling_guide"``). ``section`` is the durable handbook
    reference (e.g. ``"II.A.5"`` / ``"Appendix 1.0"``); set ``to_verify`` when the
    exact subsection/value is uncertain (waiting periods, the MIP rate table, the
    60% reserve haircut) — never fabricate one.
    """
    return RuleSource(
        type="hud_handbook_4000_1",
        citation=f"HUD Handbook 4000.1 {section}",
        section=section,
        retrieved="2026-06",
        to_verify=to_verify,
    )


def fha_rule(
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
    """An FHA investor rule, always ``program=fha`` + ``starter=True`` (validate with Priya)."""
    return VerificationRule(
        rule_id=rule_id,
        layer=RuleLayer.INVESTOR,
        applicability=FHA,
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

"""A SAMPLE lender overlay (LP-74) — proves override-by-id + add-custom.

This is **not** a real lender overlay (the real UWM / Sun-West overlays are
LP-80). It exists only to exercise the overlay-application mechanism:

* it **overrides** the Conventional back-end DTI cap by ``rule_id`` — a stricter
  45 % where the investor default is 50 % (same rule, same logic, new threshold
  data), proving override-by-id and that the patch actually changes evaluation;
* it **adds a custom rule** the investor default does not have — a reserves
  minimum — proving add-custom (a LENDER-scoped rule).

Everything it does not mention falls through to the investor default — that is
the investor-default-with-overlay-as-diff behaviour.
"""

from __future__ import annotations

from decimal import Decimal

from app.models.finding import FindingCategory
from app.verification.overlays.schema import LenderOverlay, ThresholdOverride
from app.verification.rules.schema import (
    Applicability,
    ApplicabilityScope,
    Condition,
    Operator,
    RuleLayer,
    RuleSeverity,
    RuleSource,
    VerificationRule,
)

SAMPLE_OVERLAY_LENDER_SLUG = "sample-overlay-bank"

# A custom rule this lender adds on top of the investor defaults.
SAMPLE_RESERVES_MIN_MONTHS = VerificationRule(
    rule_id=f"{SAMPLE_OVERLAY_LENDER_SLUG}.reserves.min_months",
    layer=RuleLayer.OVERLAY,
    applicability=Applicability(scope=ApplicabilityScope.LENDER, lender=SAMPLE_OVERLAY_LENDER_SLUG),
    reads=("reserves.months",),
    condition=Condition(op=Operator.GE, value=Decimal("6"), unit="months"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.ASSETS,
    description="Lender overlay: at least 6 months of reserves (sample custom rule).",
    source=RuleSource(
        type="lender_overlay",
        citation="Sample Overlay Bank credit policy (sample)",
    ),
)

SAMPLE_OVERLAY = LenderOverlay(
    lender_slug=SAMPLE_OVERLAY_LENDER_SLUG,
    overrides=(
        # Override-by-id: stricter Conventional DTI (45 vs the investor 50). Only
        # the threshold data changes; conv.dti.back_end_max keeps its logic.
        ThresholdOverride(
            rule_id="conv.dti.back_end_max",
            condition=Condition(op=Operator.LE, value=Decimal("45"), unit="percent"),
        ),
    ),
    custom_rules=(SAMPLE_RESERVES_MIN_MONTHS,),
)


# Overlays keyed by lender slug, for the registry.
SAMPLE_OVERLAYS: dict[str, LenderOverlay] = {SAMPLE_OVERLAY_LENDER_SLUG: SAMPLE_OVERLAY}

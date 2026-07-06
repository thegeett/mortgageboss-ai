"""STARTER lender overlays — UWM + Sun-West (LP-80). PLACEHOLDER VALUES.

================================ READ THIS FIRST ================================
These are **STARTER / PLACEHOLDER** overlays for the domain expert (Priya) to
**VALIDATE and CORRECT**. The specific thresholds below are NOT authoritative UWM
or Sun-West requirements — that lender knowledge is not yet available. They are a
small, plausible set chosen so enforcement is demonstrable and so Priya has
something concrete to react to ("no, UWM's DTI cap is actually X"; "Sun-West also
requires Y").

  • The MECHANISM is real (LP-74's three-layer composition applies these).
  • The VALUES are STARTER — replace them with Priya's real knowledge.

Do NOT present these as real lender requirements. Editing UI is LP-87; for now
they are hand-editable config here.
================================================================================

An overlay is a **diff** against the investor default (LP-74), never a full copy:

* ``overrides`` — replace an investor rule's threshold *by ``rule_id``* (only the
  :class:`Condition` data changes; the rule's identity + logic are inherited).
* ``custom_rules`` — a LENDER-scoped rule the investor default does not have.

Everything not mentioned falls through to the investor default. The overlays are
keyed by the lender **slug** (matching the seeded lenders ``uwm`` / ``sun-west``),
so a file whose target lender is UWM is automatically evaluated against UWM's
overlay (the calculators + the engine both resolve via ``default_registry()``).

**The enforcement proof:** UWM tightens the Conventional back-end DTI cap (45 vs
the investor 50); Sun-West does NOT touch DTI. So the *same* file at e.g. 48 %
back-end DTI **flags under UWM but not under Sun-West** — same data, different
lender, different findings. Sun-West still differs (a tighter purchase-LTV cap),
so each is a genuine, distinct diff.
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

# A banner reused in every reason/citation so the placeholder status is impossible
# to miss at the call site or in a finding's provenance.
_PLACEHOLDER = "STARTER PLACEHOLDER — validate with Priya; not an authoritative lender value"

# Slugs MUST match the seeded lenders (app/scripts/seed_dev_data.py) so a file's
# target lender selects the right overlay.
UWM_SLUG = "uwm"
SUNWEST_SLUG = "sun-west"


# --- UWM (starter) ----------------------------------------------------------
# Starter shape: tightens Conventional back-end DTI (the headline of the proof)
# and adds one custom reserves requirement. All values placeholders.

UWM_RESERVES_MIN_MONTHS = VerificationRule(
    rule_id=f"{UWM_SLUG}.reserves.min_months",
    layer=RuleLayer.OVERLAY,
    applicability=Applicability(scope=ApplicabilityScope.LENDER, lender=UWM_SLUG),
    reads=("reserves.months",),
    condition=Condition(op=Operator.GE, value=Decimal("2"), unit="months"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.ASSETS,
    description=f"UWM overlay: at least 2 months of reserves. ({_PLACEHOLDER})",
    source=RuleSource(type="lender_overlay", citation=f"UWM overlay — {_PLACEHOLDER}"),
)

UWM_OVERLAY = LenderOverlay(
    lender_slug=UWM_SLUG,
    overrides=(
        # Override-by-id: tighter Conventional back-end DTI (45 vs the investor 50).
        # Only the threshold data changes; conv.dti.back_end_max keeps its logic.
        ThresholdOverride(
            rule_id="conv.dti.back_end_max",
            condition=Condition(op=Operator.LE, value=Decimal("45"), unit="percent"),
            reason=f"UWM tightens the Conventional back-end DTI cap to 45%. ({_PLACEHOLDER})",
        ),
    ),
    custom_rules=(UWM_RESERVES_MIN_MONTHS,),
)


# --- Sun-West (starter) -----------------------------------------------------
# Starter shape: deliberately does NOT override DTI (so the same file diverges
# from UWM), but tightens the Conventional purchase-LTV cap. All values placeholders.

SUNWEST_OVERLAY = LenderOverlay(
    lender_slug=SUNWEST_SLUG,
    overrides=(
        # Sun-West leaves Conventional DTI at the investor default (50) — that is
        # what makes the same 48% file flag for UWM but not Sun-West. It differs on
        # LTV instead: a tighter Conventional purchase cap (95 vs the investor 97).
        ThresholdOverride(
            rule_id="conv.ltv.purchase_max",
            condition=Condition(op=Operator.LE, value=Decimal("95"), unit="percent"),
            reason=f"Sun-West tightens the Conventional purchase LTV cap to 95%. ({_PLACEHOLDER})",
        ),
    ),
    custom_rules=(),
)


# The starter overlays, keyed by lender slug, for the registry. Merged with the
# LP-74 sample overlay in ``default_registry()``.
STARTER_OVERLAYS: dict[str, LenderOverlay] = {
    UWM_SLUG: UWM_OVERLAY,
    SUNWEST_SLUG: SUNWEST_OVERLAY,
}

"""FHA PROPERTY (MPR) + DOCUMENTATION rules (LP-85) — grounded starters.

================================ READ THIS FIRST ================================
~18 FHA rules (property/MPR 13 + documentation 5) poured into the LP-74 engine as
``program=fha`` (CONTENT, not mechanism) — the LAST rule-content ticket. After this
the engine holds a COMPLETE grounded-starter Conventional + FHA rule set (LP-82..85).
Same shape + posture as LP-82/83/84: **GROUNDED STARTERS** researched against the
current HUD Handbook 4000.1 (retrieved 2026-06) with real II.D / II.A citations,
every rule ``starter=True`` and pending the domain expert's (Priya's) validation.

FHA property is the MOST distinctively-FHA content of all — no Conventional analog:

  • **The three S's (MPR/MPS).** A Conventional appraisal targets market VALUE; an FHA
    appraisal ALSO verifies the property meets the Minimum Property Requirements /
    Standards for **safety, security, and soundness**. A property failing any of the
    three S's needs REPAIRS before FHA insures the loan (II.D). MPR = existing
    construction; MPS = new construction (24 CFR 200.926) — applicability by status.

  • **The "subject-to-repair" CONDITIONAL model** (reuses LP-84's compensating-factors
    mitigable pattern). When the appraiser finds an MPR deficiency the appraisal is
    issued "subject to" the repair — and MOST deficiencies are CORRECTABLE (fix,
    re-inspect, proceed). So MPR findings are encoded as MITIGABLE (a subject-to-repair
    YELLOW finding resolvable by documenting the repair / re-inspection via LP-75's
    resolution — OVERRIDDEN-with-reason / APPLIED), NOT silent hard blocks. Only
    UN-correctable issues (a bedroom with no egress; serious structural failure) are
    true blocks → RED. Severity = correctable-vs-uncorrectable.

  • **MPRs are POLICY-IN-FLUX.** FHA published a 2026 Request for Information to
    modernize the MPRs (no comprehensive update in 20+ years; comment period through
    June 2026). So this content is not only lender-overlay-subject but actively under
    revision — STRONGLY validate-with-Priya + "subject to the pending MPR modernization".

**TIER-2 HONESTY (critical — same posture as LP-77's appraised value).** Most MPR
conditions (peeling paint, roof condition, handrails, water intrusion) are OBSERVED BY
THE APPRAISER and live in the appraisal document — Tier-2 (manual / not deterministically
extracted from raw data). These rules therefore do NOT pretend to detect physical
deficiencies. They check: (a) the FHA appraisal is PRESENT, (b) whether it is "subject
to" repairs (where that datum is captured), and (c) SURFACE the MPR checklist for
human/appraiser confirmation — each deficiency rule reads an appraiser-provided fact and
is recorded not-evaluated (graceful) until that datum is captured. We don't fake what the
system can't see; the appraiser/AI provides the observation, the engine tracks the gate.

**Cross-links (confirm, don't duplicate):** the property rules share LP-77's Tier-2
appraisal posture (the appraisal is manual/extracted, not invented); program-gating
(program=fha) + the conditional/mitigable finding pattern are reused from LP-84.

**Typed-core promotion:** ``property.is_condo`` (promoted, LP-83) gates condo approval;
``property.unit_count`` is newly promoted from the financed unit count. The MPR deficiency
flags, appraisal subject-to-status, year-built, construction status, well/septic presence,
and the FHA appraisal/case-number doc facts are promotion-pending (``notes`` say so).
================================================================================
"""

from __future__ import annotations

from decimal import Decimal

from app.models.finding import FindingCategory
from app.verification.rules.fha._base import fha_rule, hud
from app.verification.rules.schema import (
    Condition,
    Operator,
    RuleGate,
    RuleSeverity,
    VerificationRule,
)

# Applicability gates (LP-83 mechanism, FHA property content).
_PRE_1978 = RuleGate(
    reads="property.year_built", condition=Condition(op=Operator.LT, value=Decimal("1978"))
)
_HAS_WELL_SEPTIC = RuleGate(
    reads="property.well_septic_present", condition=Condition(op=Operator.GE, value=Decimal("1"))
)
_NEW_CONSTRUCTION = RuleGate(
    reads="property.is_new_construction", condition=Condition(op=Operator.GE, value=Decimal("1"))
)
_CONDO = RuleGate(
    reads="property.is_condo", condition=Condition(op=Operator.GE, value=Decimal("1"))
)
_SUBJECT_TO_REPAIR = RuleGate(
    reads="property.appraisal.subject_to_repair",
    condition=Condition(op=Operator.GE, value=Decimal("1")),
)

# A 0/1 deficiency flag: 1 = the appraiser flagged a deficiency. ``LE 0`` passes when
# clear and fires a subject-to-repair finding when a deficiency is present. A 0/1
# presence flag: ``GE 1`` requires the thing to be present.
_NO_DEFICIENCY = Condition(op=Operator.LE, value=Decimal("0"), unit="boolean")
_PRESENT = Condition(op=Operator.GE, value=Decimal("1"), unit="boolean")

_TIER2 = (
    "TIER-2 (appraiser-observed, like LP-77's appraised value): reads an appraiser-provided fact "
    "and is not-evaluated until that datum is captured — surfaces the MPR checklist for human/"
    "appraiser confirmation, does NOT deterministically detect the physical condition."
)
_INFLUX = "Subject to the pending FHA MPR modernization (2026 RFI) — validate with Priya."


# --------------------------------------------------------------------------- #
# PROPERTY / MPR (HUD 4000.1 II.D) — the three S's + the deficiency checklist
# --------------------------------------------------------------------------- #

FHA_PROPERTY_THREE_S_UMBRELLA = fha_rule(
    "fha.property.mpr_three_s_umbrella",
    reads=("property.appraisal.subject_to_repair",),
    condition=_NO_DEFICIENCY,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.PROPERTY,
    description="The property meets FHA safety/security/soundness (else subject-to-repair before insuring).",
    source=hud("II.D"),
    notes=(
        "STARTER — the three-S's UMBRELLA: an FHA appraisal verifies safety + security + soundness; a "
        "failing property is issued 'subject to' repairs that must be completed (often re-inspected) "
        "before closing. CONDITIONAL/MITIGABLE (YELLOW, resolvable via LP-75 by documenting the repair/"
        f"re-inspection — reuses LP-84's pattern). {_TIER2} {_INFLUX} Promotion pending: "
        "property.appraisal.subject_to_repair."
    ),
)

FHA_PROPERTY_LEAD_PAINT = fha_rule(
    "fha.property.mpr_lead_based_paint",
    reads=("property.mpr.lead_paint_deficiency",),
    condition=_NO_DEFICIENCY,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.PROPERTY,
    gate=_PRE_1978,
    description="Defective (chipping/peeling) paint on a pre-1978 home is addressed before closing.",
    source=hud("II.D", to_verify=True),
    notes=(
        "STARTER — GATED to pre-1978 construction (gate: property.year_built < 1978); chipping/peeling/"
        f"flaking paint must be corrected before closing. CONDITIONAL/subject-to-repair (correctable). "
        f"{_TIER2} {_INFLUX} Promotion pending: property.year_built + property.mpr.lead_paint_deficiency."
    ),
)

FHA_PROPERTY_FUNCTIONAL_SYSTEMS = fha_rule(
    "fha.property.mpr_functional_systems",
    reads=("property.mpr.systems_deficiency",),
    condition=_NO_DEFICIENCY,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.PROPERTY,
    description="Heating, plumbing, and electrical systems work safely and continuously.",
    source=hud("II.D"),
    notes=(
        "STARTER — mechanical systems (heating/plumbing/electrical) must function safely + continuously; "
        f"non-functional → subject-to-repair (correctable). {_TIER2} {_INFLUX} Promotion pending: "
        "property.mpr.systems_deficiency."
    ),
)

FHA_PROPERTY_ROOF = fha_rule(
    "fha.property.mpr_roof",
    reads=("property.mpr.roof_deficiency",),
    condition=_NO_DEFICIENCY,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.PROPERTY,
    description="The roof keeps moisture out and has reasonable remaining economic life.",
    source=hud("II.D", to_verify=True),
    notes=(
        "STARTER — active leaks / insufficient remaining life / too many layers → subject-to-repair. The "
        f"exact remaining-life + layer limits are TO VERIFY. CONDITIONAL (correctable). {_TIER2} {_INFLUX} "
        "Promotion pending: property.mpr.roof_deficiency."
    ),
)

FHA_PROPERTY_WATER_INTRUSION = fha_rule(
    "fha.property.mpr_water_intrusion",
    reads=("property.mpr.water_intrusion_deficiency",),
    condition=_NO_DEFICIENCY,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.PROPERTY,
    description="No standing water / excessive moisture in the basement or crawl spaces.",
    source=hud("II.D", to_verify=True),
    notes=(
        f"STARTER — water intrusion affecting soundness → subject-to-repair (correctable). {_TIER2} "
        f"{_INFLUX} Promotion pending: property.mpr.water_intrusion_deficiency."
    ),
)

FHA_PROPERTY_HANDRAILS = fha_rule(
    "fha.property.mpr_safe_access_handrails",
    reads=("property.mpr.handrail_deficiency",),
    condition=_NO_DEFICIENCY,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.PROPERTY,
    description="Stairways with 3+ steps have handrails; safe access to the property + utilities exists.",
    source=hud("II.D", to_verify=True),
    notes=(
        "STARTER — the 3+ steps handrail trigger is folk-knowledge; the exact rule is TO VERIFY. "
        f"CONDITIONAL/subject-to-repair (correctable). {_TIER2} {_INFLUX} Promotion pending: "
        "property.mpr.handrail_deficiency."
    ),
)

FHA_PROPERTY_EGRESS = fha_rule(
    "fha.property.mpr_bedroom_egress",
    reads=("property.mpr.bedroom_egress_deficiency",),
    condition=_NO_DEFICIENCY,
    severity=RuleSeverity.RED,
    category=FindingCategory.PROPERTY,
    description="Each bedroom has proper egress (a no-egress bedroom is an un-correctable block).",
    source=hud("II.D", to_verify=True),
    notes=(
        "STARTER — the UN-CORRECTABLE case → RED (a harder block, not a correctable subject-to-repair): a "
        "bedroom without proper egress (window/door) generally cannot be cured by a simple repair. The "
        f"exact egress standard is TO VERIFY. {_TIER2} {_INFLUX} Promotion pending: "
        "property.mpr.bedroom_egress_deficiency."
    ),
)

FHA_PROPERTY_WELL_SEPTIC = fha_rule(
    "fha.property.mpr_well_septic",
    reads=("property.mpr.well_septic_deficiency",),
    condition=_NO_DEFICIENCY,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.PROPERTY,
    gate=_HAS_WELL_SEPTIC,
    description="Well/septic meets FHA distance + condition standards (when the property has them).",
    source=hud("II.D", to_verify=True),
    notes=(
        "STARTER — GATED to a property with a well/septic (gate: property.well_septic_present). Starter "
        "distances (well >=50 ft from the septic tank, >=10 ft from the property line; signs of septic "
        f"failure → further inspection) are TO VERIFY. CONDITIONAL (often correctable). {_TIER2} {_INFLUX} "
        "Promotion pending: property.well_septic_present + property.mpr.well_septic_deficiency."
    ),
)

FHA_PROPERTY_DEFECTIVE_CONDITIONS = fha_rule(
    "fha.property.mpr_defective_conditions",
    reads=("property.mpr.structural_defect",),
    condition=_NO_DEFICIENCY,
    severity=RuleSeverity.RED,
    category=FindingCategory.PROPERTY,
    description="No defective conditions (structural failure, decay, termites, environmental hazards).",
    source=hud("II.D", to_verify=True),
    notes=(
        "STARTER — soundness: structural failure (settlement / bulging foundation walls), decay, termite "
        "damage, or environmental hazards. RED — these threaten the foundation/structure being "
        "serviceable for the life of the mortgage and may be un-correctable; serious cases block. Exact "
        f"section TO VERIFY. {_TIER2} {_INFLUX} Promotion pending: property.mpr.structural_defect."
    ),
)

FHA_PROPERTY_MPS_NEW_CONSTRUCTION = fha_rule(
    "fha.property.mps_new_construction",
    reads=("property.mps.standards_met",),
    condition=_PRESENT,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.PROPERTY,
    gate=_NEW_CONSTRUCTION,
    description="New construction meets the Minimum Property Standards (MPS), not just the MPRs.",
    source=hud("II.D", to_verify=True),
    notes=(
        "STARTER — MPR vs MPS by construction status: MPR = existing construction; MPS = NEW construction "
        "(24 CFR 200.926). GATED to new construction (gate: property.is_new_construction). Exact "
        f"sectioning TO VERIFY. {_TIER2} {_INFLUX} Promotion pending: property.is_new_construction + "
        "property.mps.standards_met."
    ),
)


# --------------------------------------------------------------------------- #
# PROPERTY ELIGIBILITY (HUD 4000.1 II.A / II.D)
# --------------------------------------------------------------------------- #

FHA_PROPERTY_UNITS = fha_rule(
    "fha.property.units_eligibility",
    reads=("property.unit_count",),
    condition=Condition(op=Operator.LE, value=Decimal("4"), unit="count"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.PROPERTY,
    description="The property is 1-4 unit residential (FHA-insurable).",
    source=hud("II.A", to_verify=True),
    notes=(
        "STARTER — FHA insures 1-4 unit residential properties; certain types are excluded. EVALUABLE "
        "from the financed unit count (promoted: property.unit_count). Exact section TO VERIFY."
    ),
)

FHA_PROPERTY_CONDO_APPROVAL = fha_rule(
    "fha.property.condo_project_approval",
    reads=("property.condo.fha_project_approved",),
    condition=_PRESENT,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.PROPERTY,
    gate=_CONDO,
    description="A condo unit's project is FHA-approved (HRAP/DELRAP) or single-unit-approved.",
    source=hud("II.A", to_verify=True),
    notes=(
        "STARTER — GATED to a condo (gate: property.is_condo, promoted LP-83). A condo unit generally "
        "requires the PROJECT on HUD's approved list (HRAP/DELRAP), or single-unit approval. Section TO "
        f"VERIFY. {_INFLUX} Promotion pending: property.condo.fha_project_approved."
    ),
)

FHA_PROPERTY_APPRAISAL_VALIDITY = fha_rule(
    "fha.property.appraisal_validity_period",
    reads=("property.appraisal.age_days",),
    condition=Condition(op=Operator.LE, value=Decimal("180"), unit="days"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.PROPERTY,
    description="The FHA appraisal is within its validity period (it 'follows the property').",
    source=hud("II.A", to_verify=True),
    notes=(
        "STARTER — an FHA appraisal is valid for a set period (~120 days, extendable to ~180) and follows "
        "the property for subsequent FHA buyers. The exact period is TO VERIFY (Tier-2 appraisal date, "
        "shared with LP-77). Promotion pending: property.appraisal.age_days."
    ),
)


# --------------------------------------------------------------------------- #
# DOCUMENTATION (HUD 4000.1 II.A) — FHA appraisal / closing documentation
# --------------------------------------------------------------------------- #

FHA_DOC_FHA_APPRAISAL_PRESENT = fha_rule(
    "fha.doc.fha_appraisal_present",
    reads=("documents.fha_appraisal_present",),
    condition=_PRESENT,
    severity=RuleSeverity.RED,
    category=FindingCategory.DOCUMENTATION,
    description="An FHA appraisal is present (FHA-approved appraiser; HUD/FHA an intended user).",
    source=hud("II.A"),
    notes=(
        "STARTER — an FHA loan requires an FHA appraisal performed by an FHA-approved appraiser with HUD/"
        "FHA listed as an intended user. Absent → RED. This is the Tier-2 anchor: the MPR rules depend on "
        "this appraisal being present. Promotion pending: documents.fha_appraisal_present."
    ),
)

FHA_DOC_SUBJECT_TO_REPAIR_COMPLETION = fha_rule(
    "fha.doc.subject_to_repair_completion",
    reads=("documents.repair_completion_present",),
    condition=_PRESENT,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.DOCUMENTATION,
    gate=_SUBJECT_TO_REPAIR,
    description="Where the appraisal is subject-to-repair, the completion / re-inspection is in the file.",
    source=hud("II.D", to_verify=True),
    notes=(
        "STARTER — GATED to a subject-to-repair appraisal (gate: property.appraisal.subject_to_repair). "
        "The repair completion / re-inspection (e.g. form 1004D / compliance inspection) must be in the "
        "file before closing — the documentary half of the subject-to-repair conditional model. Section "
        f"TO VERIFY. {_INFLUX} Promotion pending: documents.repair_completion_present."
    ),
)

FHA_DOC_CASE_NUMBER_AMENDATORY = fha_rule(
    "fha.doc.case_number_and_amendatory_clause",
    reads=("documents.fha_case_number_present",),
    condition=_PRESENT,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.DOCUMENTATION,
    description="An FHA case number is assigned and the Amendatory Clause / RE certification is present.",
    source=hud("II.A", to_verify=True),
    notes=(
        "STARTER — an FHA case number must be assigned; purchase files need the FHA Amendatory Clause + "
        "real estate certification. Section TO VERIFY. Promotion pending: documents.fha_case_number_present."
    ),
)

FHA_DOC_PRE_APPRAISAL_SALES_CONTRACT = fha_rule(
    "fha.doc.pre_appraisal_sales_contract",
    reads=("documents.sales_contract_present",),
    condition=_PRESENT,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.DOCUMENTATION,
    description="The appraiser is provided the executed sales contract (purchase) before appraising.",
    source=hud("II.D", to_verify=True),
    notes=(
        "STARTER — before appraising, the appraiser must obtain the executed sales contract (purchase) + "
        "any land lease / surveys / legal descriptions. Section TO VERIFY. Promotion pending: "
        "documents.sales_contract_present."
    ),
)

FHA_DOC_APPRAISAL_RECENCY = fha_rule(
    "fha.doc.appraisal_recency",
    reads=("documents.appraisal.most_recent_age_months",),
    condition=Condition(op=Operator.LE, value=Decimal("4"), unit="months"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.DOCUMENTATION,
    description="Appraisal/property documentation is within FHA's recency window.",
    source=hud("II.A", to_verify=True),
    notes=(
        "STARTER — FHA has its OWN document recency; the 4-month starter is a placeholder, NOT assumed "
        "from the Fannie 4-month — TO VERIFY. Promotion pending: documents.appraisal.most_recent_age_months."
    ),
)


FHA_PROPERTY_MPR_RULES: tuple[VerificationRule, ...] = (
    FHA_PROPERTY_THREE_S_UMBRELLA,
    FHA_PROPERTY_LEAD_PAINT,
    FHA_PROPERTY_FUNCTIONAL_SYSTEMS,
    FHA_PROPERTY_ROOF,
    FHA_PROPERTY_WATER_INTRUSION,
    FHA_PROPERTY_HANDRAILS,
    FHA_PROPERTY_EGRESS,
    FHA_PROPERTY_WELL_SEPTIC,
    FHA_PROPERTY_DEFECTIVE_CONDITIONS,
    FHA_PROPERTY_MPS_NEW_CONSTRUCTION,
)

FHA_PROPERTY_ELIGIBILITY_RULES: tuple[VerificationRule, ...] = (
    FHA_PROPERTY_UNITS,
    FHA_PROPERTY_CONDO_APPROVAL,
    FHA_PROPERTY_APPRAISAL_VALIDITY,
)

FHA_DOC_RULES: tuple[VerificationRule, ...] = (
    FHA_DOC_FHA_APPRAISAL_PRESENT,
    FHA_DOC_SUBJECT_TO_REPAIR_COMPLETION,
    FHA_DOC_CASE_NUMBER_AMENDATORY,
    FHA_DOC_PRE_APPRAISAL_SALES_CONTRACT,
    FHA_DOC_APPRAISAL_RECENCY,
)

# The full LP-85 set (~18): property/MPR (10) + property eligibility (3) + doc (5).
FHA_PROPERTY_DOC_RULES: tuple[VerificationRule, ...] = (
    *FHA_PROPERTY_MPR_RULES,
    *FHA_PROPERTY_ELIGIBILITY_RULES,
    *FHA_DOC_RULES,
)

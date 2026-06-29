"""Conventional CREDIT/DTI + PROPERTY + DOCUMENTATION rules (LP-83) — grounded starters.

================================ READ THIS FIRST ================================
~30 Conventional rules poured into the LP-74 engine (CONTENT, not mechanism), the
same shape + posture as LP-82: **GROUNDED STARTERS** researched against the current
Fannie Mae Selling Guide (retrieved 2026-06) with real B-section citations, every
rule ``starter=True`` and pending the domain expert's (Priya's) validation.

This category is HIGHER-STAKES than LP-82 and the research caught a major change:

  • **The credit-score minimum is now LAYERED + recently-changed — NOT a flat 620.**
    Through DU Version 12.0 (effective 11/2025) minimum credit scores **no longer
    apply** (DU relies on its own risk analysis); **manually underwritten** loans
    still require **620**; a representative score **below 620 is ineligible for
    delivery** to Fannie Mae (B3-5.1-01). Encoded as the nuanced state: a gated
    manual-620 rule + an ungated sub-620 delivery-floor rule. A hardcoded "min 620
    always" would be WRONG — folk-knowledge is out of date.
  • **DTI** is DU-50% / manual-36%→45% (B3-6-02); the DU ceiling is the existing
    ``conv.dti.back_end_max`` (LE 50) and LP-83 adds the gated manual ceiling (LE 45).
  • **Appraisal age** is 4 months on the note date (B4-1.2-04), parallel to doc age.

**Applicability gating (LP-83):** some rules apply only in a sub-case the program
scope can't express — manually underwritten loans (gate ``underwriting.is_manual``),
condo properties (gate ``property.is_condo``). The gate fact being absent means
not-applicable (the engine skips it).

**Cross-links (confirm, don't duplicate):** the max-DTI rules CONSUME LP-76's computed
``dti.back_end_pct`` (read it, never recompute); the re-underwrite-on-undisclosed-debt
rule is the deterministic counterpart to LP-78's cross-source undisclosed-obligation
finding (the APPLY→recompute interlock already exists).

**Typed-core promotion:** the property rules use the promoted ``property.present`` /
``property.is_condo`` facts; credit/appraisal/underwriting-method facts are promotion-
pending (``notes`` say so), so those rules are recorded not-evaluated until they land.
Eligibility-Matrix / DU items are marked driven-not-hardcoded.
================================================================================
"""

from __future__ import annotations

from decimal import Decimal

from app.models.finding import FindingCategory
from app.verification.rules.conventional._base import conv_rule, sg
from app.verification.rules.schema import (
    Condition,
    Operator,
    RuleGate,
    RuleSeverity,
    VerificationRule,
)

# Applicability gates (LP-83). The DU ceiling is the existing ungated
# ``conv.dti.back_end_max`` (LE 50); LP-83 adds the manual-gated variant.
_MANUAL = RuleGate(
    reads="underwriting.is_manual", condition=Condition(op=Operator.GE, value=Decimal("1"))
)
_CONDO = RuleGate(
    reads="property.is_condo", condition=Condition(op=Operator.GE, value=Decimal("1"))
)

_PRESENT = Condition(op=Operator.GE, value=Decimal("1"), unit="boolean")
_ABSENT = Condition(op=Operator.LE, value=Decimal("0"), unit="boolean")


# --------------------------------------------------------------------------- #
# CREDIT (B3-5.x) — the recently-changed, high-stakes category
# --------------------------------------------------------------------------- #

CONV_CREDIT_MIN_SCORE_MANUAL = conv_rule(
    "conv.credit.min_score_manual",
    reads=("credit.representative_score",),
    condition=Condition(op=Operator.GE, value=Decimal("620"), unit="score"),
    severity=RuleSeverity.RED,
    category=FindingCategory.CREDIT,
    gate=_MANUAL,
    description="Manually underwritten loans require a minimum representative credit score of 620.",
    source=sg("B3-5.1-01"),
    notes=(
        "STARTER — RECENTLY CHANGED + LAYERED, do NOT read as a flat 'min 620 always': through DU "
        "Version 12.0 (11/2025) minimum scores NO LONGER APPLY (DU decides); MANUAL underwriting "
        "still requires 620 (this gated rule); a sub-620 score is ineligible for delivery (see "
        "conv.credit.min_score_delivery_floor). A prime validate-with-Priya item. Promotion pending: "
        "credit.representative_score + underwriting.is_manual."
    ),
)

CONV_CREDIT_MIN_SCORE_DELIVERY_FLOOR = conv_rule(
    "conv.credit.min_score_delivery_floor",
    reads=("credit.representative_score",),
    condition=Condition(op=Operator.GE, value=Decimal("620"), unit="score"),
    severity=RuleSeverity.RED,
    category=FindingCategory.CREDIT,
    description="A representative score below 620 is ineligible for delivery to Fannie Mae.",
    source=sg("B3-5.1-01"),
    notes=(
        "STARTER — the delivery floor (ungated): a representative score below 620 is ineligible for "
        "delivery even though DU applies no minimum for underwriting. Promotion pending: "
        "credit.representative_score."
    ),
)

CONV_CREDIT_REPORT_PRESENT = conv_rule(
    "conv.credit.report_present",
    reads=("documents.credit.report_present",),
    condition=_PRESENT,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.CREDIT,
    description="A credit report is obtained (retained whether or not a score is produced).",
    source=sg("B3-5.1-01"),
    notes=(
        "STARTER — permitted score models are classic FICO versions for DU + manual; the report is "
        "retained whether or not a score is produced. Promotion pending: documents.credit.report_present."
    ),
)

CONV_CREDIT_REPRESENTATIVE_SCORE_PRESENT = conv_rule(
    "conv.credit.representative_score_present",
    reads=("credit.representative_score_present",),
    condition=_PRESENT,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.CREDIT,
    description="A representative/median score is selectable across borrowers/bureaus.",
    source=sg("B3-5.1-02"),
    notes=(
        "STARTER — checks the required scores are present (not a fabricated selection formula). "
        "Promotion pending: credit.representative_score_present."
    ),
)

CONV_CREDIT_DEROG_FORECLOSURE = conv_rule(
    "conv.credit.derogatory_foreclosure_waiting",
    reads=("credit.months_since_foreclosure",),
    condition=Condition(op=Operator.GE, value=Decimal("84"), unit="months"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.CREDIT,
    description="A foreclosure waiting period (~7 years) has elapsed before the note date.",
    source=sg("B3-5.3-07", to_verify=True),
    notes=(
        "STARTER — the exact waiting period + citation are TO VERIFY against B3-5.3-07 (~7 years is "
        "folk-knowledge). Promotion pending: credit.months_since_foreclosure."
    ),
)

CONV_CREDIT_DEROG_BANKRUPTCY = conv_rule(
    "conv.credit.derogatory_bankruptcy_waiting",
    reads=("credit.months_since_bankruptcy",),
    condition=Condition(op=Operator.GE, value=Decimal("48"), unit="months"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.CREDIT,
    description="A bankruptcy waiting period (~4 years) has elapsed before the note date.",
    source=sg("B3-5.3-07", to_verify=True),
    notes=(
        "STARTER — exact period + citation TO VERIFY (chapter 7 vs 13 differ). Promotion pending: "
        "credit.months_since_bankruptcy."
    ),
)

CONV_CREDIT_DEROG_SHORT_SALE = conv_rule(
    "conv.credit.derogatory_short_sale_waiting",
    reads=("credit.months_since_short_sale",),
    condition=Condition(op=Operator.GE, value=Decimal("48"), unit="months"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.CREDIT,
    description="A short-sale / deed-in-lieu waiting period (~4 years) has elapsed.",
    source=sg("B3-5.3-07", to_verify=True),
    notes="STARTER — exact period + citation TO VERIFY. Promotion pending: credit.months_since_short_sale.",
)

CONV_CREDIT_TRADELINES = conv_rule(
    "conv.credit.tradelines_sufficient",
    reads=("credit.tradeline_count",),
    condition=Condition(op=Operator.GE, value=Decimal("1"), unit="count"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.CREDIT,
    description="Sufficient credit tradelines exist (else nontraditional credit may be needed).",
    source=sg("B3-5.4-01", to_verify=True),
    notes="STARTER — section TO VERIFY (nontraditional-credit rules). Promotion pending: credit.tradeline_count.",
)


# --------------------------------------------------------------------------- #
# DTI (B3-6) — consumes LP-76's computed dti.back_end_pct
# --------------------------------------------------------------------------- #

CONV_DTI_MAX_MANUAL = conv_rule(
    "conv.dti.back_end_max_manual",
    reads=("dti.back_end_pct",),
    condition=Condition(op=Operator.LE, value=Decimal("45"), unit="percent"),
    severity=RuleSeverity.RED,
    category=FindingCategory.INCOME,
    gate=_MANUAL,
    description="Manually underwritten back-end DTI is at or under 45% (36% base + factors).",
    source=sg("B3-6-02"),
    notes=(
        "STARTER — CONSUMES LP-76's computed dti.back_end_pct (does not recompute). DU casefiles use "
        "50% (the existing conv.dti.back_end_max); manual is 36% exceedable to 45% with the credit-"
        "score + reserve requirements in the Eligibility Matrix. Promotion pending: underwriting.is_manual."
    ),
)

CONV_DTI_REUNDERWRITE_UNDISCLOSED = conv_rule(
    "conv.dti.reunderwrite_undisclosed_debt",
    reads=("dti.undisclosed_monthly_debt",),
    condition=_ABSENT,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.INCOME,
    description="No undisclosed/discovered debt that would push DTI beyond tolerance after decision.",
    source=sg("B3-6-02"),
    notes=(
        "STARTER — the DETERMINISTIC COUNTERPART to LP-78's cross-source undisclosed-obligation "
        "finding (the AI surfaces it; applying it feeds the DTI recompute — the interlock exists). "
        "Promotion pending: dti.undisclosed_monthly_debt."
    ),
)

CONV_DTI_OBLIGATIONS_10_MONTHS = conv_rule(
    "conv.dti.obligations_beyond_10_months",
    reads=("dti.obligations_classified",),
    condition=_PRESENT,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.INCOME,
    description="Installment/mortgage debts beyond 10 months are counted; revolving as min payment.",
    source=sg("B3-6-05"),
    notes=(
        "STARTER — cross-links LP-76's DTI calc (which sums monthly obligations). See also B3-6-02. "
        "Promotion pending: dti.obligations_classified."
    ),
)

CONV_DTI_BUSINESS_DEBT = conv_rule(
    "conv.dti.business_debt_personally_obligated",
    reads=("income.self_employment.business_debt_personally_obligated",),
    condition=_ABSENT,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.INCOME,
    description="Personally-obligated business debt is included in monthly obligations for DTI.",
    source=sg("B3-3.5-01"),
    notes=(
        "STARTER — reinforces LP-82's conv.income.self_employment_business_debt_in_dti from the DTI "
        "side. Promotion pending: income.self_employment.business_debt_personally_obligated."
    ),
)

CONV_DTI_REVOLVING_MIN_PAYMENT = conv_rule(
    "conv.dti.revolving_min_payment_used",
    reads=("dti.revolving_uses_min_payment",),
    condition=_PRESENT,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.INCOME,
    description="Revolving accounts are counted at the minimum monthly payment.",
    source=sg("B3-6-05", to_verify=True),
    notes="STARTER — section TO VERIFY. Promotion pending: dti.revolving_uses_min_payment.",
)


# --------------------------------------------------------------------------- #
# PROPERTY / APPRAISAL (B4-1.x, B2-3)
# --------------------------------------------------------------------------- #

CONV_PROPERTY_APPRAISAL_AGE = conv_rule(
    "conv.property.appraisal_age",
    reads=("property.appraisal_age_months",),
    condition=Condition(op=Operator.LE, value=Decimal("4"), unit="months"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.PROPERTY,
    description="The appraisal effective date is no more than 4 months from the note date.",
    source=sg("B4-1.2-04"),
    notes=(
        "STARTER — parallels the 4-month doc age; an appraisal update applies in reuse cases. "
        "Promotion pending: property.appraisal_age_months."
    ),
)

CONV_PROPERTY_GENERAL_ELIGIBILITY = conv_rule(
    "conv.property.general_eligibility",
    reads=("property.is_eligible_type",),
    condition=_PRESENT,
    severity=RuleSeverity.RED,
    category=FindingCategory.PROPERTY,
    description="The property is an eligible residential real-property type (not hotel/houseboat/timeshare).",
    source=sg("B2-3-01"),
    notes=(
        "STARTER — residential, secured by real property, fee-simple/leasehold/co-op title; condo/co-op "
        "hotels, houseboats, timeshares are ineligible. Promotion pending: property.is_eligible_type."
    ),
)

CONV_PROPERTY_VALUE_ACCEPTANCE = conv_rule(
    "conv.property.value_acceptance_or_appraisal",
    reads=("property.appraisal_or_waiver_present",),
    condition=_PRESENT,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.PROPERTY,
    description="An appraisal — or a DU value-acceptance (appraisal waiver) — is present.",
    source=sg("B4-1.4-11"),
    notes=(
        "STARTER — value acceptance is DU-DRIVEN (DU may offer it); this checks an appraisal OR a "
        "waiver is present, not a fabricated rule. Promotion pending: property.appraisal_or_waiver_present."
    ),
)

CONV_PROPERTY_OCCUPANCY = conv_rule(
    "conv.property.occupancy_eligibility",
    reads=("property.occupancy_eligible",),
    condition=_PRESENT,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.PROPERTY,
    description="Occupancy (primary/second/investment) is eligible for the LTV/score offered.",
    source=sg("Eligibility Matrix", to_verify=True),
    notes=(
        "STARTER — ELIGIBILITY-MATRIX-DRIVEN (occupancy + units drive LTV/score); not hardcoded here. "
        "Promotion pending: property.occupancy_eligible."
    ),
)

CONV_PROPERTY_UNITS = conv_rule(
    "conv.property.units_eligibility",
    reads=("property.unit_count",),
    condition=Condition(op=Operator.LE, value=Decimal("4"), unit="count"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.PROPERTY,
    description="The property has 1-4 units (standard Conventional).",
    source=sg("B2-3-01", to_verify=True),
    notes="STARTER — section/units TO VERIFY. Promotion pending: property.unit_count.",
)

CONV_PROPERTY_SUBJECT_PRESENT = conv_rule(
    "conv.property.subject_property_present",
    reads=("property.present",),
    condition=_PRESENT,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.PROPERTY,
    description="A subject property is recorded on the file.",
    source=sg("B2-3-01"),
    notes="STARTER — EVALUABLE from the file's property record (promoted: property.present).",
)

CONV_PROPERTY_TITLE = conv_rule(
    "conv.property.title_eligibility",
    reads=("property.title_eligible",),
    condition=_PRESENT,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.PROPERTY,
    description="Title is held as an eligible estate (fee simple / leasehold / co-op).",
    source=sg("B2-3-01"),
    notes="STARTER. Promotion pending: property.title_eligible.",
)

CONV_PROPERTY_APPRAISED_VALUE = conv_rule(
    "conv.property.appraised_value_supports_value",
    reads=("property.appraised_value_present",),
    condition=_PRESENT,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.PROPERTY,
    description="An appraised value is present to support the LTV (when no waiver applies).",
    source=sg("B4-1.2-04", to_verify=True),
    notes="STARTER — section TO VERIFY. Promotion pending: property.appraised_value_present.",
)

CONV_PROPERTY_DECLINING_MARKET = conv_rule(
    "conv.property.declining_market_review",
    reads=("property.declining_market",),
    condition=_ABSENT,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.PROPERTY,
    description="A declining-market indication is reviewed (may affect max LTV).",
    source=sg("B4-1.4", to_verify=True),
    notes="STARTER — section TO VERIFY. Promotion pending: property.declining_market.",
)


# --------------------------------------------------------------------------- #
# DOCUMENTATION / CLOSING (B1-1, B4-2.1)
# --------------------------------------------------------------------------- #

CONV_DOCS_DOCUMENT_AGE = conv_rule(
    "conv.docs.document_age",
    reads=("documents.most_recent_age_months",),
    condition=Condition(op=Operator.LE, value=Decimal("4"), unit="months"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.DOCUMENTATION,
    description="Documents are no more than 4 months old on the note date (most-recent determines age).",
    source=sg("B1-1-03"),
    notes=(
        "STARTER — the umbrella 4-month doc age across credit/income/asset/appraisal (LP-82 has the "
        "category-specific income/asset variants). Promotion pending: documents.most_recent_age_months."
    ),
)

CONV_DOCS_APPLICATION_PACKAGE = conv_rule(
    "conv.docs.application_package_present",
    reads=("documents.application.signed_present",),
    condition=_PRESENT,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.DOCUMENTATION,
    description="The signed application (1003) is present in the package.",
    source=sg("B1-1-01"),
    notes="STARTER. Promotion pending: documents.application.signed_present.",
)

CONV_DOCS_DISCLOSURES = conv_rule(
    "conv.docs.disclosures_present",
    reads=("documents.disclosures_present",),
    condition=_PRESENT,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.DOCUMENTATION,
    description="Required disclosures are present in the package.",
    source=sg("B1-1-01", to_verify=True),
    notes="STARTER — section TO VERIFY. Promotion pending: documents.disclosures_present.",
)

CONV_DOCS_CONDO_PROJECT_REVIEW = conv_rule(
    "conv.docs.condo_project_review",
    reads=("documents.condo.project_review_present",),
    condition=_PRESENT,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.DOCUMENTATION,
    gate=_CONDO,
    description="Project review documentation is present for a condo/co-op/PUD property.",
    source=sg("B4-2.1-01"),
    notes=(
        "STARTER — APPLICABILITY-GATED to condo properties (gate: property.is_condo). Promotion "
        "pending: documents.condo.project_review_present."
    ),
)

CONV_DOCS_TAX_TRANSCRIPT = conv_rule(
    "conv.docs.tax_transcript_authorization",
    reads=("documents.tax_transcript_authorized",),
    condition=_PRESENT,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.DOCUMENTATION,
    description="An IRS Form 4506-C / tax-transcript authorization is present where returns are required.",
    source=sg("B3-3.1"),
    notes=(
        "STARTER — cross-links LP-82's self-employment (returns required). Promotion pending: "
        "documents.tax_transcript_authorized."
    ),
)

CONV_DOCS_PURCHASE_AGREEMENT = conv_rule(
    "conv.docs.purchase_agreement_present",
    reads=("documents.purchase_agreement_present",),
    condition=_PRESENT,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.DOCUMENTATION,
    description="A purchase agreement is present (purchase transactions).",
    source=sg("B1-1-01", to_verify=True),
    notes="STARTER — section TO VERIFY. Promotion pending: documents.purchase_agreement_present.",
)

CONV_DOCS_FLOOD_CERT = conv_rule(
    "conv.docs.flood_certification_present",
    reads=("documents.flood_certification_present",),
    condition=_PRESENT,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.DOCUMENTATION,
    description="A flood-zone determination/certification is present.",
    source=sg("B7-3", to_verify=True),
    notes="STARTER — section TO VERIFY. Promotion pending: documents.flood_certification_present.",
)

CONV_DOCS_PHOTO_ID = conv_rule(
    "conv.docs.photo_id_present",
    reads=("documents.photo_id_present",),
    condition=_PRESENT,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.DOCUMENTATION,
    description="Borrower photo identification is present (closing/compliance).",
    source=sg("B1-1-01", to_verify=True),
    notes="STARTER — section TO VERIFY. Promotion pending: documents.photo_id_present.",
)


CONVENTIONAL_CREDIT_RULES: tuple[VerificationRule, ...] = (
    CONV_CREDIT_MIN_SCORE_MANUAL,
    CONV_CREDIT_MIN_SCORE_DELIVERY_FLOOR,
    CONV_CREDIT_REPORT_PRESENT,
    CONV_CREDIT_REPRESENTATIVE_SCORE_PRESENT,
    CONV_CREDIT_DEROG_FORECLOSURE,
    CONV_CREDIT_DEROG_BANKRUPTCY,
    CONV_CREDIT_DEROG_SHORT_SALE,
    CONV_CREDIT_TRADELINES,
)

CONVENTIONAL_DTI_RULES: tuple[VerificationRule, ...] = (
    CONV_DTI_MAX_MANUAL,
    CONV_DTI_REUNDERWRITE_UNDISCLOSED,
    CONV_DTI_OBLIGATIONS_10_MONTHS,
    CONV_DTI_BUSINESS_DEBT,
    CONV_DTI_REVOLVING_MIN_PAYMENT,
)

CONVENTIONAL_PROPERTY_RULES: tuple[VerificationRule, ...] = (
    CONV_PROPERTY_APPRAISAL_AGE,
    CONV_PROPERTY_GENERAL_ELIGIBILITY,
    CONV_PROPERTY_VALUE_ACCEPTANCE,
    CONV_PROPERTY_OCCUPANCY,
    CONV_PROPERTY_UNITS,
    CONV_PROPERTY_SUBJECT_PRESENT,
    CONV_PROPERTY_TITLE,
    CONV_PROPERTY_APPRAISED_VALUE,
    CONV_PROPERTY_DECLINING_MARKET,
)

CONVENTIONAL_DOC_RULES: tuple[VerificationRule, ...] = (
    CONV_DOCS_DOCUMENT_AGE,
    CONV_DOCS_APPLICATION_PACKAGE,
    CONV_DOCS_DISCLOSURES,
    CONV_DOCS_CONDO_PROJECT_REVIEW,
    CONV_DOCS_TAX_TRANSCRIPT,
    CONV_DOCS_PURCHASE_AGREEMENT,
    CONV_DOCS_FLOOD_CERT,
    CONV_DOCS_PHOTO_ID,
)

# The full LP-83 set (~30): credit (8) + DTI (5) + property (9) + documentation (8).
CONVENTIONAL_CREDIT_PROPERTY_DOC_RULES: tuple[VerificationRule, ...] = (
    *CONVENTIONAL_CREDIT_RULES,
    *CONVENTIONAL_DTI_RULES,
    *CONVENTIONAL_PROPERTY_RULES,
    *CONVENTIONAL_DOC_RULES,
)

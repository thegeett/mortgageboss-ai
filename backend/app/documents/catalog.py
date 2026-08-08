"""The document-type catalog — the single source of truth for tier + category (LP-58).

Phase 2 scales the document pipeline from 3 types to ~80-100 via a **three-tier**
model (:class:`~app.models.document.Tier`): not every type earns full structured
extraction. This catalog is where that knowledge lives — one maintainable mapping
of ``document_type -> (tier, category)`` that the pipeline consults *after*
classification to route a document to the right handling path:

  * **Tier 1** → the existing :data:`app.ai.extraction.EXTRACTORS` registry (full
    structured extraction). The 3 Phase-1 types (``pay_stub`` / ``w2`` /
    ``bank_statement``) are Tier 1 and unchanged. The other Tier-1 types are
    *cataloged* here now; their extractors register in LP-60..64.
  * **Tier 2** → recognized: classified + categorized + (LP-65) a short summary.
  * **Tier 3** → long-tail: a generic analyzer (LP-66). Anything not in the
    catalog defaults here.

Why a catalog and not scattered ``if/elif`` or a DB table:

  * **Maintainable** — adding/retiring a type is a one-line edit; no migration
    (tier/category are app-layer knowledge, ADR-053/ADR-167), no code branches.
  * **Single source of truth** — both the tier (for routing) and the category
    (for filing / needs-matching) come from here, so they never drift apart.

The catalog now spans the **full ~80-type taxonomy** (LP-59): ~18 Tier-1 types
plus a comprehensive Tier-2 set across the seven categories. It is an
INDUSTRY-STANDARD STARTER — the document types a US residential mortgage file
typically draws on — **not** yet validated against the resident domain expert's
(Priya's) real library; expect it to **refine with Priya** and per-type accuracy
to be confirmed against real labeled documents over time.

The catalog is also the source of truth for the classifier's **type list**: the
classification prompt is built from these slugs (see
:mod:`app.ai.classification_prompt`), so the two cannot drift — a type the
classifier can return is a type the catalog knows, and vice versa.
"""

from app.models.document import DocumentCategory, Tier

# --------------------------------------------------------------------------- #
# The catalog — document_type -> (tier, category)
# --------------------------------------------------------------------------- #
# The slugs match the classifier's lowercase ``document_type`` output. Organized
# by CATEGORY (then tier within it) so it reads as a maintainable taxonomy — the
# same by-category structure the classification prompt uses. The ~18 Tier-1 types
# (full extraction, LP-60..64) are marked; everything else is Tier 2 (recognized).
#
# This is an INDUSTRY-STANDARD STARTER taxonomy (LP-59): the document types a US
# residential mortgage file typically draws on. It is **not** validated against
# the resident domain expert's (Priya's) real document library yet — that review
# is deferred. Treat it as a strong starting point to **refine with Priya**, and
# expect per-type accuracy to be validated against real labeled documents over
# time. Maintainable by design: add/rename/retier a type with a one-line edit
# (and add its recognition indicators in app/ai/classification_prompt.py — a test
# keeps the two in sync).
CATALOG: dict[str, tuple[Tier, DocumentCategory]] = {
    # ===================================================================== #
    # Income / Employment
    # ===================================================================== #
    "pay_stub": (Tier.TIER_1, DocumentCategory.INCOME_EMPLOYMENT),  # T1
    "w2": (Tier.TIER_1, DocumentCategory.INCOME_EMPLOYMENT),  # T1
    "1099": (Tier.TIER_1, DocumentCategory.INCOME_EMPLOYMENT),  # T1
    "tax_return": (Tier.TIER_1, DocumentCategory.INCOME_EMPLOYMENT),  # T1
    "voe": (Tier.TIER_1, DocumentCategory.INCOME_EMPLOYMENT),  # T1
    "profit_and_loss": (Tier.TIER_1, DocumentCategory.INCOME_EMPLOYMENT),  # T1
    "tax_transcript": (Tier.TIER_2, DocumentCategory.INCOME_EMPLOYMENT),
    "form_4506c": (Tier.TIER_2, DocumentCategory.INCOME_EMPLOYMENT),
    "business_tax_return": (Tier.TIER_1, DocumentCategory.INCOME_EMPLOYMENT),
    "k1_statement": (
        Tier.TIER_1,
        DocumentCategory.INCOME_EMPLOYMENT,
    ),  # LP-442: merge target (k_1_schedule spec)
    "social_security_award_letter": (Tier.TIER_1, DocumentCategory.INCOME_EMPLOYMENT),
    "pension_statement": (Tier.TIER_2, DocumentCategory.INCOME_EMPLOYMENT),
    "retirement_income_letter": (Tier.TIER_2, DocumentCategory.INCOME_EMPLOYMENT),
    "unemployment_income_letter": (Tier.TIER_2, DocumentCategory.INCOME_EMPLOYMENT),
    "disability_income_letter": (Tier.TIER_2, DocumentCategory.INCOME_EMPLOYMENT),
    "child_support_income": (
        Tier.TIER_1,
        DocumentCategory.INCOME_EMPLOYMENT,
    ),  # LP-442: split target
    "alimony_income": (Tier.TIER_1, DocumentCategory.INCOME_EMPLOYMENT),  # LP-442: split target
    "rental_income_schedule": (Tier.TIER_2, DocumentCategory.INCOME_EMPLOYMENT),
    "commission_income_statement": (Tier.TIER_2, DocumentCategory.INCOME_EMPLOYMENT),
    "employment_offer_letter": (Tier.TIER_1, DocumentCategory.INCOME_EMPLOYMENT),
    # LP-442 — schema'd types reconciled into the catalog (every one has a spec → Tier-1).
    "form_1040_personal_tax_transcripts": (Tier.TIER_1, DocumentCategory.INCOME_EMPLOYMENT),
    "form_1065_partnership_tax_transcripts": (Tier.TIER_1, DocumentCategory.INCOME_EMPLOYMENT),
    "form_1120_corporate_tax_transcripts": (Tier.TIER_1, DocumentCategory.INCOME_EMPLOYMENT),
    "form_4506t_request_for_transcript": (Tier.TIER_1, DocumentCategory.INCOME_EMPLOYMENT),
    "transcripts_of_1099": (Tier.TIER_1, DocumentCategory.INCOME_EMPLOYMENT),
    "k_1_shareholder_profit_and_loss_transcripts": (
        Tier.TIER_1,
        DocumentCategory.INCOME_EMPLOYMENT,
    ),
    "trust_federal_tax_returns": (Tier.TIER_1, DocumentCategory.INCOME_EMPLOYMENT),
    "cpa_letter": (Tier.TIER_1, DocumentCategory.INCOME_EMPLOYMENT),
    "business_existence_verification_cpa_ltr_bus_lic": (
        Tier.TIER_1,
        DocumentCategory.INCOME_EMPLOYMENT,
    ),
    "business_license": (Tier.TIER_1, DocumentCategory.INCOME_EMPLOYMENT),
    "disability_award_letter": (Tier.TIER_1, DocumentCategory.INCOME_EMPLOYMENT),
    "retirement_pension_award_letter": (Tier.TIER_1, DocumentCategory.INCOME_EMPLOYMENT),
    "retirement_check": (Tier.TIER_1, DocumentCategory.INCOME_EMPLOYMENT),
    "verbal_voe": (Tier.TIER_1, DocumentCategory.INCOME_EMPLOYMENT),
    "military_leave_and_earning_statement_les": (Tier.TIER_1, DocumentCategory.INCOME_EMPLOYMENT),
    "foster_care_verification": (Tier.TIER_1, DocumentCategory.INCOME_EMPLOYMENT),
    "boarder_rental_payments": (Tier.TIER_1, DocumentCategory.INCOME_EMPLOYMENT),
    "boarder_proof_of_residency": (Tier.TIER_1, DocumentCategory.INCOME_EMPLOYMENT),
    "cancelled_checks_evidencing_receipt_of_note_income": (
        Tier.TIER_1,
        DocumentCategory.INCOME_EMPLOYMENT,
    ),
    # ===================================================================== #
    # Assets
    # ===================================================================== #
    "bank_statement": (Tier.TIER_1, DocumentCategory.ASSETS),  # T1
    "investment_account": (Tier.TIER_1, DocumentCategory.ASSETS),  # T1
    "retirement_account": (Tier.TIER_1, DocumentCategory.ASSETS),  # T1
    "gift_letter": (Tier.TIER_1, DocumentCategory.ASSETS),  # T1
    "verification_of_deposit": (Tier.TIER_1, DocumentCategory.ASSETS),
    "brokerage_statement": (Tier.TIER_2, DocumentCategory.ASSETS),
    "money_market_statement": (Tier.TIER_2, DocumentCategory.ASSETS),
    "certificate_of_deposit": (Tier.TIER_2, DocumentCategory.ASSETS),
    "earnest_money_receipt": (Tier.TIER_1, DocumentCategory.ASSETS),
    "gift_donor_bank_statement": (Tier.TIER_2, DocumentCategory.ASSETS),
    "life_insurance_statement": (Tier.TIER_2, DocumentCategory.ASSETS),
    "sale_of_asset_proof": (Tier.TIER_2, DocumentCategory.ASSETS),
    "crypto_account_statement": (Tier.TIER_2, DocumentCategory.ASSETS),
    # LP-442 — schema'd asset types.
    "ira_401k": (Tier.TIER_1, DocumentCategory.ASSETS),
    "bank_deposit_slip": (Tier.TIER_1, DocumentCategory.ASSETS),
    "emd_withdrawal_proof": (Tier.TIER_1, DocumentCategory.ASSETS),
    "life_insurance_policy": (Tier.TIER_1, DocumentCategory.ASSETS),
    "verification_of_assets": (Tier.TIER_1, DocumentCategory.ASSETS),
    "financial_statements": (Tier.TIER_1, DocumentCategory.ASSETS),
    "statement_of_account": (Tier.TIER_1, DocumentCategory.ASSETS),
    # ===================================================================== #
    # Property
    # ===================================================================== #
    "purchase_agreement": (Tier.TIER_1, DocumentCategory.PROPERTY),  # T1
    "homeowners_insurance": (Tier.TIER_1, DocumentCategory.PROPERTY),  # T1
    "mortgage_statement": (Tier.TIER_1, DocumentCategory.PROPERTY),  # T1
    "property_tax_bill": (Tier.TIER_1, DocumentCategory.PROPERTY),  # T1
    "hoa_statement": (Tier.TIER_1, DocumentCategory.PROPERTY),  # T1
    "appraisal": (Tier.TIER_1, DocumentCategory.PROPERTY),
    "title_commitment": (Tier.TIER_1, DocumentCategory.PROPERTY),
    "preliminary_title_report": (Tier.TIER_2, DocumentCategory.PROPERTY),
    "flood_certification": (Tier.TIER_1, DocumentCategory.PROPERTY),
    "flood_insurance_policy": (Tier.TIER_1, DocumentCategory.PROPERTY),
    "survey": (Tier.TIER_1, DocumentCategory.PROPERTY),
    "warranty_deed": (Tier.TIER_2, DocumentCategory.PROPERTY),
    "home_inspection_report": (Tier.TIER_2, DocumentCategory.PROPERTY),
    "pest_inspection_report": (Tier.TIER_2, DocumentCategory.PROPERTY),
    "well_septic_certification": (Tier.TIER_2, DocumentCategory.PROPERTY),
    "condo_questionnaire": (Tier.TIER_1, DocumentCategory.PROPERTY),
    "payoff_statement": (
        Tier.TIER_1,
        DocumentCategory.PROPERTY,
    ),  # LP-442: merge target (mortgage_payoff spec)
    "lease_agreement": (Tier.TIER_1, DocumentCategory.PROPERTY),
    # LP-442 — schema'd property types.
    "master_insurance_policy_for_condominium": (Tier.TIER_1, DocumentCategory.PROPERTY),
    "building_permits": (Tier.TIER_1, DocumentCategory.PROPERTY),
    "hoa_certification": (Tier.TIER_1, DocumentCategory.PROPERTY),
    "homeowner_s_insurance_quote": (Tier.TIER_1, DocumentCategory.PROPERTY),
    "termite_report": (Tier.TIER_1, DocumentCategory.PROPERTY),
    "termite_completion": (Tier.TIER_1, DocumentCategory.PROPERTY),
    "property_profile_subject": (Tier.TIER_1, DocumentCategory.PROPERTY),
    "property_profile_non_subject": (Tier.TIER_1, DocumentCategory.PROPERTY),
    "property_tax_bill_non_subject": (Tier.TIER_1, DocumentCategory.PROPERTY),
    "proof_of_occupancy": (Tier.TIER_1, DocumentCategory.PROPERTY),
    "subject_property_note": (Tier.TIER_1, DocumentCategory.PROPERTY),
    "other_property_note": (Tier.TIER_1, DocumentCategory.PROPERTY),
    "seller_signature_authority": (Tier.TIER_1, DocumentCategory.PROPERTY),
    # LP-466 — an AVM / Home Value Estimate. NOT an appraisal and NOT evidence of value for
    # underwriting (see the indicator + ADR); a non-binding estimate a processor may glance at.
    "home_value_estimate": (Tier.TIER_1, DocumentCategory.PROPERTY),
    # ===================================================================== #
    # Credit
    # ===================================================================== #
    "credit_report": (Tier.TIER_1, DocumentCategory.CREDIT),
    "credit_explanation_letter": (Tier.TIER_2, DocumentCategory.CREDIT),
    "credit_supplement": (Tier.TIER_2, DocumentCategory.CREDIT),
    "bankruptcy_discharge": (Tier.TIER_1, DocumentCategory.CREDIT),
    "foreclosure_documentation": (Tier.TIER_2, DocumentCategory.CREDIT),
    "judgment_documentation": (Tier.TIER_2, DocumentCategory.CREDIT),
    "collection_account_letter": (Tier.TIER_2, DocumentCategory.CREDIT),
    "debt_payoff_statement": (Tier.TIER_2, DocumentCategory.CREDIT),
    "student_loan_statement": (Tier.TIER_2, DocumentCategory.CREDIT),
    "installment_loan_statement": (Tier.TIER_2, DocumentCategory.CREDIT),
    # LP-442 — schema'd credit types.
    "bankruptcy_filing": (Tier.TIER_1, DocumentCategory.CREDIT),
    "unsecured_note": (Tier.TIER_1, DocumentCategory.CREDIT),
    "verification_of_mortgage": (Tier.TIER_1, DocumentCategory.CREDIT),
    "verification_of_rent": (Tier.TIER_1, DocumentCategory.CREDIT),
    # ===================================================================== #
    # Disclosures
    # ===================================================================== #
    "closing_disclosure": (Tier.TIER_2, DocumentCategory.DISCLOSURES),
    "loan_estimate": (Tier.TIER_2, DocumentCategory.DISCLOSURES),
    # LP-442 decision 2: the generic borrower_authorization is RETIRED — the two
    # authorization specs (authorization_to_run_credit, borrower_authorization_and_certification)
    # are distinct documents and cannot share a key. Verified unused (no rule/fixture/test).
    "intent_to_proceed": (Tier.TIER_2, DocumentCategory.DISCLOSURES),
    "notice_of_right_to_cancel": (Tier.TIER_2, DocumentCategory.DISCLOSURES),
    "truth_in_lending": (Tier.TIER_2, DocumentCategory.DISCLOSURES),
    "servicing_disclosure": (Tier.TIER_2, DocumentCategory.DISCLOSURES),
    "affiliated_business_disclosure": (
        Tier.TIER_1,
        DocumentCategory.DISCLOSURES,
    ),  # LP-442: merge target (aba spec)
    "privacy_notice": (Tier.TIER_2, DocumentCategory.DISCLOSURES),
    "e_consent_disclosure": (
        Tier.TIER_1,
        DocumentCategory.DISCLOSURES,
    ),  # LP-442: merge target (consent spec)
    # LP-442 — schema'd disclosure/authorization types (decision 2 splits the two auth docs).
    "authorization_to_run_credit": (Tier.TIER_1, DocumentCategory.DISCLOSURES),
    "borrower_authorization_and_certification": (Tier.TIER_1, DocumentCategory.DISCLOSURES),
    "borrower_s_authorization_for_counseling": (Tier.TIER_1, DocumentCategory.DISCLOSURES),
    "credit_card_authorization": (Tier.TIER_1, DocumentCategory.DISCLOSURES),
    "social_security_administration_ssa_89": (Tier.TIER_1, DocumentCategory.DISCLOSURES),
    "mortgage_loan_origination_agreement": (Tier.TIER_1, DocumentCategory.DISCLOSURES),
    "prior_closing_disclosure_final_cd_from_purchase": (Tier.TIER_1, DocumentCategory.DISCLOSURES),
    # LP-465 — a temporary buydown reduces the borrower's actual payment below the note
    # payment for the first 1-2 years; the per-period schedule + rates are structured data a
    # rule (and the processor) reads → Tier 1. (Promoted from `unknown`.)
    "temporary_buydown_agreement": (Tier.TIER_1, DocumentCategory.DISCLOSURES),
    # ===================================================================== #
    # Borrower Info
    # ===================================================================== #
    "drivers_license": (Tier.TIER_1, DocumentCategory.BORROWER_INFO),  # T1
    "divorce_decree": (Tier.TIER_1, DocumentCategory.BORROWER_INFO),  # T1
    "letter_of_explanation": (Tier.TIER_1, DocumentCategory.BORROWER_INFO),  # T1
    "passport": (Tier.TIER_2, DocumentCategory.BORROWER_INFO),
    "social_security_card": (Tier.TIER_1, DocumentCategory.BORROWER_INFO),
    "permanent_resident_card": (Tier.TIER_1, DocumentCategory.BORROWER_INFO),
    "visa_documentation": (Tier.TIER_2, DocumentCategory.BORROWER_INFO),
    "birth_certificate": (Tier.TIER_1, DocumentCategory.BORROWER_INFO),
    "marriage_certificate": (Tier.TIER_2, DocumentCategory.BORROWER_INFO),
    "military_id": (Tier.TIER_2, DocumentCategory.BORROWER_INFO),
    "power_of_attorney": (Tier.TIER_2, DocumentCategory.BORROWER_INFO),
    "trust_documentation": (Tier.TIER_2, DocumentCategory.BORROWER_INFO),
    "name_affidavit": (Tier.TIER_2, DocumentCategory.BORROWER_INFO),
    # LP-442 — schema'd borrower-info types (incl. the 5 topical LOE variants + application LOE).
    "government_issued_id": (Tier.TIER_1, DocumentCategory.BORROWER_INFO),
    "work_visa_ead_card": (Tier.TIER_1, DocumentCategory.BORROWER_INFO),
    "court_order_documents": (Tier.TIER_1, DocumentCategory.BORROWER_INFO),
    "trust_agreement": (Tier.TIER_1, DocumentCategory.BORROWER_INFO),
    "trust_documents": (Tier.TIER_1, DocumentCategory.BORROWER_INFO),
    "application_loe": (Tier.TIER_1, DocumentCategory.BORROWER_INFO),
    "letter_of_explanation_asset": (Tier.TIER_1, DocumentCategory.BORROWER_INFO),
    "letter_of_explanation_child_care": (Tier.TIER_1, DocumentCategory.BORROWER_INFO),
    "letter_of_explanation_income": (Tier.TIER_1, DocumentCategory.BORROWER_INFO),
    "letter_of_explanation_misc": (Tier.TIER_1, DocumentCategory.BORROWER_INFO),
    "letter_of_explanation_property": (Tier.TIER_1, DocumentCategory.BORROWER_INFO),
    # LP-465 — a USCIS Notice of Action (Form I-797A/B/C) feeds ID-8 (citizenship/residency);
    # its receipt/case/validity + I-94 block are structured facts → Tier 1. Sits with the
    # immigration/identity family. (Promoted from `unknown`; absorbs I-797 misroutes to
    # visa_documentation / work_visa_ead_card.)
    "uscis_notice_of_action": (Tier.TIER_1, DocumentCategory.BORROWER_INFO),
    # ===================================================================== #
    # Misc — recognized loan-file documents that don't fit the buckets above.
    # (The Tier-3 default below catches anything UNCATALOGED; these are known.)
    # ===================================================================== #
    "uniform_residential_loan_application": (Tier.TIER_1, DocumentCategory.MISC),
    "underwriting_approval": (Tier.TIER_2, DocumentCategory.MISC),
    "rate_lock_agreement": (Tier.TIER_2, DocumentCategory.MISC),
    "general_correspondence": (Tier.TIER_2, DocumentCategory.MISC),
    # LP-442 — schema'd misc types.
    "aus_findings": (Tier.TIER_1, DocumentCategory.MISC),
    "certificate_of_eligibility": (Tier.TIER_1, DocumentCategory.MISC),
    "appraisal_payment": (Tier.TIER_1, DocumentCategory.MISC),
    "evidence_of_payment": (Tier.TIER_1, DocumentCategory.MISC),
    "custom": (Tier.TIER_1, DocumentCategory.MISC),
    "miscellaneous_document": (Tier.TIER_1, DocumentCategory.MISC),
    # LP-466 — closing/settlement wire instructions (typed + MASKED routing/account; was landing in
    # general_correspondence free-form + unmasked) and a lender-portal dashboard screenshot (identity
    # only — a software capture, extracts almost nothing by design; stops diluting `unknown`).
    "wire_instructions": (Tier.TIER_1, DocumentCategory.MISC),
    "lender_dashboard_screenshot": (Tier.TIER_1, DocumentCategory.MISC),
}

# The default for any type not in the catalog: the long-tail Tier 3 / Misc bucket.
# A confidently-classified but uncataloged type lands here (the generic analyzer,
# LP-66); a low-confidence/unknown classification is gated to NEEDS_REVIEW by the
# pipeline before it ever reaches tier routing.
_DEFAULT: tuple[Tier, DocumentCategory] = (Tier.TIER_3, DocumentCategory.MISC)


def get_tier_and_category(document_type: str | None) -> tuple[Tier, DocumentCategory]:
    """Look up a document type's ``(tier, category)`` — the catalog's core read.

    Unknown or absent types fall back to the long-tail default
    (Tier 3 / Misc). Never raises — every document gets a tier + category.
    """
    if not document_type:
        return _DEFAULT
    return CATALOG.get(document_type, _DEFAULT)


def get_tier(document_type: str | None) -> Tier:
    """The tier the pipeline should handle ``document_type`` as (default Tier 3)."""
    return get_tier_and_category(document_type)[0]


def get_category(document_type: str | None) -> DocumentCategory:
    """The filing category for ``document_type`` (default Misc).

    Catalog-driven (LP-58) — replaces the Phase-1 provisional type→category map.
    """
    return get_tier_and_category(document_type)[1]


def is_cataloged(document_type: str | None) -> bool:
    """Whether ``document_type`` is a known (cataloged) type, vs. long-tail."""
    return bool(document_type) and document_type in CATALOG


def types_for_category(category: DocumentCategory) -> list[str]:
    """All cataloged type slugs in ``category``, in catalog (insertion) order.

    The classification prompt groups its type listing by category using this, so
    the prompt's structure is driven by the catalog — one source of truth.
    """
    return [slug for slug, (_, cat) in CATALOG.items() if cat is category]

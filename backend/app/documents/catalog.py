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

from collections.abc import Callable
from dataclasses import dataclass

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
    # LP-468 — an employer-issued annual compensation/rewards statement (base + bonus + equity). The home
    # for the Deloitte/Fidelity/PayPal docs that were force-fitting into commission_income_statement. No
    # rule today; the direct input to IN-10/IN-11 once the earnings classifier exists.
    "compensation_statement": (Tier.TIER_1, DocumentCategory.INCOME_EMPLOYMENT),
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
    # LP-642 — the SUBJECT-PROPERTY RENT SCHEDULES. Fannie B3-3.8-02 (09/02/2026) makes one of these
    # MANDATORY where rental income is used to qualify: "a Single-Family Comparable Rent Schedule
    # (Form 1007) or Small Residential Income Property Appraisal Report (Form 1025), as applicable".
    # Until now neither existed as a type, so the one document a rental purchase cannot qualify
    # without could be neither requested nor filed — `activation_bars.yaml` recorded that as a
    # limitation and SEL-2026-08 turned it into a blocker.
    #
    # TIER 2, NOT TIER 1, DELIBERATELY. Tier 2 is classified + categorised + summarised, with no
    # structured extraction — which is what a type needs to be REQUESTABLE and FILEABLE. Reading the
    # market rent off the form is a separate step with its own accuracy question (LP-642), and
    # cataloguing at Tier 1 would claim an extractor that does not exist.
    "comparable_rent_schedule": (Tier.TIER_2, DocumentCategory.PROPERTY),  # Form 1007, one-unit
    "small_residential_income_appraisal": (
        Tier.TIER_2,
        DocumentCategory.PROPERTY,
    ),  # Form 1025, 2-4
    "purchase_agreement": (Tier.TIER_1, DocumentCategory.PROPERTY),  # T1
    "homeowners_insurance": (Tier.TIER_1, DocumentCategory.PROPERTY),  # T1
    "mortgage_statement": (Tier.TIER_1, DocumentCategory.PROPERTY),  # T1
    # LP-469 — IRS Form 1098 Mortgage Interest Statement. PROPERTY (not INCOME like form_1099): its subject is
    # a mortgage on a property, and its neighbours are mortgage_statement / property_tax_bill. DT-6 reads the
    # interest + taxes + principal as a housing expense on a (often retained) property.
    "form_1098": (Tier.TIER_1, DocumentCategory.PROPERTY),
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
    # LP-467 — an ACORD 25 liability CERTIFICATE (a summary of coverage, distinct from the master
    # POLICY; joins the insurance family here as there is no INSURANCE category). Visibility only —
    # serves no rule; NOTE it is NOT CO-3 evidence (CO-3 wants ACORD 27/28 property + a fidelity cert).
    "certificate_of_liability_insurance": (Tier.TIER_1, DocumentCategory.PROPERTY),
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
    # A revolving-account statement. The catalog carried `installment_loan_statement` and
    # `student_loan_statement` but nothing for the commonest consumer debt of all, so a need asking
    # for one named a document the classifier could not produce and no upload could ever clear
    # (bug-009).
    "credit_card_statement": (Tier.TIER_2, DocumentCategory.CREDIT),
    # LP-442 — schema'd credit types.
    "bankruptcy_filing": (Tier.TIER_1, DocumentCategory.CREDIT),
    "unsecured_note": (Tier.TIER_1, DocumentCategory.CREDIT),
    "verification_of_mortgage": (Tier.TIER_1, DocumentCategory.CREDIT),
    "verification_of_rent": (Tier.TIER_1, DocumentCategory.CREDIT),
    # ===================================================================== #
    # Disclosures
    # ===================================================================== #
    # LP-470 — promoted Tier 2 -> Tier 1 with a HEADLINE-block schema (spec 119/120). No in-scope rule reads
    # a CD/LE (CL-2..7, DC-1..7 are out of pre-submission scope), so they earn Tier 1 on processor visibility;
    # the full cost tables / transaction summaries stay on Tier 3 (ADR).
    "closing_disclosure": (Tier.TIER_1, DocumentCategory.DISCLOSURES),
    "loan_estimate": (Tier.TIER_1, DocumentCategory.DISCLOSURES),
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
    "passport": (Tier.TIER_1, DocumentCategory.BORROWER_INFO),  # LP-472 — shared identity extractor
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
    # LP-467 — one generic vendor service invoice (a BILL: vendor/amount/loan; distinct from the
    # evidence_of_payment/appraisal_payment RECEIPT types). Visibility only — serves no rule.
    "service_invoice": (Tier.TIER_1, DocumentCategory.MISC),
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


#: Slugs of one word are NOT matched against a free-text name (LP-636 defect 5). "survey",
#: "appraisal", "w2" and the like appear inside ordinary prose — "the appraisal is attached", "a
#: letter about the survey" — so a one-word match is a coin flip. Multi-word slugs are specific
#: enough that an ordered match means what it says.
_MIN_SLUG_WORDS_FOR_NAME_MATCH = 2
#: An upper bound for the explanation's band searches — no catalog slug is near this long.
_MAX_SLUG_WORDS = 32

#: Tokens allowed BETWEEN consecutive slug words. 1, because the case this tolerance exists for —
#: "Earnest Money / EMD Receipt" → ``earnest_money_receipt`` — has exactly one, while the
#: false-positive names it must decline have two or more.
_MAX_GAP_TOKENS = 1

#: The fraction of the name's tokens the matched slug must account for. A genuine name for a
#: document is mostly the type; a name that MENTIONS one is mostly other words. Measured on both
#: populations: true names 0.5-0.67, mentions 0.18-0.25. 0.4 sits in the gap with room either side.
#:
#: This is the guard that matters most in practice, because of WHERE the feature runs: a confident
#: ``unknown`` is very often a cover letter, a transmittal, a fax sheet or an email printout —
#: exactly the documents whose names reference OTHER documents.
_MIN_SLUG_COVERAGE = 0.4


def _normalize_for_match(text: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace: ``"a Driver's License"`` → ``"drivers license"``.

    An apostrophe is DELETED, not turned into a space. Replacing it split "driver's" into
    "driver s" and the driver's-licence case — one of the four this exists for — silently failed
    to match.
    """
    dropped = text.lower().replace("'", "").replace("\u2019", "")
    return " ".join("".join(c if c.isalnum() else " " for c in dropped).split())


def match_catalog_type(free_text: str | None) -> str | None:
    """The catalog slug that a free-text document NAME names, or ``None``.

    LP-636 defect 5. The classifier emits ``document_name`` — its own words for what the document
    is — BEFORE it makes the constrained ``document_type`` pick, and LP-463 records that the free
    name is "a more reliable signal than the constrained pick". When the pick comes back a
    confident ``unknown``, that name is the only surviving evidence that a catalog type was missed.
    On LF-ZE9N four Tier-1 types were lost this way — a driver's licence, a closing disclosure, a
    credit report and an earnest-money receipt — each routed to Tier 3 and COMPLETED with no flag.

    DELIBERATELY CONSERVATIVE, AND DELIBERATELY NOT AUTHORITATIVE. Three guards, each with a
    measured reason rather than a taste:

    * the slug's words must appear IN ORDER, with at most :data:`_MAX_GAP_TOKENS` between them;
    * the slug must account for at least :data:`_MIN_SLUG_COVERAGE` of the name's tokens;
    * one-word slugs are ignored entirely (:data:`_MIN_SLUG_WORDS_FOR_NAME_MATCH`).

    No fuzzy distance, no stemming. ``misc`` is the correct destination for a genuinely unknown
    document and must stay reachable, so a near-miss has to fall through rather than be captured.

    THE COVERAGE GUARD IS THE ONE THAT EARNS ITS KEEP, and the reason is where this runs. A
    confident ``unknown`` is very often a cover letter, a transmittal, a fax sheet or an email
    printout — precisely the documents whose names reference OTHER documents. "an email asking the
    borrower to send a bank statement" names a bank statement and is not one. Ordering alone
    cannot tell those apart; the proportion of the name the type accounts for can.

    Expect this to produce some flags a processor dismisses. That is the accepted cost of the
    asymmetry below, not a defect — but the rate is worth watching rather than assuming.

    The caller uses this to FLAG FOR REVIEW, never to apply the type. Applying a type from a name
    match would put a wrong schema on a document — the T4→w2 harm LP-463 exists to prevent — and
    the whole point of that ticket is not applying a label we do not trust. A false positive here
    therefore costs one review; a false positive in an auto-applied version would cost wrong data.

    Longest match wins, so ``prior_closing_disclosure_final_cd_from_purchase`` is preferred over
    ``closing_disclosure`` when the name carries both.
    """
    if not free_text:
        return None
    haystack = _normalize_for_match(free_text)
    if not haystack:
        return None

    tokens = haystack.split()
    best: str | None = None
    best_words = 0
    for slug in CATALOG:
        words = slug.split("_")
        if len(words) < _MIN_SLUG_WORDS_FOR_NAME_MATCH:
            continue
        if len(words) <= best_words:
            continue
        if not _matches_in_order_with_small_gaps(words, tokens):
            continue
        # COVERAGE. A genuine name for a document is mostly the type: "a driver's license" is 3
        # tokens of which 2 are the slug. A name that merely MENTIONS a type is mostly other words:
        # "an email asking the borrower to send a bank statement" is 9 tokens of which 2 are.
        # Measured on both populations the gap is clean — true names 0.5-0.67, mentions 0.18-0.25 —
        # so this is the discriminator, not the ordering rule.
        if len(words) / len(tokens) < _MIN_SLUG_COVERAGE:
            continue
        best, best_words = slug, len(words)
    return best


#: Why nothing matched (LP-639). A closed vocabulary — safe to log, unlike the name itself.
#:
#: ONE REASON PER GUARD, because a single "it did not match" cannot be acted on. `match_catalog_type`
#: applies three, and the first version of this modelled two — so a one-word catalog type named
#: EXACTLY ("Appraisal") reported the same thing as a name with no catalog words in it at all.
REJECTED_BY_COVERAGE = "coverage"
REJECTED_BY_ORDER = "order"
REJECTED_BY_MIN_WORDS = "min_words"
#: No catalog slug's words appear in the name at all — a model problem, not a matcher one.
NO_CATALOG_WORDS = "no_catalog_words"
#: A name was produced but normalised away to nothing (punctuation, or a script the normaliser
#: strips). Its own state, because sharing ``None`` with a successful match made a log query
#: counting matches silently include it.
UNUSABLE_NAME = "unusable_name"


@dataclass(frozen=True)
class CatalogMatchExplanation:
    """Why :func:`match_catalog_type` answered the way it did — WITHOUT the name (LP-639).

    THE PROBLEM THIS EXISTS FOR. When the classifier returns a confident ``unknown``, the only
    surviving evidence is the model's own ``document_name`` — free text that can quote a borrower's
    details, so it is never logged or stored. A confident ``unknown`` therefore has no account of
    itself, and diagnosing one means inferring. On LF-ZE9N the inference was wrong twice.

    Every field is a COUNT, a RATIO, a BOOLEAN or a catalog SLUG — closed vocabularies and numbers.
    The name's content never appears.
    """

    #: Did the model produce a name at all? False means the evidence never existed.
    name_present: bool
    #: How many words it ran to, after normalisation.
    name_words: int
    #: The type it matched, if any.
    matched: str | None
    #: The type it came closest to, when nothing matched.
    near_miss: str | None
    #: What fraction of the name ``near_miss`` accounts for, rounded to two places.
    #:
    #: THE FIELD THAT MAKES ``coverage`` ACTIONABLE, and its absence made the first version
    #: misleading. ``rejected_by=coverage`` was documented as meaning "the model named a real type
    #: and the matcher turned it away, so loosen the matcher" — but it is equally what the guard
    #: produces when working correctly: "an email asking the borrower to send a bank statement" is
    #: the case the coverage rule was measured to reject, and it yielded a byte-identical
    #: explanation to LF-ZE9N's genuine Closing Disclosure. The ratio is what separates them, and
    #: `match_catalog_type` already documents the populations: true names 0.5-0.67, mentions
    #: 0.18-0.25. Without it, acting on the field as written would loosen the guard against exactly
    #: the names it exists to exclude.
    near_miss_coverage: float | None
    #: Which guard stopped the match. See the constants above; ``None`` only when something matched.
    rejected_by: str | None


def _longest_slug_where(
    tokens: list[str],
    predicate: Callable[[list[str], list[str]], bool],
    *,
    min_words: int,
    max_words: int,
) -> str | None:
    """The longest catalog slug within the word-count band that satisfies ``predicate``."""
    best: str | None = None
    best_words = 0
    for slug in CATALOG:
        words = slug.split("_")
        if not (min_words <= len(words) <= max_words) or len(words) <= best_words:
            continue
        if predicate(words, tokens):
            best, best_words = slug, len(words)
    return best


def explain_catalog_match(free_text: str | None) -> CatalogMatchExplanation:
    """Run the same match as :func:`match_catalog_type`, and report why it landed (LP-639).

    Deliberately a SECOND pass rather than a rewrite of the matcher to return both: the matcher is
    what decides whether a processor sees a flag, and threading a diagnostic through it would put
    observability on that path. The caller keeps calling `match_catalog_type` for the decision, and
    this for the log — a rationale that was stated once while the pipeline had quietly started
    taking its decision from here instead.

    The near miss is what makes it worth logging. "Nothing matched" cannot tell a name that named no
    type from a name that named one and failed a guard. This names the slug, the guard, and the
    coverage ratio — which is the number that says whether the guard was wrong or right.
    """
    if not free_text:
        return CatalogMatchExplanation(False, 0, None, None, None, None)
    haystack = _normalize_for_match(free_text)
    if not haystack:
        return CatalogMatchExplanation(True, 0, None, None, None, UNUSABLE_NAME)

    tokens = haystack.split()
    matched = match_catalog_type(free_text)
    if matched is not None:
        return CatalogMatchExplanation(True, len(tokens), matched, None, None, None)

    def _cover(slug: str) -> float:
        return round(len(slug.split("_")) / len(tokens), 2)

    # Ordered, long enough to be considered — so coverage is the only guard left that can have
    # stopped it. This is the case worth acting on, and `near_miss_coverage` says whether to.
    ordered = _longest_slug_where(
        tokens,
        _matches_in_order_with_small_gaps,
        min_words=_MIN_SLUG_WORDS_FOR_NAME_MATCH,
        max_words=_MAX_SLUG_WORDS,
    )
    if ordered is not None:
        return CatalogMatchExplanation(
            True, len(tokens), None, ordered, _cover(ordered), REJECTED_BY_COVERAGE
        )

    # Ordered but TOO SHORT to be considered at all — the third guard, which the first version of
    # this did not model. `explain_catalog_match("Appraisal")` reported "the model named nothing",
    # about a name that named a catalog type exactly.
    short = _longest_slug_where(
        tokens,
        _matches_in_order_with_small_gaps,
        min_words=1,
        max_words=_MIN_SLUG_WORDS_FOR_NAME_MATCH - 1,
    )
    if short is not None:
        return CatalogMatchExplanation(
            True, len(tokens), None, short, _cover(short), REJECTED_BY_MIN_WORDS
        )

    # Every word present, but not in that order — a genuine near miss on the ordering guard, which
    # was previously indistinguishable from a name containing no catalog words whatsoever.
    def _all_present(words: list[str], haystack_tokens: list[str]) -> bool:
        return all(word in haystack_tokens for word in words)

    unordered = _longest_slug_where(
        tokens, _all_present, min_words=_MIN_SLUG_WORDS_FOR_NAME_MATCH, max_words=_MAX_SLUG_WORDS
    )
    if unordered is not None:
        return CatalogMatchExplanation(
            True, len(tokens), None, unordered, _cover(unordered), REJECTED_BY_ORDER
        )

    return CatalogMatchExplanation(True, len(tokens), None, None, None, NO_CATALOG_WORDS)


def _matches_in_order_with_small_gaps(needle: list[str], haystack: list[str]) -> bool:
    """Every word of ``needle`` present in ``haystack``, in order, with at most
    :data:`_MAX_GAP_TOKENS` intervening tokens between consecutive matches.

    BOUNDED, not free. An unbounded ordered subsequence was the first attempt and it overfits: it
    was widened to catch "Earnest Money / EMD Receipt" (one token wedged mid-phrase) and in doing
    so it started matching names where the words are merely scattered — "a closing statement with a
    separate disclosure page", "a credit memo and a separate report on fees". Those have two to
    four intervening tokens; the case worth catching has one.

    So the bound is set from the case it exists for rather than loosened until an example passed.
    Order still has to hold, so "a receipt for the earnest money" does not match
    ``earnest_money_receipt`` — that is the line between "the name contains these words" and "the
    name says this thing".
    """
    position = -1
    for word in needle:
        try:
            found = haystack.index(word, position + 1)
        except ValueError:
            return False
        if position >= 0 and found - position - 1 > _MAX_GAP_TOKENS:
            return False
        position = found
    return True


def types_for_category(category: DocumentCategory) -> list[str]:
    """All cataloged type slugs in ``category``, in catalog (insertion) order.

    The classification prompt groups its type listing by category using this, so
    the prompt's structure is driven by the catalog — one source of truth.
    """
    return [slug for slug, (_, cat) in CATALOG.items() if cat is category]

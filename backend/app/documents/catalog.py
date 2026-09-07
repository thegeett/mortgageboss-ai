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

LP-800 adds a **third** axis on the same slugs: :data:`GUIDANCE` — who holds each
document type, and, for the types a borrower is actually asked for, what to say to
them. Phase 4 drafts the request, and neither the tier nor the category can tell it
whether the borrower can act on the ask at all. Same one-line-edit discipline, same
never-raise lookup, and a test keeps all three axes covering the same slug set.
"""

from collections.abc import Callable
from dataclasses import asdict, dataclass
from enum import StrEnum

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
    # TIER 1 AS OF LP-642 STEP 2. Step 1 catalogued these at Tier 2 — classified, categorised and
    # fileable, with no structured extraction — precisely because no extractor existed and Tier 1
    # would have claimed one that did not. `extract_comparable_rent_schedule` now reads both forms,
    # so the tier moves with the fact rather than ahead of it.
    "comparable_rent_schedule": (Tier.TIER_1, DocumentCategory.PROPERTY),  # Form 1007, one-unit
    "small_residential_income_appraisal": (Tier.TIER_1, DocumentCategory.PROPERTY),  # Form 1025
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


# --------------------------------------------------------------------------- #
# Borrower guidance — who a document comes FROM, and how to ask for it (LP-800)
# --------------------------------------------------------------------------- #
# Phase 4 sends the ask. Everything above answers "what IS this document"; nothing
# answered "whose document is it, and what do I say to the person who has it".
# Without that, a drafted request either names the document type at the borrower —
# "please provide a comparable_rent_schedule" — or asks them for something they
# cannot produce, because the appraiser, the title company or their own employer
# holds it.
#
# CODE, NOT A TABLE, for the same reason tier and category are (ADR-053/ADR-167):
# adding a type stays a one-line edit with no migration. `responsible_party` is a
# closed vocabulary and could be a DB enum; the instruction prose could not, and
# splitting one fact about a type across two stores is how the two drift.


class ResponsibleParty(StrEnum):
    """Who actually holds a document — the party a request has to reach.

    Not "who is accountable for the file". A processor chases every one of these; the
    distinction that matters to a draft is whether the BORROWER can act on the ask at
    all. ``PROCESSOR`` means the processor orders it themselves and no borrower-facing
    request should be generated (LP-801's `requestable` is about a finding; this is
    about a document type, and the two gates are independent).
    """

    BORROWER = "borrower"
    PROCESSOR = "processor"
    LENDER = "lender"
    TITLE = "title"
    EMPLOYER = "employer"
    CPA = "cpa"
    AGENT = "agent"
    INSURER = "insurer"


@dataclass(frozen=True)
class BorrowerGuidance:
    """What a request for one document type has to say, in the borrower's words.

    ``borrower_label`` is the ONLY string a borrower should ever see for a type — the
    catalog slug is an internal identifier and reads as a system leak in an email.

    ``common_rejects`` is the field that earns its keep and the one most easily skipped.
    Almost every re-request in a processing file is a document that arrived, was looked
    at, and was sent back: page 1 of 5, a screenshot of a balance, an expired licence.
    Naming the failure in the FIRST ask is cheaper than a second round trip, and it is
    knowledge the borrower has no way to have.
    """

    responsible_party: ResponsibleParty
    #: What to call the document when speaking to a borrower.
    borrower_label: str | None = None
    #: Where to get it, in the borrower's words — a portal, an office, a person.
    how_to_obtain: str | None = None
    #: What "all of it" means for THIS type. Generic completeness advice is useless:
    #: "all pages" means something different for a bank statement and a tax return.
    completeness_rule: str | None = None
    #: The ways this specific type usually arrives wrong.
    common_rejects: tuple[str, ...] = ()
    #: A blank form the borrower fills in, where one exists. None everywhere today —
    #: LP-817 owns the template library, and a link that resolves to nothing is worse
    #: in an email than no link, so these stay None until there is something to point at.
    template_url: str | None = None


#: Who holds each cataloged type. EVERY catalog slug appears here — a type with no party
#: is a type Phase 4 cannot address, and the sync test refuses one rather than letting it
#: fall to a default that would quietly address it to the borrower.
#:
#: SOURCED WHERE A SOURCE EXISTS. The assignments the Fannie Mae Selling Guide actually governs
#: carry their section inline, next to the claim, so a reviewer reads the rule and the assignment
#: together rather than taking the assignment on trust. Cited sections were read on 2026-09-07.
#:
#: The rest — the majority — remain an INDUSTRY-STANDARD FIRST PASS on the same footing as the
#: catalog itself: the party a US residential mortgage file normally draws each type from. The Guide
#: says who must OBTAIN a document for a loan to be saleable; it does not say who a processor emails,
#: and for most types nothing says. Those are still unvalidated against the resident domain expert's
#: real workflow, and a processing company's own habits move some of them — a shop that orders
#: payoffs through the borrower rather than the servicer, say. Expect this to refine with Priya.
#:
#: THE VOCABULARY CANNOT NAME A DEPOSITORY OR A SERVICER, and the sourcing pass is what surfaced it.
#: `verification_of_deposit`, `verification_of_assets`, `verification_of_mortgage` and
#: `verification_of_rent` are third-party forms sent OUT to a bank, a servicer or a landlord — the
#: same shape as `voe`, which CAN name its third party because `EMPLOYER` exists. They are recorded
#: as PROCESSOR, which is honest about "not a borrower ask" and wrong about "no outbound request at
#: all". LP-820 owns the non-borrower request paths and will need a party for each, or it will read
#: these four as having nowhere to go.
_RESPONSIBLE_PARTY: dict[str, ResponsibleParty] = {
    # ===================================================================== #
    # Income / Employment
    # ===================================================================== #
    # The borrower holds their own pay and tax records. The exceptions are the ones
    # ordered on the borrower's authorisation rather than fetched by them: transcripts
    # come back from the IRS to the processor, and a VOE is completed by the employer.
    "pay_stub": ResponsibleParty.BORROWER,
    "w2": ResponsibleParty.BORROWER,
    "1099": ResponsibleParty.BORROWER,
    "tax_return": ResponsibleParty.BORROWER,
    # B3-4.2-01: a verification form is "requested directly from" the third party and "sent
    # directly from" it. The borrower never handles it — that is the point of the form.
    "voe": ResponsibleParty.EMPLOYER,
    "profit_and_loss": ResponsibleParty.BORROWER,
    "tax_transcript": ResponsibleParty.PROCESSOR,
    # B3-3.1-02 (06/03/2026), which ABSORBED the old B3-3.1-06 — the b3-3.1-06 URL still resolves and
    # still carries this sentence, but the page now titles itself B3-3.1-02. Cite the heading, not the
    # URL that got you there.
    # B3-3.1-02: "The lender must have each borrower whose income is used in qualifying ... complete
    # and sign a separate IRS Form 4506-C at or before closing", and the LENDER enters its own name
    # as the recipient of the transcripts. So the ask goes to the borrower — a signature — even
    # though what comes back comes to us. That is why this is BORROWER and `tax_transcript` is not.
    "form_4506c": ResponsibleParty.BORROWER,
    "business_tax_return": ResponsibleParty.BORROWER,
    "k1_statement": ResponsibleParty.BORROWER,
    "social_security_award_letter": ResponsibleParty.BORROWER,
    "pension_statement": ResponsibleParty.BORROWER,
    "retirement_income_letter": ResponsibleParty.BORROWER,
    "unemployment_income_letter": ResponsibleParty.BORROWER,
    "disability_income_letter": ResponsibleParty.BORROWER,
    "child_support_income": ResponsibleParty.BORROWER,
    "alimony_income": ResponsibleParty.BORROWER,
    "rental_income_schedule": ResponsibleParty.BORROWER,
    "commission_income_statement": ResponsibleParty.BORROWER,
    "compensation_statement": ResponsibleParty.BORROWER,
    "employment_offer_letter": ResponsibleParty.BORROWER,
    "form_1040_personal_tax_transcripts": ResponsibleParty.PROCESSOR,
    "form_1065_partnership_tax_transcripts": ResponsibleParty.PROCESSOR,
    "form_1120_corporate_tax_transcripts": ResponsibleParty.PROCESSOR,
    "form_4506t_request_for_transcript": ResponsibleParty.BORROWER,  # signed, like the 4506-C
    "transcripts_of_1099": ResponsibleParty.PROCESSOR,
    "k_1_shareholder_profit_and_loss_transcripts": ResponsibleParty.PROCESSOR,
    "trust_federal_tax_returns": ResponsibleParty.BORROWER,
    "cpa_letter": ResponsibleParty.CPA,
    "business_existence_verification_cpa_ltr_bus_lic": ResponsibleParty.CPA,
    "business_license": ResponsibleParty.BORROWER,
    "disability_award_letter": ResponsibleParty.BORROWER,
    "retirement_pension_award_letter": ResponsibleParty.BORROWER,
    "retirement_check": ResponsibleParty.BORROWER,
    # B3-3.1-04: the lender obtains it, by telephoning the employer. The artefact is our own written
    # record of that call — nobody else holds it, so there is no request to send anywhere. This is
    # the one PROCESSOR in this file that genuinely means "nobody to ask", not "not the borrower".
    "verbal_voe": ResponsibleParty.PROCESSOR,
    "military_leave_and_earning_statement_les": ResponsibleParty.BORROWER,
    "foster_care_verification": ResponsibleParty.BORROWER,
    "boarder_rental_payments": ResponsibleParty.BORROWER,
    "boarder_proof_of_residency": ResponsibleParty.BORROWER,
    "cancelled_checks_evidencing_receipt_of_note_income": ResponsibleParty.BORROWER,
    # ===================================================================== #
    # Assets
    # ===================================================================== #
    # Statements are the borrower's. The verifications (VOD / VOA) are third-party forms
    # the processor sends to the depository, which is why they are not borrower asks even
    # though they describe the borrower's own accounts.
    "bank_statement": ResponsibleParty.BORROWER,
    "investment_account": ResponsibleParty.BORROWER,
    "retirement_account": ResponsibleParty.BORROWER,
    # B3-4.3-04: the gift "must be evidenced by a letter signed by the donor". BORROWER regardless —
    # the party is who we ASK, and we have no relationship with the donor. The borrower gets it.
    "gift_letter": ResponsibleParty.BORROWER,
    # B3-4.2-01: "requested directly from the depository institution", and returned directly by it.
    # See the vocabulary gap above: PROCESSOR here means "not a borrower ask", not "nobody to ask".
    "verification_of_deposit": ResponsibleParty.PROCESSOR,
    "brokerage_statement": ResponsibleParty.BORROWER,
    "money_market_statement": ResponsibleParty.BORROWER,
    "certificate_of_deposit": ResponsibleParty.BORROWER,
    # B3-4.3-09: receipt is verified by "a copy of the borrower's canceled check OR a written
    # statement from the holder of the deposit". Two documents, two parties, and the catalog has
    # both — the holder's statement is the agent's, `emd_withdrawal_proof` is the borrower's half.
    "earnest_money_receipt": ResponsibleParty.AGENT,
    "gift_donor_bank_statement": ResponsibleParty.BORROWER,
    "life_insurance_statement": ResponsibleParty.BORROWER,
    "sale_of_asset_proof": ResponsibleParty.BORROWER,
    "crypto_account_statement": ResponsibleParty.BORROWER,
    "ira_401k": ResponsibleParty.BORROWER,
    "bank_deposit_slip": ResponsibleParty.BORROWER,
    "emd_withdrawal_proof": ResponsibleParty.BORROWER,  # B3-4.3-09, the cancelled-check half
    "life_insurance_policy": ResponsibleParty.BORROWER,
    "verification_of_assets": ResponsibleParty.PROCESSOR,  # B3-4.2-01 shape; see the gap above
    "financial_statements": ResponsibleParty.BORROWER,
    "statement_of_account": ResponsibleParty.BORROWER,
    # ===================================================================== #
    # Property
    # ===================================================================== #
    # The split that matters here: what the borrower OWNS the paperwork for (their
    # mortgage, tax bill, HOA dues, leases, inspections they commissioned) versus what
    # the transaction produces around them (appraisal, title, flood determination), which
    # the borrower cannot obtain and should never be asked for.
    # LP-800 review — LENDER, matching `appraisal` below. All three are the same appraiser's work
    # product arriving through the same AMC order, and this file already quotes the guide language
    # for these two: `ai/extraction/comparable_rent_schedule.py` opens with "The LENDER must obtain
    # the following: a Single-Family Comparable Rent Schedule (Form 1007) or Small Residential Income
    # Property Appraisal Report (Form 1025)". Splitting one order across two parties would give
    # LP-820 two request paths and two clocks for documents that arrive together.
    # B4-1.1-03 covers these two exactly as it covers `appraisal` below: same appraiser, same order.
    "comparable_rent_schedule": ResponsibleParty.LENDER,  # Form 1007, appraiser-prepared
    "small_residential_income_appraisal": ResponsibleParty.LENDER,  # Form 1025 / Freddie 72
    "purchase_agreement": ResponsibleParty.AGENT,
    "homeowners_insurance": ResponsibleParty.BORROWER,
    "mortgage_statement": ResponsibleParty.BORROWER,
    "form_1098": ResponsibleParty.BORROWER,
    "property_tax_bill": ResponsibleParty.BORROWER,
    "hoa_statement": ResponsibleParty.BORROWER,
    # B4-1.1-03 IS A PROHIBITION, NOT A CONVENTION: lenders "may not use appraisals ordered or
    # received by borrowers or other parties with an interest in the transaction, such as the
    # property seller or real estate agent". An appraisal a borrower sent us is not merely awkward
    # to have asked for — it is UNUSABLE, and the asking is what invites them to produce one.
    # `render_document_block` refuses every non-BORROWER type, so this is enforced, not advisory.
    "appraisal": ResponsibleParty.LENDER,
    "title_commitment": ResponsibleParty.TITLE,
    "preliminary_title_report": ResponsibleParty.TITLE,
    "flood_certification": ResponsibleParty.LENDER,
    "flood_insurance_policy": ResponsibleParty.BORROWER,
    "survey": ResponsibleParty.TITLE,
    "warranty_deed": ResponsibleParty.TITLE,
    "home_inspection_report": ResponsibleParty.BORROWER,
    "pest_inspection_report": ResponsibleParty.BORROWER,
    "well_septic_certification": ResponsibleParty.BORROWER,
    "condo_questionnaire": ResponsibleParty.PROCESSOR,  # sent to the HOA / management co.
    "payoff_statement": ResponsibleParty.PROCESSOR,  # ordered from the servicer
    "lease_agreement": ResponsibleParty.BORROWER,
    "master_insurance_policy_for_condominium": ResponsibleParty.INSURER,
    "building_permits": ResponsibleParty.BORROWER,
    "hoa_certification": ResponsibleParty.PROCESSOR,
    "homeowner_s_insurance_quote": ResponsibleParty.BORROWER,
    "termite_report": ResponsibleParty.BORROWER,
    "termite_completion": ResponsibleParty.BORROWER,
    "property_profile_subject": ResponsibleParty.PROCESSOR,
    "property_profile_non_subject": ResponsibleParty.PROCESSOR,
    "property_tax_bill_non_subject": ResponsibleParty.BORROWER,
    "proof_of_occupancy": ResponsibleParty.BORROWER,
    "subject_property_note": ResponsibleParty.BORROWER,
    "other_property_note": ResponsibleParty.BORROWER,
    "seller_signature_authority": ResponsibleParty.AGENT,
    "home_value_estimate": ResponsibleParty.PROCESSOR,
    "certificate_of_liability_insurance": ResponsibleParty.INSURER,
    # ===================================================================== #
    # Credit
    # ===================================================================== #
    # The report and its supplements are pulled by the lender; everything the report
    # RAISES — a discharge, a judgment, a payoff, an explanation — is the borrower's to
    # produce. VOM and VOR are third-party forms sent to a servicer or landlord.
    "credit_report": ResponsibleParty.LENDER,
    "credit_explanation_letter": ResponsibleParty.BORROWER,
    "credit_supplement": ResponsibleParty.PROCESSOR,
    "bankruptcy_discharge": ResponsibleParty.BORROWER,
    "foreclosure_documentation": ResponsibleParty.BORROWER,
    "judgment_documentation": ResponsibleParty.BORROWER,
    "collection_account_letter": ResponsibleParty.BORROWER,
    "debt_payoff_statement": ResponsibleParty.BORROWER,
    "student_loan_statement": ResponsibleParty.BORROWER,
    "installment_loan_statement": ResponsibleParty.BORROWER,
    "credit_card_statement": ResponsibleParty.BORROWER,
    "bankruptcy_filing": ResponsibleParty.BORROWER,
    "unsecured_note": ResponsibleParty.BORROWER,
    "verification_of_mortgage": ResponsibleParty.PROCESSOR,  # B3-4.2-01 shape; see the gap above
    "verification_of_rent": ResponsibleParty.PROCESSOR,  # B3-4.2-01 shape; see the gap above
    # ===================================================================== #
    # Disclosures
    # ===================================================================== #
    # The lender ISSUES these; the borrower signs and returns some of them. The party
    # recorded is whoever a missing copy has to be chased from, which for a signed
    # authorisation or consent is the borrower and for a CD or LE is the lender.
    "closing_disclosure": ResponsibleParty.LENDER,
    "loan_estimate": ResponsibleParty.LENDER,
    "intent_to_proceed": ResponsibleParty.BORROWER,
    "notice_of_right_to_cancel": ResponsibleParty.LENDER,
    "truth_in_lending": ResponsibleParty.LENDER,
    "servicing_disclosure": ResponsibleParty.LENDER,
    "affiliated_business_disclosure": ResponsibleParty.LENDER,
    "privacy_notice": ResponsibleParty.LENDER,
    "e_consent_disclosure": ResponsibleParty.BORROWER,
    "authorization_to_run_credit": ResponsibleParty.BORROWER,
    "borrower_authorization_and_certification": ResponsibleParty.BORROWER,
    "borrower_s_authorization_for_counseling": ResponsibleParty.BORROWER,
    "credit_card_authorization": ResponsibleParty.BORROWER,
    "social_security_administration_ssa_89": ResponsibleParty.BORROWER,
    "mortgage_loan_origination_agreement": ResponsibleParty.BORROWER,
    "prior_closing_disclosure_final_cd_from_purchase": ResponsibleParty.BORROWER,
    "temporary_buydown_agreement": ResponsibleParty.LENDER,
    # ===================================================================== #
    # Borrower information
    # ===================================================================== #
    # Identity, life events, and the letters only the borrower can write. Every one of
    # these is a borrower ask by definition — the category IS the party.
    "drivers_license": ResponsibleParty.BORROWER,
    "divorce_decree": ResponsibleParty.BORROWER,
    "letter_of_explanation": ResponsibleParty.BORROWER,
    "passport": ResponsibleParty.BORROWER,
    "social_security_card": ResponsibleParty.BORROWER,
    "permanent_resident_card": ResponsibleParty.BORROWER,
    "visa_documentation": ResponsibleParty.BORROWER,
    "birth_certificate": ResponsibleParty.BORROWER,
    "marriage_certificate": ResponsibleParty.BORROWER,
    "military_id": ResponsibleParty.BORROWER,
    "power_of_attorney": ResponsibleParty.BORROWER,
    "trust_documentation": ResponsibleParty.BORROWER,
    "name_affidavit": ResponsibleParty.BORROWER,
    "government_issued_id": ResponsibleParty.BORROWER,
    "work_visa_ead_card": ResponsibleParty.BORROWER,
    "court_order_documents": ResponsibleParty.BORROWER,
    "trust_agreement": ResponsibleParty.BORROWER,
    "trust_documents": ResponsibleParty.BORROWER,
    "application_loe": ResponsibleParty.BORROWER,
    "letter_of_explanation_asset": ResponsibleParty.BORROWER,
    "letter_of_explanation_child_care": ResponsibleParty.BORROWER,
    "letter_of_explanation_income": ResponsibleParty.BORROWER,
    "letter_of_explanation_misc": ResponsibleParty.BORROWER,
    "letter_of_explanation_property": ResponsibleParty.BORROWER,
    "uscis_notice_of_action": ResponsibleParty.BORROWER,
    # ===================================================================== #
    # Misc
    # ===================================================================== #
    # System artefacts and lender output. `custom` and `miscellaneous_document` are
    # PROCESSOR deliberately: they are "we do not know what this is", and the safe
    # reading of an unknown type is that nobody has been told to send it.
    "uniform_residential_loan_application": ResponsibleParty.PROCESSOR,
    "underwriting_approval": ResponsibleParty.LENDER,
    "rate_lock_agreement": ResponsibleParty.LENDER,
    "general_correspondence": ResponsibleParty.PROCESSOR,
    "aus_findings": ResponsibleParty.LENDER,
    "certificate_of_eligibility": ResponsibleParty.BORROWER,
    "appraisal_payment": ResponsibleParty.BORROWER,
    "evidence_of_payment": ResponsibleParty.BORROWER,
    "custom": ResponsibleParty.PROCESSOR,
    "miscellaneous_document": ResponsibleParty.PROCESSOR,
    "wire_instructions": ResponsibleParty.TITLE,
    "lender_dashboard_screenshot": ResponsibleParty.PROCESSOR,
    "service_invoice": ResponsibleParty.PROCESSOR,
}


@dataclass(frozen=True)
class _Instructions:
    """The prose half of a guidance entry — everything EXCEPT the responsible party.

    Party lives only in `_RESPONSIBLE_PARTY`. It used to be repeated here as the first argument of
    each `BorrowerGuidance(...)` literal, and the literal won: `GUIDANCE` preferred the instruction
    entry wholesale, so for the 28 types that have one, editing `_RESPONSIBLE_PARTY` did NOTHING.
    A reviewer correcting a party there would have seen no effect and no error.

    Found by mutation during the 2026-09-07 sourcing pass: flipping `form_4506c` to PROCESSOR left
    the whole suite green. It is the same "two spellings of one fact" ADR-399 refused, in the file
    that argued for it — and it could only ever disagree in the direction no test looks at, because
    `test_instructions_exist_only_where_the_borrower_can_act` pins the literals to BORROWER.
    """

    borrower_label: str
    how_to_obtain: str
    completeness_rule: str
    common_rejects: tuple[str, ...]
    template_url: str | None = None


#: Full instructions for the types a borrower is actually asked for. Everything else gets
#: its party and no prose — writing thin instructions for all 166 would take longer and
#: read worse than writing real ones for the types that carry the traffic.
#:
#: Every entry here has ``responsible_party = BORROWER`` (asserted by the sync test): a
#: paragraph telling a borrower how to obtain their own appraisal would be instructions
#: for something they cannot do.
_BORROWER_INSTRUCTIONS: dict[str, _Instructions] = {
    # ---------------------------------------------------------------- income
    "pay_stub": _Instructions(
        borrower_label="Pay stubs — your most recent 30 days",
        how_to_obtain=(
            "From your employer's payroll portal — ADP, Workday, Paychex and similar all "
            "have a 'pay statements' section — or ask your HR or payroll contact."
        ),
        completeness_rule=(
            "Every stub covering the last 30 days, each showing your name, your employer's "
            "name, the pay period dates, and the year-to-date totals."
        ),
        common_rejects=(
            "a screenshot of the payroll portal instead of the stub itself",
            "a stub with the year-to-date totals cut off",
            "the summary page rather than the full stub",
            "stubs older than 30 days",
        ),
    ),
    "w2": _Instructions(
        borrower_label="W-2s — the last two years",
        how_to_obtain=(
            "From your employer, or downloaded from the same payroll portal as your pay "
            "stubs. If you changed jobs, you need one from each employer."
        ),
        completeness_rule=(
            "All pages of the W-2 for each of the last two tax years, from every employer, "
            "with the boxes legible."
        ),
        common_rejects=(
            "one year when two were asked for",
            "one employer's W-2 when you worked for two",
            "the state copy with the federal wage boxes cut off",
        ),
    ),
    "1099": _Instructions(
        borrower_label="1099s — the last two years",
        how_to_obtain=(
            "From whoever paid you — a client, a platform, a broker, or the Social Security "
            "Administration. Most send them by the end of January."
        ),
        completeness_rule=(
            "Every 1099 you received for each of the last two tax years, all pages."
        ),
        common_rejects=(
            "a summary of earnings instead of the 1099 form",
            "one 1099 when you had several payers",
        ),
    ),
    "tax_return": _Instructions(
        borrower_label="Personal tax returns — the last two years",
        how_to_obtain=(
            "From your tax preparer, or from the software you filed with — TurboTax, H&R "
            "Block and similar keep a PDF of the filed return. The IRS also provides copies "
            "at irs.gov."
        ),
        completeness_rule=(
            "The complete federal return for each year: every page, every schedule, and the "
            "W-2s and 1099s attached to it. State returns are not needed."
        ),
        common_rejects=(
            "the first two pages only",
            "a return with schedules missing",
            "an unsigned return where a signed copy was asked for",
            "a state return instead of the federal one",
        ),
    ),
    "business_tax_return": _Instructions(
        borrower_label="Business tax returns — the last two years",
        how_to_obtain=(
            "From your CPA or tax preparer. This is the return filed for the business — a "
            "1065, 1120 or 1120-S — not your personal return."
        ),
        completeness_rule=(
            "The complete federal business return for each year, including every schedule "
            "and every K-1 the business issued."
        ),
        common_rejects=(
            "the personal return instead of the business one",
            "a return without the K-1s",
        ),
    ),
    "profit_and_loss": _Instructions(
        borrower_label="Profit and loss statement — year to date",
        how_to_obtain=(
            "From your accountant, or exported from your bookkeeping software — QuickBooks, "
            "Xero and similar all produce one."
        ),
        completeness_rule=(
            "Covering 1 January of this year through the most recent complete month, showing "
            "gross income, expenses and net profit, with the business name and the period on it."
        ),
        common_rejects=(
            "a bank statement in place of a profit and loss statement",
            "a statement that stops several months short of the current month",
            "a statement with no period stated on it",
        ),
    ),
    "k1_statement": _Instructions(
        borrower_label="Schedule K-1 — the last two years",
        how_to_obtain="From the accountant who prepared the partnership or S-corporation return.",
        completeness_rule=("The K-1 issued to you for each of the last two tax years, all pages."),
        common_rejects=(
            "the business return without the K-1 attached",
            "one year when two were asked for",
        ),
    ),
    "social_security_award_letter": _Instructions(
        borrower_label="Social Security award letter — the current year",
        how_to_obtain=(
            "From ssa.gov: sign in and choose 'get a benefit verification letter'. It can "
            "also be requested by telephone."
        ),
        completeness_rule=(
            "The letter for the current year, showing your name, the monthly amount, and the "
            "date the benefit started or was renewed."
        ),
        common_rejects=(
            "a bank statement showing the deposit instead of the letter",
            "an award letter from an earlier year",
            "a 1099-SSA instead of the award letter",
        ),
    ),
    "form_4506c": _Instructions(
        borrower_label="IRS Form 4506-C — signed",
        how_to_obtain=(
            "We send you the form already filled in. Sign and date it; do not change the "
            "years or any of the boxes."
        ),
        completeness_rule=(
            "Signed and dated, with your name and Social Security number exactly as they "
            "appear on the tax return the form covers."
        ),
        common_rejects=(
            "a name spelled differently from the tax return",
            "a signature with no date beside it",
            "a form where the requested years were altered",
        ),
    ),
    # ---------------------------------------------------------------- assets
    "bank_statement": _Instructions(
        borrower_label="Bank statements — the two most recent months",
        how_to_obtain=(
            "Download them from your bank's website or app. Look for 'statements' or "
            "'documents' — not the transaction list on the account screen."
        ),
        completeness_rule=(
            "Every page of each statement, including pages that are blank or say 'this page "
            "intentionally left blank'. Each must show your name, the bank's name, the "
            "account number and the statement period."
        ),
        common_rejects=(
            "a screenshot of the account balance",
            "the transaction history exported to a spreadsheet",
            "page 1 of 5",
            "a statement with your name or the bank's name cropped out",
        ),
    ),
    "investment_account": _Instructions(
        borrower_label="Investment account statements — the two most recent months",
        how_to_obtain=(
            "From your brokerage's website — the monthly or quarterly statement, not the "
            "holdings screen."
        ),
        completeness_rule=(
            "All pages of each statement, showing your name, the institution, the account "
            "number and the period."
        ),
        common_rejects=(
            "a screenshot of the portfolio value",
            "a trade confirmation instead of a statement",
        ),
    ),
    "retirement_account": _Instructions(
        borrower_label="Retirement account statement — the most recent quarter",
        how_to_obtain=(
            "From your 401(k), IRA or pension provider's website, under 'statements' or "
            "'documents'."
        ),
        completeness_rule=(
            "All pages of the most recent statement, showing your name, the institution, the "
            "account number and the vested balance."
        ),
        common_rejects=(
            "a screenshot of the balance",
            "the annual summary instead of the statement",
        ),
    ),
    "gift_letter": _Instructions(
        borrower_label="Gift letter — signed by the person giving the gift",
        how_to_obtain=(
            "We will send you the form. The person giving the gift fills it in and signs it; "
            "you cannot sign it on their behalf."
        ),
        completeness_rule=(
            "Signed and dated by the donor, stating the amount, their relationship to you, "
            "and that the money is a gift with no expectation of repayment."
        ),
        common_rejects=(
            "a letter saying the money is a loan or will be paid back",
            "an unsigned or undated letter",
            "a text message or email in place of the signed letter",
        ),
    ),
    "gift_donor_bank_statement": _Instructions(
        borrower_label="The gift donor's bank statement — showing the money leaving",
        how_to_obtain=(
            "Ask the person giving the gift for the statement from the account the money "
            "came out of."
        ),
        completeness_rule=(
            "All pages of the statement covering the withdrawal, with the donor's name and "
            "the account visible and the withdrawal itself shown."
        ),
        common_rejects=(
            "a screenshot of the transfer",
            "a statement where the withdrawal does not appear",
            "your own statement instead of the donor's",
        ),
    ),
    "emd_withdrawal_proof": _Instructions(
        borrower_label="Proof the earnest money left your account",
        how_to_obtain=(
            "Your bank statement or online banking record showing the payment clearing, plus "
            "the cancelled cheque or wire confirmation if you have one."
        ),
        completeness_rule=(
            "A record showing the amount, the date, and that the money came from an account "
            "in your name — matching the amount on the purchase agreement."
        ),
        common_rejects=(
            "a screenshot of a pending transaction",
            "the agent's receipt without the matching bank record",
        ),
    ),
    # -------------------------------------------------------------- property
    "homeowners_insurance": _Instructions(
        borrower_label="Homeowner's insurance — the declarations page",
        how_to_obtain=(
            "From your insurance agent or the insurer's website. Ask for the 'declarations "
            "page' or 'dec page' — not the full policy booklet."
        ),
        completeness_rule=(
            "The declarations page showing the property address, the coverage amount, the "
            "annual premium, the policy period and the named insured."
        ),
        common_rejects=(
            "the policy booklet without the declarations page",
            "a quote instead of a bound policy",
            "a policy whose period begins after the closing date",
        ),
    ),
    "mortgage_statement": _Instructions(
        borrower_label="Mortgage statement — the most recent",
        how_to_obtain="From your servicer's website, or the statement they post to you monthly.",
        completeness_rule=(
            "All pages of the most recent statement, showing the loan number, the balance and "
            "the monthly payment including escrow."
        ),
        common_rejects=(
            "a payment confirmation instead of the statement",
            "a statement more than 60 days old",
        ),
    ),
    "property_tax_bill": _Instructions(
        borrower_label="Property tax bill — the most recent",
        how_to_obtain=(
            "From your county or city tax collector's website — most let you search by "
            "address or parcel number."
        ),
        completeness_rule=(
            "The full bill showing the property address, the parcel number, the annual amount "
            "and the tax year."
        ),
        common_rejects=(
            "a payment receipt that does not show the amounts",
            "an assessment notice instead of the bill",
        ),
    ),
    "hoa_statement": _Instructions(
        borrower_label="HOA statement or dues notice",
        how_to_obtain="From your homeowners association or its management company.",
        completeness_rule=(
            "A statement showing the association's name, the property, the dues amount and "
            "how often they are charged."
        ),
        common_rejects=(
            "a screenshot of a payment",
            "the association's rules instead of the dues statement",
        ),
    ),
    "lease_agreement": _Instructions(
        borrower_label="Lease agreement — the signed lease",
        how_to_obtain="Your own copy of the signed lease for the rental property.",
        completeness_rule=(
            "Every page of the executed lease, signed by you and the tenant, showing the "
            "rent, the term and the property address."
        ),
        common_rejects=(
            "an unsigned draft",
            "the first page only",
            "a rental listing instead of the lease",
        ),
    ),
    # -------------------------------------------------------- credit + identity
    "student_loan_statement": _Instructions(
        borrower_label="Student loan statement — the most recent",
        how_to_obtain=(
            "From your loan servicer's website. If your loans sit with more than one "
            "servicer, you need a statement from each."
        ),
        completeness_rule=(
            "A statement showing the balance and the monthly payment. If you are on an "
            "income-driven plan, in deferment or in forbearance, it must say so and give the "
            "payment amount."
        ),
        common_rejects=(
            "a screenshot of the balance with no payment shown",
            "one servicer's statement when the loans sit with several",
            "a payoff quote instead of a statement",
        ),
    ),
    "credit_explanation_letter": _Instructions(
        borrower_label="Letter of explanation — credit history",
        how_to_obtain=(
            "You write this one. We will tell you which accounts or inquiries it needs to cover."
        ),
        completeness_rule=(
            "Dated and signed by you, naming each account or inquiry asked about and explaining it."
        ),
        common_rejects=(
            "a letter covering some but not all of the items asked about",
            "an unsigned letter",
        ),
    ),
    "letter_of_explanation": _Instructions(
        borrower_label="Letter of explanation — in your own words",
        how_to_obtain=(
            "You write this one. We will tell you what it needs to cover; a short paragraph "
            "in plain language is enough."
        ),
        completeness_rule=(
            "Dated and signed by you, answering the specific question asked — what happened, "
            "when, and why."
        ),
        common_rejects=(
            "a letter that does not answer the question that was asked",
            "an unsigned or undated letter",
            "an explanation sent as a text or email instead of a signed letter",
        ),
    ),
    "divorce_decree": _Instructions(
        borrower_label="Divorce decree — the complete filed copy",
        how_to_obtain=(
            "From the court that issued it, usually through the clerk's office, or from your "
            "attorney."
        ),
        completeness_rule=(
            "Every page of the filed decree, including any settlement agreement or support "
            "order attached to it, carrying the court's stamp or the judge's signature."
        ),
        common_rejects=(
            "the first pages without the support terms",
            "a separation agreement that was never filed with the court",
            "a summary or cover letter from an attorney",
        ),
    ),
    "drivers_license": _Instructions(
        borrower_label="Driver's licence — front and back",
        how_to_obtain="A photograph or scan of your current licence.",
        completeness_rule=(
            "Both sides, unexpired, with all four corners in frame and every line of text readable."
        ),
        common_rejects=(
            "an expired licence",
            "the front only",
            "a photograph taken at an angle where the text blurs",
            "a licence on a dark background where the edges are lost",
        ),
    ),
    "passport": _Instructions(
        borrower_label="Passport — the photo page",
        how_to_obtain="A photograph or scan of the page carrying your photograph and details.",
        completeness_rule=(
            "The whole photo page, unexpired, with the two machine-readable lines at the "
            "bottom in frame."
        ),
        common_rejects=(
            "an expired passport",
            "a photo page with the edges cropped",
            "the cover instead of the photo page",
        ),
    ),
    "permanent_resident_card": _Instructions(
        borrower_label="Permanent resident card — front and back",
        how_to_obtain="A photograph or scan of your current card.",
        completeness_rule=(
            "Both sides, unexpired, with all four corners in frame and the card number readable."
        ),
        common_rejects=(
            "the front only",
            "an expired card without the extension notice",
            "a photograph where glare covers the card number",
        ),
    ),
    "social_security_card": _Instructions(
        borrower_label="Social Security card",
        how_to_obtain=(
            "A photograph or scan of the card itself. If it is lost, ssa.gov can issue a "
            "replacement."
        ),
        completeness_rule=(
            "The whole card, with your name and number readable and nothing written over them."
        ),
        common_rejects=(
            "the number written on a piece of paper",
            "a laminated card where glare covers the number",
            "a photograph with a corner out of frame",
        ),
    ),
}


#: The public mapping: one entry per catalog type, party always, prose where it exists.
#:
#: DERIVED rather than written out 166 times, so each fact has one home. A slug's party lives in
#: `_RESPONSIBLE_PARTY` and ONLY there; its prose lives in `_BORROWER_INSTRUCTIONS` and only there;
#: this composes them. A type added to the catalog without a party is missing from GUIDANCE
#: entirely — which is what the sync test reports, instead of a silent default.
GUIDANCE: dict[str, BorrowerGuidance] = {
    slug: (
        BorrowerGuidance(party, **asdict(prose))
        if (prose := _BORROWER_INSTRUCTIONS.get(slug)) is not None
        else BorrowerGuidance(party)
    )
    for slug, party in _RESPONSIBLE_PARTY.items()
}


#: An uncataloged type is addressed to the PROCESSOR with no instructions. Failing towards
#: "a person on our side deals with this" is the safe direction: the other default would
#: generate a borrower-facing ask for a document nobody has classified.
_DEFAULT_GUIDANCE = BorrowerGuidance(ResponsibleParty.PROCESSOR)


def get_guidance(document_type: str | None) -> BorrowerGuidance:
    """Borrower guidance for ``document_type`` — never raises, like the rest of the catalog.

    Unknown or absent types fall back to processor-owned with no instructions.
    """
    if not document_type:
        return _DEFAULT_GUIDANCE
    return GUIDANCE.get(document_type, _DEFAULT_GUIDANCE)

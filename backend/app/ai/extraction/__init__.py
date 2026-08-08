"""Extraction package — the per-type extractors + the dispatch registry (LP-39c).

Each document type has its own extractor (``extract_pay_stub`` / ``extract_w2`` /
``extract_bank_statement``) producing the LP-39a shape (typed core + grouped
catch-all, plus a transactions list for bank statements). The pipeline (LP-42
``process_document`` and the reprocess path) routes extraction through
:data:`EXTRACTORS` — adding a type later is "write an extractor + register it",
the clean form for Phase 2's ~100 types. An unregistered type is classified-only.

The result types share a structural :class:`ExtractionResult` interface (``data``
with ``model_dump``, ``status``, ``confidence``, ``reasoning``, token usage), so
the pipeline stores any of them uniformly via ``create_extraction_version``.
"""

from collections.abc import Awaitable, Callable
from typing import Protocol

from pydantic import BaseModel

# LP-443 step 7 (Phase C) — the remaining generated extractors.
from app.ai.extraction.affiliated_business_disclosure import extract_affiliated_business_disclosure
from app.ai.extraction.alimony_income import extract_alimony_income
from app.ai.extraction.application_loe import extract_application_loe
from app.ai.extraction.appraisal import extract_appraisal
from app.ai.extraction.appraisal_payment import extract_appraisal_payment
from app.ai.extraction.aus_findings import extract_aus_findings
from app.ai.extraction.authorization_to_run_credit import extract_authorization_to_run_credit
from app.ai.extraction.bank_deposit_slip import extract_bank_deposit_slip
from app.ai.extraction.bank_statement import extract_bank_statement
from app.ai.extraction.bankruptcy_discharge import extract_bankruptcy_discharge
from app.ai.extraction.bankruptcy_filing import extract_bankruptcy_filing
from app.ai.extraction.birth_certificate import extract_birth_certificate
from app.ai.extraction.boarder_proof_of_residency import extract_boarder_proof_of_residency
from app.ai.extraction.boarder_rental_payments import extract_boarder_rental_payments
from app.ai.extraction.borrower_authorization_and_certification import (
    extract_borrower_authorization_and_certification,
)
from app.ai.extraction.borrower_s_authorization_for_counseling import (
    extract_borrower_s_authorization_for_counseling,
)
from app.ai.extraction.building_permits import extract_building_permits
from app.ai.extraction.business_existence_verification_cpa_ltr_bus_lic import (
    extract_business_existence_verification_cpa_ltr_bus_lic,
)
from app.ai.extraction.business_license import extract_business_license
from app.ai.extraction.business_tax_return import extract_business_tax_return
from app.ai.extraction.cancelled_checks_evidencing_receipt_of_note_income import (
    extract_cancelled_checks_evidencing_receipt_of_note_income,
)
from app.ai.extraction.certificate_of_eligibility import extract_certificate_of_eligibility
from app.ai.extraction.child_support_income import extract_child_support_income
from app.ai.extraction.condo_questionnaire import extract_condo_questionnaire
from app.ai.extraction.court_order_documents import extract_court_order_documents
from app.ai.extraction.cpa_letter import extract_cpa_letter
from app.ai.extraction.credit_card_authorization import extract_credit_card_authorization
from app.ai.extraction.credit_report import extract_credit_report
from app.ai.extraction.custom import extract_custom
from app.ai.extraction.disability_award_letter import extract_disability_award_letter
from app.ai.extraction.divorce_decree import extract_divorce_decree
from app.ai.extraction.drivers_license import extract_drivers_license
from app.ai.extraction.e_consent_disclosure import extract_e_consent_disclosure
from app.ai.extraction.earnest_money_receipt import extract_earnest_money_receipt
from app.ai.extraction.emd_withdrawal_proof import extract_emd_withdrawal_proof
from app.ai.extraction.employment_offer_letter import extract_employment_offer_letter
from app.ai.extraction.evidence_of_payment import extract_evidence_of_payment
from app.ai.extraction.financial_statements import extract_financial_statements
from app.ai.extraction.flood_certification import extract_flood_certification
from app.ai.extraction.flood_insurance_policy import extract_flood_insurance_policy
from app.ai.extraction.form_1040_personal_tax_transcripts import (
    extract_form_1040_personal_tax_transcripts,
)
from app.ai.extraction.form_1065_partnership_tax_transcripts import (
    extract_form_1065_partnership_tax_transcripts,
)
from app.ai.extraction.form_1099 import extract_1099
from app.ai.extraction.form_1120_corporate_tax_transcripts import (
    extract_form_1120_corporate_tax_transcripts,
)
from app.ai.extraction.form_4506t_request_for_transcript import (
    extract_form_4506t_request_for_transcript,
)
from app.ai.extraction.foster_care_verification import extract_foster_care_verification
from app.ai.extraction.gift_letter import extract_gift_letter
from app.ai.extraction.government_issued_id import extract_government_issued_id
from app.ai.extraction.hoa_certification import extract_hoa_certification
from app.ai.extraction.hoa_statement import extract_hoa_statement
from app.ai.extraction.home_value_estimate import extract_home_value_estimate
from app.ai.extraction.homeowner_s_insurance_quote import extract_homeowner_s_insurance_quote
from app.ai.extraction.homeowners_insurance import extract_homeowners_insurance
from app.ai.extraction.investment_account import extract_investment_account
from app.ai.extraction.ira_401k import extract_ira_401k
from app.ai.extraction.k1_statement import extract_k1_statement
from app.ai.extraction.k_1_shareholder_profit_and_loss_transcripts import (
    extract_k_1_shareholder_profit_and_loss_transcripts,
)
from app.ai.extraction.lease_agreement import extract_lease_agreement
from app.ai.extraction.lender_dashboard_screenshot import extract_lender_dashboard_screenshot
from app.ai.extraction.letter_of_explanation import extract_letter_of_explanation
from app.ai.extraction.letter_of_explanation_asset import extract_letter_of_explanation_asset
from app.ai.extraction.letter_of_explanation_child_care import (
    extract_letter_of_explanation_child_care,
)
from app.ai.extraction.letter_of_explanation_income import extract_letter_of_explanation_income
from app.ai.extraction.letter_of_explanation_misc import extract_letter_of_explanation_misc
from app.ai.extraction.letter_of_explanation_property import extract_letter_of_explanation_property
from app.ai.extraction.life_insurance_policy import extract_life_insurance_policy
from app.ai.extraction.master_insurance_policy_for_condominium import (
    extract_master_insurance_policy_for_condominium,
)
from app.ai.extraction.military_leave_and_earning_statement_les import (
    extract_military_leave_and_earning_statement_les,
)
from app.ai.extraction.miscellaneous_document import extract_miscellaneous_document
from app.ai.extraction.mortgage_loan_origination_agreement import (
    extract_mortgage_loan_origination_agreement,
)
from app.ai.extraction.mortgage_statement import extract_mortgage_statement
from app.ai.extraction.other_property_note import extract_other_property_note
from app.ai.extraction.pay_stub import extract_pay_stub
from app.ai.extraction.payoff_statement import extract_payoff_statement
from app.ai.extraction.permanent_resident_card import extract_permanent_resident_card
from app.ai.extraction.prior_closing_disclosure_final_cd_from_purchase import (
    extract_prior_closing_disclosure_final_cd_from_purchase,
)
from app.ai.extraction.profit_and_loss import extract_profit_and_loss
from app.ai.extraction.proof_of_occupancy import extract_proof_of_occupancy
from app.ai.extraction.property_profile_non_subject import extract_property_profile_non_subject
from app.ai.extraction.property_profile_subject import extract_property_profile_subject
from app.ai.extraction.property_tax_bill import extract_property_tax_bill
from app.ai.extraction.property_tax_bill_non_subject import extract_property_tax_bill_non_subject
from app.ai.extraction.purchase_agreement import extract_purchase_agreement
from app.ai.extraction.retirement_account import extract_retirement_account
from app.ai.extraction.retirement_check import extract_retirement_check
from app.ai.extraction.retirement_pension_award_letter import (
    extract_retirement_pension_award_letter,
)
from app.ai.extraction.seller_signature_authority import extract_seller_signature_authority
from app.ai.extraction.social_security_administration_ssa_89 import (
    extract_social_security_administration_ssa_89,
)
from app.ai.extraction.social_security_award_letter import extract_social_security_award_letter
from app.ai.extraction.social_security_card import extract_social_security_card
from app.ai.extraction.statement_of_account import extract_statement_of_account
from app.ai.extraction.subject_property_note import extract_subject_property_note
from app.ai.extraction.survey import extract_survey
from app.ai.extraction.tax_return import extract_tax_return
from app.ai.extraction.temporary_buydown_agreement import extract_temporary_buydown_agreement
from app.ai.extraction.termite_completion import extract_termite_completion
from app.ai.extraction.termite_report import extract_termite_report
from app.ai.extraction.title_commitment import extract_title_commitment
from app.ai.extraction.transcripts_of_1099 import extract_transcripts_of_1099
from app.ai.extraction.trust_agreement import extract_trust_agreement
from app.ai.extraction.trust_documents import extract_trust_documents
from app.ai.extraction.trust_federal_tax_returns import extract_trust_federal_tax_returns
from app.ai.extraction.uniform_residential_loan_application import (
    extract_uniform_residential_loan_application,
)
from app.ai.extraction.unsecured_note import extract_unsecured_note
from app.ai.extraction.uscis_notice_of_action import extract_uscis_notice_of_action
from app.ai.extraction.verbal_voe import extract_verbal_voe
from app.ai.extraction.verification_of_assets import extract_verification_of_assets
from app.ai.extraction.verification_of_deposit import extract_verification_of_deposit
from app.ai.extraction.verification_of_mortgage import extract_verification_of_mortgage
from app.ai.extraction.verification_of_rent import extract_verification_of_rent
from app.ai.extraction.voe import extract_voe
from app.ai.extraction.w2 import extract_w2
from app.ai.extraction.wire_instructions import extract_wire_instructions
from app.ai.extraction.work_visa_ead_card import extract_work_visa_ead_card
from app.models.extraction import ExtractionStatus


class ExtractionResult(Protocol):
    """The common shape every extractor returns (structural — the pipeline reads these)."""

    status: ExtractionStatus
    confidence: float
    reasoning: str | None
    input_tokens: int | None
    output_tokens: int | None

    @property
    def data(self) -> BaseModel:  # serialized via model_dump(mode="json")
        ...


# An extractor: ``async (content: bytes, media_type: str) -> ExtractionResult``.
Extractor = Callable[[bytes, str], Awaitable[ExtractionResult]]

# document_type → extractor. Register a new type's extractor here (Phase 2). The
# keys MUST match the catalog's Tier-1 slugs (app/documents/catalog.py) so the
# tier-aware routing (LP-58) dispatches each Tier-1 type to its extractor.
EXTRACTORS: dict[str, Extractor] = {
    # Phase 1 (LP-39).
    "pay_stub": extract_pay_stub,
    "w2": extract_w2,
    "bank_statement": extract_bank_statement,
    # LP-60 — Tier 1 income/employment cluster.
    "1099": extract_1099,
    "voe": extract_voe,
    "profit_and_loss": extract_profit_and_loss,
    "letter_of_explanation": extract_letter_of_explanation,
    # LP-61 — Tier 1 asset cluster.
    "investment_account": extract_investment_account,
    "retirement_account": extract_retirement_account,
    "gift_letter": extract_gift_letter,
    # LP-62 — Tier 1 property cluster.
    "purchase_agreement": extract_purchase_agreement,
    "homeowners_insurance": extract_homeowners_insurance,
    "mortgage_statement": extract_mortgage_statement,
    "property_tax_bill": extract_property_tax_bill,
    "hoa_statement": extract_hoa_statement,
    # LP-63 — Tier 1 borrower-info / legal cluster. (letter_of_explanation is the
    # general-LOE extractor from LP-60, reused — registered above.)
    "drivers_license": extract_drivers_license,
    "divorce_decree": extract_divorce_decree,
    # LP-64 — Tier 1 tax returns (the nested 1040 + schedules bundle).
    "tax_return": extract_tax_return,
    # LP-443 step 7 — the first wired batch of GENERATED extractors (the vocabulary is reconciled,
    # so these catalog keys are reachable by the classifier). List-bearing types feed the generic
    # capture (_LIST_SPECS in documents_section.py); flat types are typed-core only.
    "appraisal": extract_appraisal,
    "credit_report": extract_credit_report,
    "title_commitment": extract_title_commitment,
    "condo_questionnaire": extract_condo_questionnaire,
    "aus_findings": extract_aus_findings,
    "business_license": extract_business_license,
    "certificate_of_eligibility": extract_certificate_of_eligibility,
    "verification_of_mortgage": extract_verification_of_mortgage,
    "homeowner_s_insurance_quote": extract_homeowner_s_insurance_quote,
    # LP-443 step 7 (Phase C) — the remaining generated extractors (every spec'd Tier-1 type
    # now routes to its GENERATED STARTER extractor; accuracy is unvalidated — tuning is a follow-up).
    "affiliated_business_disclosure": extract_affiliated_business_disclosure,
    "alimony_income": extract_alimony_income,
    "application_loe": extract_application_loe,
    "appraisal_payment": extract_appraisal_payment,
    "authorization_to_run_credit": extract_authorization_to_run_credit,
    "bank_deposit_slip": extract_bank_deposit_slip,
    "bankruptcy_discharge": extract_bankruptcy_discharge,
    "bankruptcy_filing": extract_bankruptcy_filing,
    "birth_certificate": extract_birth_certificate,
    "boarder_proof_of_residency": extract_boarder_proof_of_residency,
    "boarder_rental_payments": extract_boarder_rental_payments,
    "borrower_authorization_and_certification": extract_borrower_authorization_and_certification,
    "borrower_s_authorization_for_counseling": extract_borrower_s_authorization_for_counseling,
    "building_permits": extract_building_permits,
    "business_existence_verification_cpa_ltr_bus_lic": extract_business_existence_verification_cpa_ltr_bus_lic,
    "business_tax_return": extract_business_tax_return,
    "cancelled_checks_evidencing_receipt_of_note_income": extract_cancelled_checks_evidencing_receipt_of_note_income,
    "child_support_income": extract_child_support_income,
    "court_order_documents": extract_court_order_documents,
    "cpa_letter": extract_cpa_letter,
    "credit_card_authorization": extract_credit_card_authorization,
    "custom": extract_custom,
    "disability_award_letter": extract_disability_award_letter,
    "e_consent_disclosure": extract_e_consent_disclosure,
    "earnest_money_receipt": extract_earnest_money_receipt,
    "emd_withdrawal_proof": extract_emd_withdrawal_proof,
    "employment_offer_letter": extract_employment_offer_letter,
    "evidence_of_payment": extract_evidence_of_payment,
    "financial_statements": extract_financial_statements,
    "flood_certification": extract_flood_certification,
    "flood_insurance_policy": extract_flood_insurance_policy,
    "form_1040_personal_tax_transcripts": extract_form_1040_personal_tax_transcripts,
    "form_1065_partnership_tax_transcripts": extract_form_1065_partnership_tax_transcripts,
    "form_1120_corporate_tax_transcripts": extract_form_1120_corporate_tax_transcripts,
    "form_4506t_request_for_transcript": extract_form_4506t_request_for_transcript,
    "foster_care_verification": extract_foster_care_verification,
    "government_issued_id": extract_government_issued_id,
    "hoa_certification": extract_hoa_certification,
    "ira_401k": extract_ira_401k,
    "k1_statement": extract_k1_statement,
    "k_1_shareholder_profit_and_loss_transcripts": extract_k_1_shareholder_profit_and_loss_transcripts,
    "lease_agreement": extract_lease_agreement,
    "letter_of_explanation_asset": extract_letter_of_explanation_asset,
    "letter_of_explanation_child_care": extract_letter_of_explanation_child_care,
    "letter_of_explanation_income": extract_letter_of_explanation_income,
    "letter_of_explanation_misc": extract_letter_of_explanation_misc,
    "letter_of_explanation_property": extract_letter_of_explanation_property,
    "life_insurance_policy": extract_life_insurance_policy,
    "master_insurance_policy_for_condominium": extract_master_insurance_policy_for_condominium,
    "military_leave_and_earning_statement_les": extract_military_leave_and_earning_statement_les,
    "miscellaneous_document": extract_miscellaneous_document,
    "mortgage_loan_origination_agreement": extract_mortgage_loan_origination_agreement,
    "other_property_note": extract_other_property_note,
    "payoff_statement": extract_payoff_statement,
    "permanent_resident_card": extract_permanent_resident_card,
    "prior_closing_disclosure_final_cd_from_purchase": extract_prior_closing_disclosure_final_cd_from_purchase,
    "proof_of_occupancy": extract_proof_of_occupancy,
    "property_profile_non_subject": extract_property_profile_non_subject,
    "property_profile_subject": extract_property_profile_subject,
    "property_tax_bill_non_subject": extract_property_tax_bill_non_subject,
    "retirement_check": extract_retirement_check,
    "retirement_pension_award_letter": extract_retirement_pension_award_letter,
    "seller_signature_authority": extract_seller_signature_authority,
    "social_security_administration_ssa_89": extract_social_security_administration_ssa_89,
    "social_security_award_letter": extract_social_security_award_letter,
    "social_security_card": extract_social_security_card,
    "statement_of_account": extract_statement_of_account,
    "subject_property_note": extract_subject_property_note,
    "survey": extract_survey,
    "termite_completion": extract_termite_completion,
    "termite_report": extract_termite_report,
    "transcripts_of_1099": extract_transcripts_of_1099,
    "trust_agreement": extract_trust_agreement,
    "trust_documents": extract_trust_documents,
    "trust_federal_tax_returns": extract_trust_federal_tax_returns,
    "uniform_residential_loan_application": extract_uniform_residential_loan_application,
    "unsecured_note": extract_unsecured_note,
    "verbal_voe": extract_verbal_voe,
    "verification_of_assets": extract_verification_of_assets,
    "verification_of_deposit": extract_verification_of_deposit,
    "verification_of_rent": extract_verification_of_rent,
    "work_visa_ead_card": extract_work_visa_ead_card,
    # LP-465 — two rule-relevant types promoted from `unknown` (a buydown alters the qualifying
    # payment; a USCIS Notice of Action feeds ID-8). New-type generation, real modules.
    "temporary_buydown_agreement": extract_temporary_buydown_agreement,
    "uscis_notice_of_action": extract_uscis_notice_of_action,
    # LP-466 — three types from `unknown`: an AVM home-value estimate (NOT an appraisal), closing
    # wire instructions (typed + masked, was free-form general_correspondence), and a lender-portal
    # dashboard screenshot (identity only, extracts almost nothing by design).
    "home_value_estimate": extract_home_value_estimate,
    "wire_instructions": extract_wire_instructions,
    "lender_dashboard_screenshot": extract_lender_dashboard_screenshot,
}

__all__ = ["EXTRACTORS", "ExtractionResult", "Extractor"]

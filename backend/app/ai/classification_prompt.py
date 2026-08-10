"""Builds the comprehensive classification prompt from the catalog (LP-59).

The Haiku classifier must recognize the full ~80-type taxonomy. The *structural*
knowledge (which types exist, their tier + category) is the catalog
(:mod:`app.documents.catalog`); the *recognition* knowledge (the distinguishing
indicators that tell one type from a similar one) lives here, as
:data:`DOCUMENT_TYPE_INDICATORS`.

To keep the prompt and the catalog from drifting, the prompt's **type list is
derived from the catalog**: :func:`render_classification_prompt` iterates the
catalog (grouped by category) and injects each type + its indicator into the
prompt template. There is exactly one source of truth for "what types exist" —
the catalog. A test asserts every catalog type has an indicator here (and vice
versa), so adding a type to the catalog without describing it fails CI.

The indicators are an industry-standard STARTER, like the catalog itself —
**refine with Priya** and tune against real labeled documents over time.
"""

from functools import cache

from app.ai.prompt_loader import load_prompt
from app.documents.catalog import types_for_category
from app.models.document import DocumentCategory

_TEMPLATE_PATH = "classification/document_classifier.txt"
_PLACEHOLDER = "{document_type_catalog}"  # a literal template token (not an f-string)

# The order categories appear in the prompt (and their human-readable headers).
# Covers every category the catalog uses; CUSTOM is a processor-only bucket and
# is not a classifier output.
_CATEGORY_LABELS: dict[DocumentCategory, str] = {
    DocumentCategory.INCOME_EMPLOYMENT: "INCOME / EMPLOYMENT",
    DocumentCategory.ASSETS: "ASSETS",
    DocumentCategory.PROPERTY: "PROPERTY",
    DocumentCategory.CREDIT: "CREDIT",
    DocumentCategory.DISCLOSURES: "DISCLOSURES",
    DocumentCategory.BORROWER_INFO: "BORROWER INFO",
    DocumentCategory.MISC: "MISC",
}

# Per-type recognition indicators — the distinguishing cues for each catalog type.
# ONE entry per catalog type (test-enforced parity). Keep each concise: what the
# document IS plus the cues that separate it from look-alikes. Starter content;
# refine with Priya + real documents.
DOCUMENT_TYPE_INDICATORS: dict[str, str] = {
    # --- Income / Employment ---
    "pay_stub": "periodic wage statement showing employer, pay-period dates, gross/net pay, and year-to-date earnings and deductions",
    "w2": "IRS Form W-2 Wage and Tax Statement; one tax year of wages with boxes 1-6 for withholding and an employer EIN",
    "1099": "IRS Form 1099 series (NEC/MISC/INT/DIV/R); reports non-employee, interest, dividend, or retirement income with payer and recipient TINs",
    "tax_return": "IRS Form 1040 individual income tax return with schedules; a full year of income, deductions, and tax",
    "voe": "Verification of Employment; an employer-completed form confirming position, dates of employment, and income (written or verbal)",
    "profit_and_loss": "a business profit-and-loss / income statement listing revenue, expenses, and net profit over a period",
    "tax_transcript": "an IRS tax transcript (account/return/wage-and-income); an IRS-formatted summary of filed data, not the taxpayer's own 1040",
    "form_4506c": "IRS Form 4506-C; a signed request/authorization to release IRS transcripts — a consent form, not income data itself",
    "business_tax_return": "a business income tax return (Form 1120, 1120-S, or 1065) for a corporation, S-corp, or partnership",
    "k1_statement": "Schedule K-1; a partner's or shareholder's share of partnership/S-corp income, deductions, and credits",
    "social_security_award_letter": "a Social Security Administration award/benefit letter stating the monthly benefit amount and effective date",
    "pension_statement": "a pension or annuity statement showing periodic retirement benefit payments from a plan or employer",
    "retirement_income_letter": "a letter or statement documenting ongoing retirement distributions used as qualifying income",
    "unemployment_income_letter": "a state unemployment-agency statement of benefit payments",
    "disability_income_letter": "a letter documenting long-term or VA disability income and its monthly amount",
    "child_support_income": "a court order or payment record documenting child support RECEIVED as income",
    "alimony_income": "a court order or record documenting spousal support / alimony RECEIVED as income",
    "rental_income_schedule": "rental-income documentation — a lease plus Schedule E or a rent roll — supporting rental cash flow",
    "commission_income_statement": "a statement of a borrower's COMMISSION income — a commissioned salesperson's commission earnings, often a two-year history for income qualification. NOT an employer's annual compensation/rewards statement of base+bonus+equity (that is compensation_statement)",
    "compensation_statement": "an EMPLOYER-issued annual COMPENSATION / rewards statement — a year-end summary of a salaried employee's pay: base salary (current and new), a performance/incentive BONUS or AIP award, an EQUITY award (RSUs or shares), and a performance rating. Employer-branded (e.g. 'Compensation Statement', 'Year-end Review Summary', 'Performance and Rewards'). NOT commission_income_statement (a commissioned salesperson's commission-income history), NOT a pay_stub (a single pay period), NOT voe or employment_offer_letter",
    "employment_offer_letter": "a signed employment offer or contract stating job title, start date, and salary for new/future employment",
    # LP-442 income/employment additions
    "form_1040_personal_tax_transcripts": "an IRS account/return TRANSCRIPT of a personal Form 1040 (IRS-generated AGI/taxable-income/total-tax summary of a filed return) — the IRS transcript, not the taxpayer's own 1040 (tax_return) and not the generic tax_transcript",
    "form_1065_partnership_tax_transcripts": "an IRS TRANSCRIPT of a partnership Form 1065 (EIN, ordinary business income) — the IRS-generated partnership-return summary, not a personal or corporate transcript",
    "form_1120_corporate_tax_transcripts": "an IRS TRANSCRIPT of a corporate Form 1120/1120-S (EIN, taxable income, total tax) — the IRS-generated corporate-return summary, not a partnership or personal transcript",
    "form_4506t_request_for_transcript": "IRS Form 4506-T/4506T-EZ — a signed REQUEST authorizing the IRS to release transcripts; a consent/request form, not transcript data (distinct from form_4506c, the 4506-C variant)",
    "transcripts_of_1099": "an IRS wage-and-income TRANSCRIPT of 1099 records for a year (a count of payer records) — the IRS-sourced 1099 summary, distinct from the 1099 form itself and from the generic tax_transcript",
    "k_1_shareholder_profit_and_loss_transcripts": "an IRS TRANSCRIPT of a Schedule K-1 (partner/shareholder income) — IRS-issued, distinct from k1_statement (the K-1 form from the entity) by issuer and layout",
    "trust_federal_tax_returns": "a trust/estate federal income tax RETURN (Form 1041): the trust's income, distributable net income, and distributions to beneficiaries — a tax return for a trust, not the trust agreement/certification documents",
    "cpa_letter": "a CPA-signed letter attesting to a self-employed borrower's business existence, ownership percentage, or ability to withdraw funds — a professional attestation letter, not a tax return or financial statement",
    "business_existence_verification_cpa_ltr_bus_lic": "verification that a business exists / is in good standing via a CPA letter, business license, or secretary-of-state record — the business-existence proof for self-employment (broader than a single cpa_letter or business_license)",
    "business_license": "a government-issued business LICENSE/permit to operate (license type, issuing agency, status, expiration) evidencing an active self-employed business — an operating license, not a CPA attestation",
    "disability_award_letter": "a disability determination/AWARD letter stating the awarded monthly benefit, start date, and continuance terms — the award (with continuance), distinct from disability_income_letter (which merely documents the income amount)",
    "retirement_pension_award_letter": "a retirement/pension AWARD letter establishing the monthly benefit and whether it is lifetime (IN-13 continuance) — the award that sets the benefit, distinct from pension_statement/retirement_income_letter (a balance or a payment record)",
    "retirement_check": "a retirement/pension benefit CHECK or its clearing evidence (payer, payee, net amount, frequency) — proof of a received retirement payment, not the award letter or an account statement",
    "verbal_voe": "a record of a VERBAL (telephone) verification of employment — a call log of who was contacted, the result, and the call date; NOT a signed employer VOE form (that is voe)",
    "military_leave_and_earning_statement_les": "a military Leave and Earnings Statement (LES) — a service member's pay statement with grade, entitlements, and net pay; the military equivalent of a pay stub, not a civilian pay_stub",
    "foster_care_verification": "a state-agency verification of foster-care payments (monthly amount, placement date, expected continuance) used as qualifying income",
    "boarder_rental_payments": "a record of a boarder's rent PAYMENTS to the borrower (amount, frequency, payment history) supporting boarder income — the payment evidence, distinct from boarder_proof_of_residency (which only proves the boarder lives there)",
    "boarder_proof_of_residency": "evidence that a boarder RESIDES at the borrower's address (a utility bill, ID, or mail addressed to the boarder there) — proof of residency, not the rent-payment record (boarder_rental_payments)",
    "cancelled_checks_evidencing_receipt_of_note_income": "cancelled/cleared checks evidencing RECEIPT of installment-note income by the borrower (drawer, amount, cleared date) — proof the note payments are actually received",
    # --- Assets ---
    "bank_statement": "a monthly depository (checking/savings) statement with the institution, account holder, transactions, and beginning/ending balances",
    "investment_account": "a brokerage or investment account statement showing securities holdings and a portfolio balance",
    "retirement_account": "a retirement account statement (401(k), IRA, 403(b)) showing the vested/available balance",
    "gift_letter": "a signed gift letter stating a donor gives funds with no repayment expected; names donor, amount, and relationship",
    "verification_of_deposit": "a Verification of Deposit (VOD) completed by a financial institution confirming account balances",
    "brokerage_statement": "a securities brokerage statement listing stocks, bonds, or funds and their market value",
    "money_market_statement": "a money-market account statement showing the balance and interest",
    "certificate_of_deposit": "a certificate of deposit (CD) statement or certificate showing principal, term, and maturity",
    "earnest_money_receipt": "a receipt or canceled check evidencing the earnest-money deposit on the purchase",
    "gift_donor_bank_statement": "the gift DONOR's bank statement evidencing the source of donated funds (paired with a gift letter)",
    "life_insurance_statement": "a life-insurance statement showing cash surrender value used as an asset",
    "sale_of_asset_proof": "documentation of proceeds from selling an asset (e.g. a vehicle) — a bill of sale plus deposit evidence",
    "crypto_account_statement": "a cryptocurrency exchange/account statement showing holdings and their value",
    # LP-442 asset additions
    "ira_401k": "an IRA or 401(k) retirement-account statement emphasizing the withdrawal-eligible / net-of-plan-loan accessible balance — overlaps the generic retirement_account; prefer this when the plan type (IRA/401(k)) and the accessible portion are the focus",
    "bank_deposit_slip": "a bank deposit slip/receipt for a specific deposit (cash-vs-checks split, account last-4, date) — evidence of one deposit, not a full account statement",
    "emd_withdrawal_proof": "proof the earnest-money funds were WITHDRAWN/debited from the borrower's account (the sourcing debit: amount, account, date) — distinct from earnest_money_receipt (escrow/seller's receipt of the EMD)",
    "life_insurance_policy": "a life-insurance POLICY stating coverage/face amount and beneficiaries (and any net cash value) — the policy document, distinct from life_insurance_statement (the periodic cash-value statement AS-4 reads)",
    "verification_of_assets": "a third-party asset-aggregator report (e.g. AccountChek) covering MANY of the borrower's accounts with a total verified balance — distinct from verification_of_deposit (one institution confirming one account)",
    "financial_statements": "a personal (or business) financial statement listing total assets, liabilities, and net worth as of a date — a net-worth statement, not a bank/brokerage account statement",
    "statement_of_account": "a generic account statement giving the account holder, balance, monthly payment, and current status — a catch-all account statement (may be an asset or a liability account; prefer a more specific type when the account kind is clear)",
    # --- Property ---
    "purchase_agreement": "a signed real-estate purchase and sale contract; buyer/seller, property address, price, and contingencies",
    "homeowners_insurance": "a homeowner's hazard insurance policy or declarations page; coverage amounts, premium, and the insured property",
    "mortgage_statement": "a monthly mortgage billing statement for an existing loan; principal balance, payment, and escrow",
    "form_1098": "an IRS Form 1098 'Mortgage Interest Statement' — the ANNUAL TAX form a mortgage servicer/lender furnishes for a calendar year, reporting mortgage interest received (Box 1), outstanding principal (Box 2), points, and often real-estate taxes in the free-text Box 10. It prints 'Form 1098', 'Mortgage Interest Statement', 'Copy B For Payer/Borrower', and OMB No. 1545-1380. NOT form_1099 (a different IRS return — reports income, not mortgage interest), NOT mortgage_statement (a MONTHLY servicer bill with an 'amount due by' date — a 1098 is an ANNUAL 'keep for your records' tax form), and NOT property_tax_bill (a taxing authority's bill — a 1098 mentions taxes only as free text in Box 10)",
    "property_tax_bill": "a county/municipal property tax bill or assessment showing the annual tax and the parcel",
    "hoa_statement": "a homeowners-association statement or dues invoice showing the HOA fee and the property",
    "appraisal": "a Uniform Residential Appraisal Report (URAR/Form 1004) with appraised value, comparables, and property condition",
    "title_commitment": "a title insurance commitment listing vesting, liens, and exceptions to clear before closing",
    "preliminary_title_report": "a preliminary title report summarizing ownership and encumbrances ahead of the commitment",
    "flood_certification": "a FEMA flood-zone determination (SFHDF) stating whether the property is in a special flood hazard area",
    "flood_insurance_policy": "a flood insurance policy or declarations page (separate from hazard insurance)",
    "survey": "a property/land survey or plat showing boundaries, structures, and easements",
    "warranty_deed": "a recorded deed (warranty/grant/quitclaim) conveying title; grantor, grantee, and legal description",
    "home_inspection_report": "a home inspection report on the condition of the property's systems and structure",
    "pest_inspection_report": "a termite / wood-destroying-organism (pest) inspection report",
    "well_septic_certification": "a well-water or septic-system certification/inspection for a non-municipal property",
    "condo_questionnaire": "a condominium project questionnaire (HOA-completed) on budget, ownership, and litigation",
    "payoff_statement": "a payoff/demand statement from a lienholder stating the amount to fully pay off an existing loan",
    "lease_agreement": "a residential lease/rental agreement for a tenant-occupied property",
    # LP-442 property additions
    "master_insurance_policy_for_condominium": "a condominium association's MASTER (blanket) insurance policy covering the whole project (carrier, project name, RCV, deductible) — the HOA's building policy, distinct from the borrower's individual homeowners_insurance (an HO-6 walls-in policy)",
    "building_permits": "a government BUILDING PERMIT for work on the property (permit type, jurisdiction, status, estimated cost) — a construction/renovation permit",
    "hoa_certification": "an HOA/condo project CERTIFICATION of project health (unit count, owner-occupancy %, delinquency %, litigation) — the project-eligibility certification, distinct from hoa_statement (a dues invoice) and condo_questionnaire (the full questionnaire)",
    "homeowner_s_insurance_quote": "a homeowner's insurance QUOTE/estimate (coverage, premium, valid-through date) not yet bound — a proposal, distinct from homeowners_insurance (a bound policy or declarations page)",
    "termite_report": "a termite / wood-destroying-organism INSPECTION report stating findings and whether the property is clear — the inspection findings, distinct from termite_completion (proof the treatment was performed)",
    "termite_completion": "a termite treatment COMPLETION certificate — evidence the treatment/work was performed and the property cleared, distinct from termite_report (the inspection findings)",
    "property_profile_subject": "a data-vendor property profile (APN, owner, assessed/AVM value, tax status) for the SUBJECT property of this loan — distinct from property_profile_non_subject (another property)",
    "property_profile_non_subject": "a data-vendor property profile for a NON-subject property the borrower owns/is involved with — distinct from property_profile_subject (the loan's subject property)",
    "property_tax_bill_non_subject": "a property TAX BILL for a NON-subject property the borrower owns (REO/DTI) — distinct from property_tax_bill (the SUBJECT property's tax bill)",
    "proof_of_occupancy": "evidence of who OCCUPIES a property (a utility bill, voter registration, or lease tied to a service address and date) — occupancy proof, not a deed or a property profile",
    "subject_property_note": "the promissory NOTE for the loan on the SUBJECT property (original principal, rate, P&I, maturity) — this loan's mortgage note, distinct from other_property_note (a note on another property)",
    "other_property_note": "a promissory NOTE on ANOTHER (non-subject) property the borrower owns (its principal, rate, P&I) — distinct from subject_property_note (this loan's note)",
    "seller_signature_authority": "documentation of who may sign for a SELLER entity (trust, LLC, estate) and under what authority, scoped to a property — a seller-side signing-authority document",
    "certificate_of_liability_insurance": "an ACORD 25 'Certificate of Liability Insurance' — a one-page standardized ACORD form SUMMARIZING the liability policies (Commercial General Liability, Automobile, Umbrella/Excess, Workers Compensation) an insurer has issued to an insured, furnished as evidence to a certificate holder. It states it 'confers no rights' and 'does not constitute a contract' — a CERTIFICATE, not a policy. NOT master_insurance_policy_for_condominium (the governing condo master POLICY with dwelling/property coverage, deductibles, causes of loss) and NOT homeowners_insurance (a borrower's HO policy or dec page)",
    "home_value_estimate": "an Automated Valuation Model (AVM) / Home Value Estimate — a software-generated estimated market value (an estimated value, a value range, and basic property facts: beds/baths/sq ft/taxes), typically from a lender portal's 'Home Value Estimator' tool, that EXPLICITLY states it is NOT an appraisal ('does not constitute an appraisal; should not be relied upon in lieu of an appraisal'). NOT an appraisal (a licensed URAR/Form 1004 with comparables, condition, and a certified value) and NOT a property_profile_subject (a data-vendor profile with APN/owner/tax status). A non-binding value estimate only",
    # --- Credit ---
    "credit_report": "a tri-merge or single-bureau consumer credit report listing tradelines, balances, inquiries, and scores",
    "credit_explanation_letter": "a borrower letter explaining specific credit events (late payments, inquiries) — a credit-specific LOE",
    "credit_supplement": "a credit supplement updating or verifying a specific tradeline or item on the credit report",
    "bankruptcy_discharge": "a court bankruptcy discharge/closing order (Chapter 7/13) showing the case was discharged",
    "foreclosure_documentation": "documentation of a foreclosure, short sale, or deed-in-lieu and its completion date",
    "judgment_documentation": "court records of a judgment or lien against the borrower and its status",
    "collection_account_letter": "a collection-agency notice or letter regarding a debt in collections",
    "debt_payoff_statement": "a statement or letter showing a debt has been or will be paid off (to exclude it from DTI)",
    "student_loan_statement": "a student-loan servicer statement showing the balance and monthly payment",
    "installment_loan_statement": "an installment-loan (auto/personal) statement showing balance, payment, and remaining term",
    # LP-442 credit additions
    "bankruptcy_filing": "a bankruptcy FILING/petition (chapter, filing date, case number, debtor) — the petition that opens a case, distinct from bankruptcy_discharge (the order closing/discharging it)",
    "unsecured_note": "an unsecured promissory note (maker to payee, principal, rate, payment, maturity) NOT secured by real estate — a personal/business note, distinct from the property-secured subject_property_note/other_property_note",
    "verification_of_mortgage": "a Verification of Mortgage (VOM): a servicer's confirmation of the borrower's existing mortgage — balance, payment, and 30/60/90-day late history; the mortgage payment-history verification, distinct from mortgage_statement (a billing statement)",
    "verification_of_rent": "a Verification of Rent (VOR): a landlord's confirmation of the borrower's rent amount, lease start, and late-payment history — the rental payment-history verification, distinct from lease_agreement (the contract)",
    # --- Disclosures ---
    "closing_disclosure": "the TRID Closing Disclosure (CD); FINAL loan terms, closing costs, and cash-to-close in the standard 5-page form",
    "loan_estimate": "the TRID Loan Estimate (LE); ESTIMATED loan terms and costs in the standard 3-page form",
    "intent_to_proceed": "a signed Intent to Proceed acknowledging the borrower wishes to continue after the Loan Estimate",
    "notice_of_right_to_cancel": "a Notice of Right to Cancel / right of rescission for a refinance of a primary residence",
    "truth_in_lending": "a Truth in Lending (TIL) disclosure with the APR and finance charge (legacy/Reg Z)",
    "servicing_disclosure": "a mortgage servicing disclosure stating whether the loan may be transferred or sold",
    "affiliated_business_disclosure": "an Affiliated Business Arrangement (AfBA) disclosure of relationships among settlement providers",
    "privacy_notice": "a GLBA privacy notice describing how borrower information is collected and shared",
    "e_consent_disclosure": "an electronic-records consent (E-SIGN / eConsent) authorizing electronic delivery of disclosures",
    # LP-442 disclosure/authorization additions (decision 2 replaces the generic borrower_authorization)
    "authorization_to_run_credit": "a borrower authorization permitting a named company to PULL/run their credit (purpose, scope, signature date) — a credit-pull consent; distinct from borrower_authorization_and_certification (the broad verify-and-certify authorization) and credit_card_authorization (charge a card)",
    "borrower_authorization_and_certification": "a broad signed borrower AUTHORIZATION AND CERTIFICATION permitting the lender to verify employment, assets, and credit, and certifying the application — distinct from authorization_to_run_credit (credit-pull only)",
    "borrower_s_authorization_for_counseling": "a borrower's authorization for housing/credit COUNSELING (agency, HUD ID, counseling type) — a counseling-consent form, not a credit-pull or verification authorization",
    "credit_card_authorization": "an authorization to CHARGE a borrower's credit card for fees (cardholder, brand, last-4, amount, one-time/recurring) — a payment authorization, distinct from authorization_to_run_credit (a credit-PULL authorization)",
    "social_security_administration_ssa_89": "an SSA-89: a borrower's signed consent authorizing a company to verify the SSN with the Social Security Administration — an SSN-verification consent form",
    "mortgage_loan_origination_agreement": "a mortgage loan ORIGINATION agreement between the borrower and the broker/originator (NMLS ID, compensation method) — the origination/broker agreement",
    "prior_closing_disclosure_final_cd_from_purchase": "a FINAL Closing Disclosure from a PRIOR/previous purchase transaction (seasoning/ownership evidence) — a past loan's CD; NOT the current loan's closing_disclosure (conflating them is dangerous)",
    "temporary_buydown_agreement": "a Temporary Buydown Agreement — a standalone agreement (often titled 'Temporary Buydown Agreement') funding a temporary reduction of the borrower's rate/payment for the first 1-2 years (a 2-1 or 1-0 buydown) via a subsidy held in a separate escrow account; carries a per-period PAYMENT SCHEDULE of reduced rates, borrower payments, and the monthly subsidy applied. NOT the note, loan_estimate, or closing_disclosure — the standalone subsidy agreement",
    # --- Borrower Info ---
    "drivers_license": "a state-issued driver's license or ID card; photo, name, date of birth, and address",
    "divorce_decree": "a court divorce decree / judgment of dissolution; may set support obligations and property division",
    "letter_of_explanation": "a borrower-written letter of explanation (LOE) addressing a question in the file (general purpose)",
    "passport": "a government PASSPORT — a travel/identity booklet or photo page: the printed word 'PASSPORT', a nationality / issuing country, place and date of birth, a passport number, and a machine-readable zone (MRZ). A passport is a TRAVEL and RE-ENTRY document. It is NOT an Employment Authorization Document — an EAD card is titled 'EMPLOYMENT AUTHORIZATION', shows Form 'I-766', a category code (e.g. C26), and states 'NOT VALID FOR REENTRY'; route that to work_visa_ead_card",
    "social_security_card": "a Social Security card showing the name and SSN",
    "permanent_resident_card": "a Permanent Resident Card (green card / Form I-551) evidencing lawful permanent residency",
    "visa_documentation": "a TRAVEL VISA stamp/foil (typically in a passport) evidencing non-citizen status to enter/reside — NOT a USCIS Notice of Action (route an I-797 to uscis_notice_of_action) and NOT an EAD card (work_visa_ead_card)",
    "birth_certificate": "an official birth certificate",
    "marriage_certificate": "an official marriage certificate or license",
    "military_id": "a U.S. military identification card",
    "power_of_attorney": "a power of attorney authorizing someone to sign on the borrower's behalf",
    "trust_documentation": "a trust agreement / certification of trust when title is held in a trust",
    "name_affidavit": "a name/signature affidavit attesting to name variations (aka) for the same borrower",
    # LP-442 borrower-info additions (incl. the topical LOE variants)
    "government_issued_id": "a generic government-issued photo ID used for identity when it is not clearly a driver's license, passport, or military ID — a fallback ID type by design (prefer drivers_license/passport/military_id when the specific kind is clear)",
    "work_visa_ead_card": "a USCIS Employment Authorization Document (EAD) — a card titled 'EMPLOYMENT AUTHORIZATION', Form I-766, with a CATEGORY CODE (e.g. C26), a USCIS#, valid-from/expiration dates, and the line 'NOT VALID FOR REENTRY' — the physical work-authorization card ID-8 checks. Distinct from a passport (a travel/re-entry booklet — an EAD is expressly 'NOT VALID FOR REENTRY'), visa_documentation (a travel visa), permanent_resident_card, and uscis_notice_of_action (an I-797 NOTICE, not a card)",
    "uscis_notice_of_action": "a USCIS Notice of Action (Form I-797A/B/C) — USCIS correspondence receipting or APPROVING a petition: shows a receipt number, a case type (e.g. I-129), notice/received/validity dates, a petitioner + beneficiary, and often a tear-off I-94 block. A NOTICE about a petition, NOT a travel visa / green card / EAD card / passport (the form itself states 'THIS NOTICE IS NOT A VISA'); route the I-797 here even when it concerns a work class (H-1B)",
    "court_order_documents": "a court order (other than a divorce decree) setting an obligation — a support award, judgment, or similar — with the obligation type, amount, and END date; distinct from divorce_decree (dissolution) and judgment_documentation",
    "trust_agreement": "the TRUST AGREEMENT instrument itself: which trust, the trustee(s), and whether the trust may encumber the property — the governing trust document, distinct from trust_documents (certifications/ancillary) and the existing trust_documentation",
    "trust_documents": "trust CERTIFICATION or ancillary trust paperwork (certificate of trust, trustee-powers excerpt) accompanying the agreement — hard to separate from the existing trust_documentation and from trust_agreement; use this for a certification/excerpt, trust_agreement for the full instrument",
    "application_loe": "a borrower letter of explanation about an APPLICATION issue — a discrepancy or question on the loan application (URLA) itself — an application-scoped LOE, distinct from the generic letter_of_explanation and the topical LOE variants",
    "letter_of_explanation_asset": "a borrower LOE about an ASSET or a specific deposit — its source and that it is not borrowed; an asset-scoped LOE, distinct from the generic letter_of_explanation",
    "letter_of_explanation_child_care": "a borrower LOE about CHILDCARE arrangements/expense (e.g. care provided free by a relative, or the monthly cost) — a childcare-scoped LOE",
    "letter_of_explanation_income": "a borrower LOE about an INCOME issue — a gap, a drop, or an unusual source over an affected period — an income-scoped LOE",
    "letter_of_explanation_misc": "a borrower LOE addressing a MISCELLANEOUS question that fits no other LOE scope — a catch-all LOE variant",
    "letter_of_explanation_property": "a borrower LOE about a PROPERTY issue (occupancy, a departing residence, a second home) — a property-scoped LOE",
    # --- Misc ---
    "uniform_residential_loan_application": "the Uniform Residential Loan Application (URLA / Form 1003); the borrower's full loan application",
    "underwriting_approval": "an underwriting approval / conditional approval stating the loan decision and outstanding conditions",
    "rate_lock_agreement": "a rate-lock confirmation/agreement stating the locked interest rate, term, and expiration",
    "general_correspondence": "general loan-file correspondence (emails, notes, cover letters) that doesn't fit another type",
    # LP-442 misc additions
    "aus_findings": "an Automated Underwriting System findings report (DU/LP): engine, recommendation, casefile ID, condition count — the AUS decision report",
    "certificate_of_eligibility": "a VA Certificate of Eligibility (COE): veteran entitlement code, available entitlement, funding-fee status — the VA loan-eligibility certificate",
    "appraisal_payment": "proof of PAYMENT for the appraisal (payer, amount, AMC/appraiser, order number, date) — a fee-payment receipt (often paid-outside-closing), not the appraisal report",
    "evidence_of_payment": "generic evidence that a payment/obligation was made or paid in full (payer, payee, amount, method, date) — a catch-all payment proof when no more specific type fits",
    "custom": "a processor-defined CUSTOM document type that fits none of the known types — an explicit escape hatch (title + issuer + date); its contents are extracted generically",
    "miscellaneous_document": "a miscellaneous loan-file document (title, issuer, date) that fits no other known type — the long-tail catch-all",
    "wire_instructions": "closing/settlement wire instructions — a payee sheet from a title company, law firm, or escrow/settlement agent giving where to send closing funds: a beneficiary name/address, a receiving bank name/address, an ABA routing number and account number, often a callback phone to verify. Transactional funds-routing, NOT general_correspondence, and NOT a bank_statement or verification_of_deposit (it moves funds, it does not evidence a borrower's assets)",
    "service_invoice": "a vendor service invoice — a BILL from a service provider (loan processor, surveyor, credit/title vendor, etc.) stating an amount OWED for a service: a vendor, an invoice date, a service description, and a total. NOT general_correspondence (it is a structured bill), and NOT appraisal_payment / evidence_of_payment (those are proof a payment was MADE — a receipt; an invoice is what is owed, before payment)",
    "lender_dashboard_screenshot": "a screenshot/print of a lender or broker PORTAL (e.g. uwm.com/dashboard) — software UI chrome: navigation, pipeline/loan alerts, rankings/points, marketing tiles, embedded tools. A capture of an application, NOT the underlying document — the loan/borrower data it displays (a status, an AVM block, a rate) is not itself this type. Route a capture DOMINATED by one embedded artifact (e.g. the Home Value Estimator screen) to that artifact's type (home_value_estimate); use this only for a broad dashboard where no single embedded document dominates",
}


def _render_catalog_section() -> str:
    """Build the by-category type+indicator listing injected into the prompt.

    Iterates the catalog (via :func:`types_for_category`) so the prompt's type
    list is exactly the catalog's — the single source of truth. Raises ``KeyError``
    if a catalog type has no indicator (a programmer error; the sync test guards it).
    """
    blocks: list[str] = []
    for category, label in _CATEGORY_LABELS.items():
        slugs = types_for_category(category)
        if not slugs:
            continue
        lines = [f"{label}:"]
        lines += [f"  - {slug} — {DOCUMENT_TYPE_INDICATORS[slug]}" for slug in slugs]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


@cache
def render_classification_prompt() -> str:
    """The full classification system prompt — template + catalog-derived type list.

    Cached: the catalog and indicators are static at runtime. Raises ``ValueError``
    if the template lost its ``{document_type_catalog}`` placeholder (a programmer
    error, surfaced loudly rather than silently shipping a prompt with no types).
    """
    template = load_prompt(_TEMPLATE_PATH)
    if _PLACEHOLDER not in template:
        raise ValueError(f"Classification prompt template is missing {_PLACEHOLDER!r}")
    return template.replace(_PLACEHOLDER, _render_catalog_section())

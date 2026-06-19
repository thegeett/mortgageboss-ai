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
    "commission_income_statement": "a statement breaking out commission or bonus earnings, often to show a two-year history",
    "employment_offer_letter": "a signed employment offer or contract stating job title, start date, and salary for new/future employment",
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
    # --- Property ---
    "purchase_agreement": "a signed real-estate purchase and sale contract; buyer/seller, property address, price, and contingencies",
    "homeowners_insurance": "a homeowner's hazard insurance policy or declarations page; coverage amounts, premium, and the insured property",
    "mortgage_statement": "a monthly mortgage billing statement for an existing loan; principal balance, payment, and escrow",
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
    # --- Disclosures ---
    "closing_disclosure": "the TRID Closing Disclosure (CD); FINAL loan terms, closing costs, and cash-to-close in the standard 5-page form",
    "loan_estimate": "the TRID Loan Estimate (LE); ESTIMATED loan terms and costs in the standard 3-page form",
    "borrower_authorization": "a signed borrower authorization permitting the lender to verify employment, assets, and credit",
    "intent_to_proceed": "a signed Intent to Proceed acknowledging the borrower wishes to continue after the Loan Estimate",
    "notice_of_right_to_cancel": "a Notice of Right to Cancel / right of rescission for a refinance of a primary residence",
    "truth_in_lending": "a Truth in Lending (TIL) disclosure with the APR and finance charge (legacy/Reg Z)",
    "servicing_disclosure": "a mortgage servicing disclosure stating whether the loan may be transferred or sold",
    "affiliated_business_disclosure": "an Affiliated Business Arrangement (AfBA) disclosure of relationships among settlement providers",
    "privacy_notice": "a GLBA privacy notice describing how borrower information is collected and shared",
    "e_consent_disclosure": "an electronic-records consent (E-SIGN / eConsent) authorizing electronic delivery of disclosures",
    # --- Borrower Info ---
    "drivers_license": "a state-issued driver's license or ID card; photo, name, date of birth, and address",
    "divorce_decree": "a court divorce decree / judgment of dissolution; may set support obligations and property division",
    "letter_of_explanation": "a borrower-written letter of explanation (LOE) addressing a question in the file (general purpose)",
    "passport": "a government passport used as photo identification; the photo page and passport number",
    "social_security_card": "a Social Security card showing the name and SSN",
    "permanent_resident_card": "a Permanent Resident Card (green card / Form I-551) evidencing lawful permanent residency",
    "visa_documentation": "a visa or work-authorization document (e.g. an EAD) evidencing non-citizen status to reside/work",
    "birth_certificate": "an official birth certificate",
    "marriage_certificate": "an official marriage certificate or license",
    "military_id": "a U.S. military identification card",
    "power_of_attorney": "a power of attorney authorizing someone to sign on the borrower's behalf",
    "trust_documentation": "a trust agreement / certification of trust when title is held in a trust",
    "name_affidavit": "a name/signature affidavit attesting to name variations (aka) for the same borrower",
    # --- Misc ---
    "uniform_residential_loan_application": "the Uniform Residential Loan Application (URLA / Form 1003); the borrower's full loan application",
    "underwriting_approval": "an underwriting approval / conditional approval stating the loan decision and outstanding conditions",
    "rate_lock_agreement": "a rate-lock confirmation/agreement stating the locked interest rate, term, and expiration",
    "general_correspondence": "general loan-file correspondence (emails, notes, cover letters) that doesn't fit another type",
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

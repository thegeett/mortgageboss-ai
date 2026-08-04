# Registration snippets — the wiring step 7 will apply (LP-440)

LP-440 generated the extractor modules but **wired nothing** (GENERATE, DO NOT WIRE). This is the complete set
of registration snippets step 7 will apply — one block per spec: the `EXTRACTORS` import + entry, the
`_PII_FIELDS` entries (already remapped to `PiiKind.{SSN,ACCOUNT}` by LP-439), the `_LIST_SPECS` `ListSpec` +
registration, and the count cross-check(s). **Every one is a snippet, never a patch** — the 36 live rules and
the catalog invariant cannot move until these are applied deliberately.

Diff-mode specs (the 18 shipping extractors) carry a DIFF REPORT instead of a module — the typed-core additions
+ the `ListSpec` for their lists, to be hand-applied.

---

### 001-application-1003 (application_1003) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.application_1003 import extract_application_1003
# ... and inside the EXTRACTORS dict:
    "application_1003": extract_application_1003,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "social_security_number": (PiiKind.SSN, False),
    "social_security_number_2": (PiiKind.SSN, False),


### 002-bank-statement — DIFF REPORT (app/ai/extraction/bank_statement.py)
# Diff-mode report — bank_statement (existing: app/ai/extraction/bank_statement.py)
#
# A shipping extractor exists. This is a REPORT of what the spec adds, NOT a patch
# (guide §6 / D6). Apply the ADD items by hand; each BLOCKED item is its own ticket.

## Typed-core additions (13)
- ADD      account_holder_names_raw: TypedField[str] / coerce_str
- ADD      account_owner_name_2: TypedField[str] / coerce_str
- ADD      account_owner_count: TypedField[int] / coerce_int
- ADD      account_holder_address: TypedField[str] / coerce_str
- ADD      account_status: TypedField[str] / coerce_str
- ADD      available_balance: TypedField[Decimal] / coerce_decimal
- ADD      average_daily_balance: TypedField[Decimal] / coerce_decimal
- ADD      nsf_fee_count: TypedField[int] / coerce_int
- ADD      nsf_fee_total: TypedField[Decimal] / coerce_decimal
- ADD      fees_total: TypedField[Decimal] / coerce_decimal
- ADD      minimum_balance_requirement: TypedField[Decimal] / coerce_decimal
- ADD      holds_or_pledges: TypedField[str] / coerce_str
- ADD      interest_paid: TypedField[Decimal] / coerce_decimal

## Nested lists (1) — GENERIC (LP-437): a declaration, not ~5 files
- ADD      transactions: 5 row fields [derived=['direction'], redact=['description'], stable_row_id] (+ a per-rule consumer — enumerator or derived recipe — as separate follow-up)

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_TRANSACTIONS_LIST = ListSpec(
    name="transactions",
    fields=("date", "description", "amount", "transaction_type", "running_balance",),
    derived=(
        DerivedSpec(field="direction", from_field="transaction_type", mapping={"deposit": "credit", "withdrawal": "debit"}),
    ),
    redact=frozenset({"description"}),
    stable_row_id=True,
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "bank_statement": (_TRANSACTIONS_LIST,),


### 003-purchase-agreement — DIFF REPORT (app/ai/extraction/purchase_agreement.py)
# Diff-mode report — purchase_agreement (existing: app/ai/extraction/purchase_agreement.py)
#
# A shipping extractor exists. This is a REPORT of what the spec adds, NOT a patch
# (guide §6 / D6). Apply the ADD items by hand; each BLOCKED item is its own ticket.

## Typed-core additions (27)
- ADD      buyer_name_2: TypedField[str] / coerce_str
- ADD      buyer_names_raw: TypedField[str] / coerce_str
- ADD      buyer_count: TypedField[int] / coerce_int
- ADD      seller_name_2: TypedField[str] / coerce_str
- ADD      seller_names_raw: TypedField[str] / coerce_str
- ADD      seller_count: TypedField[int] / coerce_int
- ADD      parties_relationship_disclosed: TypedField[str] / coerce_str
- ADD      listing_agent_name: TypedField[str] / coerce_str
- ADD      selling_agent_name: TypedField[str] / coerce_str
- ADD      legal_description: TypedField[str] / coerce_str
- ADD      property_type: TypedField[str] / coerce_str
- ADD      hoa_indicator: TypedField[str] / coerce_str
- ADD      hoa_dues_amount: TypedField[Decimal] / coerce_decimal
- ADD      annual_property_tax: TypedField[Decimal] / coerce_decimal
- ADD      earnest_money_due_date: TypedField[date] / coerce_date
- ADD      earnest_money_holder: TypedField[str] / coerce_str
- ADD      seller_credit_amount: TypedField[Decimal] / coerce_decimal
- ADD      seller_credit_purpose: TypedField[str] / coerce_str
- ADD      other_concessions_amount: TypedField[Decimal] / coerce_decimal
- ADD      down_payment_amount: TypedField[Decimal] / coerce_decimal
- ADD      loan_amount_stated: TypedField[Decimal] / coerce_decimal
- ADD      contract_date: TypedField[date] / coerce_date
- ADD      contract_expiration_date: TypedField[date] / coerce_date
- ADD      all_parties_signed: TypedField[str] / coerce_str
- ADD      personal_property_included: TypedField[str] / coerce_str
- ADD      personal_property_value: TypedField[Decimal] / coerce_decimal
- ADD      side_agreements_referenced: TypedField[str] / coerce_str

## Nested lists (2) — GENERIC (LP-437): a declaration, not ~5 files
- ADD      addenda: 5 row fields (+ a per-rule consumer — enumerator or derived recipe — as separate follow-up)
- ADD      contingencies: 3 row fields (+ a per-rule consumer — enumerator or derived recipe — as separate follow-up)

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_ADDENDA_LIST = ListSpec(
    name="addenda",
    fields=("addendum_name", "addendum_type", "addendum_date", "is_signed", "is_attached",),
)

_CONTINGENCIES_LIST = ListSpec(
    name="contingencies",
    fields=("contingency_type", "deadline_date", "is_waived",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "purchase_agreement": (_ADDENDA_LIST, _CONTINGENCIES_LIST,),


### 004-title-commitment (title_commitment) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.title_commitment import extract_title_commitment
# ... and inside the EXTRACTORS dict:
    "title_commitment": extract_title_commitment,

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_SCHEDULE_B_ITEMS_LIST = ListSpec(
    name="schedule_b_items",
    fields=("schedule", "item_number", "item_type", "description", "recording_date", "recording_reference", "amount", "is_satisfied", "affected_party",),
)

_CHAIN_OF_TITLE_LIST = ListSpec(
    name="chain_of_title",
    fields=("transfer_date", "grantor", "grantee", "consideration_amount", "recording_reference",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "title_commitment": (_SCHEDULE_B_ITEMS_LIST, _CHAIN_OF_TITLE_LIST,),


### 005-credit-report (credit_report) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.credit_report import extract_credit_report
# ... and inside the EXTRACTORS dict:
    "credit_report": extract_credit_report,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "borrower_ssn": (PiiKind.SSN, False),
    "co_borrower_ssn": (PiiKind.SSN, False),

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_TRADELINES_LIST = ListSpec(
    name="tradelines",
    fields=("creditor_name", "account_type", "account_number_masked", "account_ownership", "date_opened", "balance", "credit_limit_or_high_credit", "monthly_payment", "past_due_amount", "account_status", "payment_status", "payment_history_24mo", "worst_delinquency", "is_disputed",),
)

_PUBLIC_RECORDS_LIST = ListSpec(
    name="public_records",
    fields=("record_type", "filing_date", "discharge_or_satisfied_date", "status", "amount", "court_or_jurisdiction",),
)

_INQUIRIES_LIST = ListSpec(
    name="inquiries",
    fields=("inquiry_date", "creditor_name", "inquiry_type",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "credit_report": (_TRADELINES_LIST, _PUBLIC_RECORDS_LIST, _INQUIRIES_LIST,),

# Count cross-check(s) (guide §8):
# Count cross-check (guide §8, LP-434): the model's own declared tradeline_count vs the
# actual number of tradelines rows. A mismatch means rows were dropped or summarised
# WITHOUT the API truncating (the truncation guard cannot see this) → never succeed.
declared = data.tradeline_count.value
actual = len(data.tradelines)
if declared is not None and declared != actual:
    status = ExtractionStatus.PARTIAL

# Count cross-check (guide §8, LP-434): the model's own declared public_record_count vs the
# actual number of public_records rows. A mismatch means rows were dropped or summarised
# WITHOUT the API truncating (the truncation guard cannot see this) → never succeed.
declared = data.public_record_count.value
actual = len(data.public_records)
if declared is not None and declared != actual:
    status = ExtractionStatus.PARTIAL


### 006-appraisal (appraisal) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.appraisal import extract_appraisal
# ... and inside the EXTRACTORS dict:
    "appraisal": extract_appraisal,

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_COMPARABLE_SALES_LIST = ListSpec(
    name="comparable_sales",
    fields=("comp_number", "address", "sale_price", "sale_date", "gross_living_area", "distance_from_subject", "net_adjustment", "adjusted_value",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "appraisal": (_COMPARABLE_SALES_LIST,),

# Count cross-check(s) (guide §8):
# Count cross-check (guide §8, LP-434): the model's own declared comparable_count vs the
# actual number of comparable_sales rows. A mismatch means rows were dropped or summarised
# WITHOUT the API truncating (the truncation guard cannot see this) → never succeed.
declared = data.comparable_count.value
actual = len(data.comparable_sales)
if declared is not None and declared != actual:
    status = ExtractionStatus.PARTIAL


### 007-pay-stub — DIFF REPORT (app/ai/extraction/pay_stub.py)
# Diff-mode report — pay_stub (existing: app/ai/extraction/pay_stub.py)
#
# A shipping extractor exists. This is a REPORT of what the spec adds, NOT a patch
# (guide §6 / D6). Apply the ADD items by hand; each BLOCKED item is its own ticket.

## Typed-core additions (6)
- ADD      employer_address: TypedField[str] / coerce_str
- ADD      employee_address: TypedField[str] / coerce_str
- ADD      employee_ssn_masked: TypedField[str] / coerce_str + _PII_FIELDS[SSN, pre_masked=True]
- ADD      position_or_title: TypedField[str] / coerce_str
- ADD      employment_start_date: TypedField[date] / coerce_date
- ADD      total_deductions_current: TypedField[Decimal] / coerce_decimal

## Nested lists (2) — GENERIC (LP-437): a declaration, not ~5 files
- ADD      earnings_lines: 5 row fields (+ a per-rule consumer — enumerator or derived recipe — as separate follow-up)
- ADD      deduction_lines: 4 row fields (+ a per-rule consumer — enumerator or derived recipe — as separate follow-up)

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_EARNINGS_LINES_LIST = ListSpec(
    name="earnings_lines",
    fields=("earning_type", "hours", "rate", "current_amount", "ytd_amount",),
)

_DEDUCTION_LINES_LIST = ListSpec(
    name="deduction_lines",
    fields=("label", "category", "current_amount", "ytd_amount",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "pay_stub": (_EARNINGS_LINES_LIST, _DEDUCTION_LINES_LIST,),


### 008-w2 — DIFF REPORT (app/ai/extraction/w2.py)
# Diff-mode report — w2 (existing: app/ai/extraction/w2.py)
#
# A shipping extractor exists. This is a REPORT of what the spec adds, NOT a patch
# (guide §6 / D6). Apply the ADD items by hand; each BLOCKED item is its own ticket.

## Typed-core additions (5)
- ADD      employer_address: TypedField[str] / coerce_str
- ADD      employee_address: TypedField[str] / coerce_str
- ADD      retirement_plan_checked: TypedField[str] / coerce_str
- ADD      statutory_employee_checked: TypedField[str] / coerce_str
- ADD      is_corrected_w2: TypedField[str] / coerce_str


### 009-condo-questionnaire (condo_questionnaire) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.condo_questionnaire import extract_condo_questionnaire
# ... and inside the EXTRACTORS dict:
    "condo_questionnaire": extract_condo_questionnaire,


### 010-aus-findings (aus_findings) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.aus_findings import extract_aus_findings
# ... and inside the EXTRACTORS dict:
    "aus_findings": extract_aus_findings,

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_AUS_REQUIRED_CONDITIONS_LIST = ListSpec(
    name="aus_required_conditions",
    fields=("condition_number", "condition_category", "condition_text", "is_prior_to_close",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "aus_findings": (_AUS_REQUIRED_CONDITIONS_LIST,),

# Count cross-check(s) (guide §8):
# Count cross-check (guide §8, LP-434): the model's own declared condition_count vs the
# actual number of aus_required_conditions rows. A mismatch means rows were dropped or summarised
# WITHOUT the API truncating (the truncation guard cannot see this) → never succeed.
declared = data.condition_count.value
actual = len(data.aus_required_conditions)
if declared is not None and declared != actual:
    status = ExtractionStatus.PARTIAL


### 011-homeowner-s-insurance — DIFF REPORT (app/ai/extraction/homeowners_insurance.py)
# Diff-mode report — homeowners_insurance (existing: app/ai/extraction/homeowners_insurance.py)
#
# A shipping extractor exists. This is a REPORT of what the spec adds, NOT a patch
# (guide §6 / D6). Apply the ADD items by hand; each BLOCKED item is its own ticket.

## Typed-core additions (13)
- ADD      named_insured_2: TypedField[str] / coerce_str
- ADD      named_insured_raw: TypedField[str] / coerce_str
- ADD      agency_producer_name: TypedField[str] / coerce_str
- ADD      policy_form: TypedField[str] / coerce_str
- ADD      policy_status: TypedField[str] / coerce_str
- ADD      replacement_cost_or_coinsurance_basis: TypedField[str] / coerce_str
- ADD      wind_hail_hurricane_coverage: TypedField[str] / coerce_str
- ADD      wind_hail_deductible: TypedField[str] / coerce_str
- ADD      premium_paid_or_due_status: TypedField[str] / coerce_str
- ADD      mortgagee_name: TypedField[str] / coerce_str
- ADD      mortgagee_clause_raw: TypedField[str] / coerce_str
- ADD      mortgagee_count: TypedField[int] / coerce_int
- ADD      document_issue_date: TypedField[date] / coerce_date

## Nested lists (1) — GENERIC (LP-437): a declaration, not ~5 files
- ADD      forms_and_endorsements: 2 row fields (+ a per-rule consumer — enumerator or derived recipe — as separate follow-up)

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_FORMS_AND_ENDORSEMENTS_LIST = ListSpec(
    name="forms_and_endorsements",
    fields=("code_or_label", "description",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "homeowners_insurance": (_FORMS_AND_ENDORSEMENTS_LIST,),


### 012-prior-closing-disclosure-final-cd-from-purchase (prior_closing_disclosure_final_cd_from_purchase) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.prior_closing_disclosure_final_cd_from_purchase import extract_prior_closing_disclosure_final_cd_from_purchase
# ... and inside the EXTRACTORS dict:
    "prior_closing_disclosure_final_cd_from_purchase": extract_prior_closing_disclosure_final_cd_from_purchase,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "loan_number": (PiiKind.ACCOUNT, True),

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_CLOSING_COST_LINE_ITEMS_LIST = ListSpec(
    name="closing_cost_line_items",
    fields=("label", "section", "amount", "paid_by",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "prior_closing_disclosure_final_cd_from_purchase": (_CLOSING_COST_LINE_ITEMS_LIST,),


### 013-1040-individual-federal-tax-returns — DIFF REPORT (app/ai/extraction/tax_return.py)
# Diff-mode report — tax_return (existing: app/ai/extraction/tax_return.py)
#
# A shipping extractor exists. This is a REPORT of what the spec adds, NOT a patch
# (guide §6 / D6). Apply the ADD items by hand; each BLOCKED item is its own ticket.

## Typed-core additions (14)
- ADD      amended_return_indicator: TypedField[str] / coerce_str
- ADD      spouse_name: TypedField[str] / coerce_str
- ADD      spouse_ssn_masked: TypedField[str] / coerce_str + _PII_FIELDS[SSN, pre_masked=True]
- ADD      home_address: TypedField[str] / coerce_str
- ADD      wages_salaries_tips: TypedField[Decimal] / coerce_decimal
- ADD      business_income_or_loss: TypedField[Decimal] / coerce_decimal
- ADD      total_net_rental_income: TypedField[Decimal] / coerce_decimal
- ADD      standard_or_itemized_deduction: TypedField[Decimal] / coerce_decimal
- ADD      total_tax: TypedField[Decimal] / coerce_decimal
- ADD      federal_income_tax_withheld: TypedField[Decimal] / coerce_decimal
- ADD      total_payments: TypedField[Decimal] / coerce_decimal
- ADD      attached_schedules_and_forms: TypedField[str] / coerce_str
- ADD      return_signed_date: TypedField[date] / coerce_date
- ADD      signatures_present: TypedField[str] / coerce_str

## Nested lists (1) — GENERIC (LP-437): a declaration, not ~5 files
- ADD      schedule_c: 8 row fields (+ a per-rule consumer — enumerator or derived recipe — as separate follow-up)

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_SCHEDULE_C_LIST = ListSpec(
    name="schedule_c",
    fields=("business_name", "gross_receipts", "total_expenses", "net_profit", "depreciation", "depletion", "amortization", "business_use_of_home",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "tax_return": (_SCHEDULE_C_LIST,),


### 014-drivers-license — DIFF REPORT (app/ai/extraction/drivers_license.py)
# Diff-mode report — drivers_license (existing: app/ai/extraction/drivers_license.py)
#
# A shipping extractor exists. This is a REPORT of what the spec adds, NOT a patch
# (guide §6 / D6). Apply the ADD items by hand; each BLOCKED item is its own ticket.

## Typed-core additions (7)
- ADD      credential_type: TypedField[str] / coerce_str
- ADD      family_name: TypedField[str] / coerce_str
- ADD      given_names: TypedField[str] / coerce_str
- ADD      middle_name: TypedField[str] / coerce_str
- ADD      suffix: TypedField[str] / coerce_str
- ADD      issue_date: TypedField[date] / coerce_date
- ADD      photo_present: TypedField[str] / coerce_str


### 015-written-voe — DIFF REPORT (app/ai/extraction/voe.py)
# Diff-mode report — voe (existing: app/ai/extraction/voe.py)
#
# A shipping extractor exists. This is a REPORT of what the spec adds, NOT a patch
# (guide §6 / D6). Apply the ADD items by hand; each BLOCKED item is its own ticket.

## Typed-core additions (14)
- ADD      issuer_name: TypedField[str] / coerce_str
- ADD      document_issue_date: TypedField[date] / coerce_date
- ADD      employer_address: TypedField[str] / coerce_str
- ADD      lender_name: TypedField[str] / coerce_str
- ADD      applicant_address: TypedField[str] / coerce_str
- ADD      employee_number: TypedField[str] / coerce_str + _PII_FIELDS[ACCOUNT, pre_masked=False]
- ADD      previous_employment_hire_date: TypedField[date] / coerce_date
- ADD      position_held: TypedField[str] / coerce_str
- ADD      employer_signer_name: TypedField[str] / coerce_str
- ADD      employer_signer_title: TypedField[str] / coerce_str
- ADD      employer_signer_phone: TypedField[str] / coerce_str
- ADD      employer_signature_and_date: TypedField[date] / coerce_date
- ADD      direct_return_to_lender_indicator: TypedField[str] / coerce_str
- ADD      applicant_authorization_signature: TypedField[str] / coerce_str

## Nested lists (1) — GENERIC (LP-437): a declaration, not ~5 files
- ADD      gross_earnings_history: 5 row fields (+ a per-rule consumer — enumerator or derived recipe — as separate follow-up)

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_GROSS_EARNINGS_HISTORY_LIST = ListSpec(
    name="gross_earnings_history",
    fields=("period", "base", "overtime", "commission", "bonus",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "voe": (_GROSS_EARNINGS_HISTORY_LIST,),


### 016-hoa-dues-statement-with-contact-info — DIFF REPORT (app/ai/extraction/hoa_statement.py)
# Diff-mode report — hoa_statement (existing: app/ai/extraction/hoa_statement.py)
#
# A shipping extractor exists. This is a REPORT of what the spec adds, NOT a patch
# (guide §6 / D6). Apply the ADD items by hand; each BLOCKED item is its own ticket.

## Typed-core additions (12)
- ADD      issuer_name: TypedField[str] / coerce_str
- ADD      management_company: TypedField[str] / coerce_str
- ADD      association_contact_phone: TypedField[str] / coerce_str
- ADD      association_contact_email_or_url: TypedField[str] / coerce_str
- ADD      association_contact_address: TypedField[str] / coerce_str
- ADD      unit_owner_name_2: TypedField[str] / coerce_str
- ADD      owner_account_number_masked: TypedField[str] / coerce_str + _PII_FIELDS[ACCOUNT, pre_masked=True]
- ADD      statement_date: TypedField[date] / coerce_date
- ADD      past_due_amount: TypedField[Decimal] / coerce_decimal
- ADD      paid_current_indicator: TypedField[str] / coerce_str
- ADD      collection_or_lien_status: TypedField[str] / coerce_str
- ADD      reserve_percentage: TypedField[str] / coerce_str

## Nested lists (1) — GENERIC (LP-437): a declaration, not ~5 files
- ADD      special_assessment_items: 3 row fields (+ a per-rule consumer — enumerator or derived recipe — as separate follow-up)

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_SPECIAL_ASSESSMENT_ITEMS_LIST = ListSpec(
    name="special_assessment_items",
    fields=("description", "amount", "duration",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "hoa_statement": (_SPECIAL_ASSESSMENT_ITEMS_LIST,),


### 017-investment-account-statements — DIFF REPORT (app/ai/extraction/investment_account.py)
# Diff-mode report — investment_account (existing: app/ai/extraction/investment_account.py)
#
# A shipping extractor exists. This is a REPORT of what the spec adds, NOT a patch
# (guide §6 / D6). Apply the ADD items by hand; each BLOCKED item is its own ticket.

## Typed-core additions (13)
- ADD      brokerage_or_custodian_name: TypedField[str] / coerce_str
- ADD      document_title: TypedField[str] / coerce_str
- ADD      account_registration_names_raw: TypedField[str] / coerce_str
- ADD      account_owner_name_2: TypedField[str] / coerce_str
- ADD      account_owner_count: TypedField[int] / coerce_int
- ADD      statement_date: TypedField[date] / coerce_date
- ADD      cash_and_cash_equivalents: TypedField[Decimal] / coerce_decimal
- ADD      securities_market_value: TypedField[Decimal] / coerce_decimal
- ADD      margin_or_securities_backed_loan_balance: TypedField[Decimal] / coerce_decimal
- ADD      net_liquidation_value: TypedField[Decimal] / coerce_decimal
- ADD      vested_or_available_value: TypedField[Decimal] / coerce_decimal
- ADD      liquidation_restrictions: TypedField[str] / coerce_str
- ADD      document_status_or_version: TypedField[str] / coerce_str

## Nested lists (1) — GENERIC (LP-437): a declaration, not ~5 files
- ADD      security_positions: 6 row fields (+ a per-rule consumer — enumerator or derived recipe — as separate follow-up)

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_SECURITY_POSITIONS_LIST = ListSpec(
    name="security_positions",
    fields=("description", "ticker_or_cusip", "quantity", "market_value", "asset_class", "source",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "investment_account": (_SECURITY_POSITIONS_LIST,),


### 018-ira-401k (ira_401k) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.ira_401k import extract_ira_401k
# ... and inside the EXTRACTORS dict:
    "ira_401k": extract_ira_401k,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "account_number_masked": (PiiKind.ACCOUNT, True),


### 019-letter-of-explanation-credit — DIFF REPORT (app/ai/extraction/letter_of_explanation.py)
# Diff-mode report — letter_of_explanation (existing: app/ai/extraction/letter_of_explanation.py)
#
# A shipping extractor exists. This is a REPORT of what the spec adds, NOT a patch
# (guide §6 / D6). Apply the ADD items by hand; each BLOCKED item is its own ticket.

## Typed-core additions (13)
- ADD      borrower_name: TypedField[str] / coerce_str
- ADD      borrower_name_2: TypedField[str] / coerce_str
- ADD      creditor_or_inquiry_company: TypedField[str] / coerce_str
- ADD      account_number_last4: TypedField[str] / coerce_str + _PII_FIELDS[ACCOUNT, pre_masked=True]
- ADD      credit_report_bureau_or_reference: TypedField[str] / coerce_str
- ADD      new_debt_resulted_from_inquiry: TypedField[str] / coerce_str
- ADD      one_time_or_recurring_indicator: TypedField[str] / coerce_str
- ADD      resolution_or_payoff_action: TypedField[str] / coerce_str
- ADD      current_account_orissue_status: TypedField[str] / coerce_str
- ADD      supporting_documents: TypedField[str] / coerce_str
- ADD      borrower_certification: TypedField[str] / coerce_str
- ADD      borrower_signature_present: TypedField[str] / coerce_str
- ADD      borrower_signature_date: TypedField[date] / coerce_date


### 020-mortgage-statement — DIFF REPORT (app/ai/extraction/mortgage_statement.py)
# Diff-mode report — mortgage_statement (existing: app/ai/extraction/mortgage_statement.py)
#
# A shipping extractor exists. This is a REPORT of what the spec adds, NOT a patch
# (guide §6 / D6). Apply the ADD items by hand; each BLOCKED item is its own ticket.

## Typed-core additions (12)
- ADD      borrower_name_2: TypedField[str] / coerce_str
- ADD      loan_number_masked: TypedField[str] / coerce_str + _PII_FIELDS[ACCOUNT, pre_masked=True]
- ADD      statement_date: TypedField[date] / coerce_date
- ADD      billing_cycle_or_period: TypedField[str] / coerce_str
- ADD      principal_amount: TypedField[Decimal] / coerce_decimal
- ADD      interest_amount: TypedField[Decimal] / coerce_decimal
- ADD      interest_rate: TypedField[str] / coerce_str
- ADD      escrow_balance: TypedField[Decimal] / coerce_decimal
- ADD      past_due_amount: TypedField[Decimal] / coerce_decimal
- ADD      maturity_date: TypedField[date] / coerce_date
- ADD      delinquency_status: TypedField[str] / coerce_str
- ADD      loss_mitigation_or_bankruptcy_messages: TypedField[str] / coerce_str


### 021-rental-agreements-lease-agreements (rental_agreements_lease_agreements) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.rental_agreements_lease_agreements import extract_rental_agreements_lease_agreements
# ... and inside the EXTRACTORS dict:
    "rental_agreements_lease_agreements": extract_rental_agreements_lease_agreements,


### 022-retiree-account-statement — DIFF REPORT (app/ai/extraction/retirement_account.py)
# Diff-mode report — retirement_account (existing: app/ai/extraction/retirement_account.py)
#
# A shipping extractor exists. This is a REPORT of what the spec adds, NOT a patch
# (guide §6 / D6). Apply the ADD items by hand; each BLOCKED item is its own ticket.

## Typed-core additions (15)
- ADD      retiree_or_account_owner_name_2: TypedField[str] / coerce_str
- ADD      statement_date: TypedField[date] / coerce_date
- ADD      vested_percentage: TypedField[Decimal] / coerce_decimal
- ADD      beginning_balance: TypedField[Decimal] / coerce_decimal
- ADD      remaining_available_balance: TypedField[Decimal] / coerce_decimal
- ADD      outstanding_loan_balance: TypedField[Decimal] / coerce_decimal
- ADD      withdrawal_or_liquidation_terms: TypedField[str] / coerce_str
- ADD      gross_distribution_amount: TypedField[Decimal] / coerce_decimal
- ADD      net_distribution_amount: TypedField[Decimal] / coerce_decimal
- ADD      distribution_frequency: TypedField[str] / coerce_str
- ADD      distribution_date_or_schedule: TypedField[str] / coerce_str
- ADD      year_to_date_distributions: TypedField[Decimal] / coerce_decimal
- ADD      required_minimum_distribution_indicator: TypedField[str] / coerce_str
- ADD      fixed_period_or_lifetime_indicator: TypedField[str] / coerce_str
- ADD      scheduled_end_date: TypedField[date] / coerce_date


### 023-employment-offer-letter (employment_offer_letter) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.employment_offer_letter import extract_employment_offer_letter
# ... and inside the EXTRACTORS dict:
    "employment_offer_letter": extract_employment_offer_letter,

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_EMPLOYMENT_CONTINGENCIES_LIST = ListSpec(
    name="employment_contingencies",
    fields=("contingency",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "employment_offer_letter": (_EMPLOYMENT_CONTINGENCIES_LIST,),


### 024-flood-certification (flood_certification) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.flood_certification import extract_flood_certification
# ... and inside the EXTRACTORS dict:
    "flood_certification": extract_flood_certification,


### 025-gift-letter — DIFF REPORT (app/ai/extraction/gift_letter.py)
# Diff-mode report — gift_letter (existing: app/ai/extraction/gift_letter.py)
#
# A shipping extractor exists. This is a REPORT of what the spec adds, NOT a patch
# (guide §6 / D6). Apply the ADD items by hand; each BLOCKED item is its own ticket.

## Typed-core additions (18)
- ADD      issuer_name: TypedField[str] / coerce_str
- ADD      donor_names_raw: TypedField[str] / coerce_str
- ADD      donor_name_2: TypedField[str] / coerce_str
- ADD      donor_address: TypedField[str] / coerce_str
- ADD      donor_phone: TypedField[str] / coerce_str
- ADD      borrower_recipient_name_2: TypedField[str] / coerce_str
- ADD      gift_date_or_expected_transfer_date: TypedField[date] / coerce_date
- ADD      funds_already_transferred: TypedField[str] / coerce_str
- ADD      transfer_method: TypedField[str] / coerce_str
- ADD      gift_source_account_institution: TypedField[str] / coerce_str
- ADD      gift_source_account_last4: TypedField[str] / coerce_str + _PII_FIELDS[ACCOUNT, pre_masked=True]
- ADD      recipient_or_escrow_account_last4: TypedField[str] / coerce_str + _PII_FIELDS[ACCOUNT, pre_masked=True]
- ADD      gift_purpose: TypedField[str] / coerce_str
- ADD      no_ownership_or_lien_interest_statement: TypedField[str] / coerce_str
- ADD      lender_name: TypedField[str] / coerce_str
- ADD      document_issue_date: TypedField[date] / coerce_date
- ADD      donor_signature_present: TypedField[str] / coerce_str
- ADD      donor_signature_date: TypedField[date] / coerce_date


### 026-mortgage-payoff (mortgage_payoff) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.mortgage_payoff import extract_mortgage_payoff
# ... and inside the EXTRACTORS dict:
    "mortgage_payoff": extract_mortgage_payoff,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "loan_number_masked": (PiiKind.ACCOUNT, True),
    "wire_or_remittance_instructions": (PiiKind.ACCOUNT, False),

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_PAYOFF_CONDITIONS_ORLIMITATIONS_LIST = ListSpec(
    name="payoff_conditions_orlimitations",
    fields=("condition", "source",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "mortgage_payoff": (_PAYOFF_CONDITIONS_ORLIMITATIONS_LIST,),


### 027-property-tax-bill-subject — DIFF REPORT (app/ai/extraction/property_tax_bill.py)
# Diff-mode report — property_tax_bill (existing: app/ai/extraction/property_tax_bill.py)
#
# A shipping extractor exists. This is a REPORT of what the spec adds, NOT a patch
# (guide §6 / D6). Apply the ADD items by hand; each BLOCKED item is its own ticket.

## Typed-core additions (14)
- ADD      issuer_name: TypedField[str] / coerce_str
- ADD      taxpayer_or_owner_names_raw: TypedField[str] / coerce_str
- ADD      taxpayer_or_owner_name_2: TypedField[str] / coerce_str
- ADD      parcel_or_apn: TypedField[str] / coerce_str
- ADD      tax_bill_or_account_number: TypedField[str] / coerce_str
- ADD      tax_year: TypedField[int] / coerce_int
- ADD      assessment_period: TypedField[str] / coerce_str
- ADD      assessed_land_value: TypedField[Decimal] / coerce_decimal
- ADD      assessed_improvement_value: TypedField[Decimal] / coerce_decimal
- ADD      taxable_value: TypedField[Decimal] / coerce_decimal
- ADD      base_tax_amount: TypedField[Decimal] / coerce_decimal
- ADD      current_balance: TypedField[Decimal] / coerce_decimal
- ADD      penalties_and_interest: TypedField[Decimal] / coerce_decimal
- ADD      delinquent_or_lien_status: TypedField[str] / coerce_str

## Nested lists (1) — GENERIC (LP-437): a declaration, not ~5 files
- ADD      installments_and_due_dates: 6 row fields (+ a per-rule consumer — enumerator or derived recipe — as separate follow-up)

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_INSTALLMENTS_AND_DUE_DATES_LIST = ListSpec(
    name="installments_and_due_dates",
    fields=("installment_label", "amount", "due_date", "paid_status", "paid_date", "source",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "property_tax_bill": (_INSTALLMENTS_AND_DUE_DATES_LIST,),


### 028-subject-property-note (subject_property_note) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.subject_property_note import extract_subject_property_note
# ... and inside the EXTRACTORS dict:
    "subject_property_note": extract_subject_property_note,


### 029-1099-form — DIFF REPORT (app/ai/extraction/form_1099.py)
# Diff-mode report — form_1099 (existing: app/ai/extraction/form_1099.py)
#
# A shipping extractor exists. This is a REPORT of what the spec adds, NOT a patch
# (guide §6 / D6). Apply the ADD items by hand; each BLOCKED item is its own ticket.

## Typed-core additions (7)
- ADD      corrected_indicator: TypedField[str] / coerce_str
- ADD      payer_address: TypedField[str] / coerce_str
- ADD      recipient_address: TypedField[str] / coerce_str
- ADD      distribution_code: TypedField[str] / coerce_str
- ADD      taxable_amount_not_determined: TypedField[str] / coerce_str
- ADD      account_number: TypedField[str] / coerce_str + _PII_FIELDS[ACCOUNT, pre_masked=False]
- ADD      second_tin_notice: TypedField[str] / coerce_str


### 030-business-license (business_license) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.business_license import extract_business_license
# ... and inside the EXTRACTORS dict:
    "business_license": extract_business_license,


### 031-court-order-documents (court_order_documents) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.court_order_documents import extract_court_order_documents
# ... and inside the EXTRACTORS dict:
    "court_order_documents": extract_court_order_documents,

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_SUPPORT_AWARDS_LIST = ListSpec(
    name="support_awards",
    fields=("award_type", "amount", "frequency", "start_date", "end_date", "payer", "payee", "escalation_or_conditions", "source",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "court_order_documents": (_SUPPORT_AWARDS_LIST,),


### 032-cpa-letter (cpa_letter) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.cpa_letter import extract_cpa_letter
# ... and inside the EXTRACTORS dict:
    "cpa_letter": extract_cpa_letter,


### 033-emd-withdrawal-proof (emd_withdrawal_proof) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.emd_withdrawal_proof import extract_emd_withdrawal_proof
# ... and inside the EXTRACTORS dict:
    "emd_withdrawal_proof": extract_emd_withdrawal_proof,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "account_number_masked": (PiiKind.ACCOUNT, True),
    "wire_ach_trace_number": (PiiKind.ACCOUNT, False),


### 034-flood-insurance (flood_insurance) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.flood_insurance import extract_flood_insurance
# ... and inside the EXTRACTORS dict:
    "flood_insurance": extract_flood_insurance,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "policy_number": (PiiKind.ACCOUNT, False),

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_MORTGAGEE_CLAUSE_ENTRIES_LIST = ListSpec(
    name="mortgagee_clause_entries",
    fields=("mortgagee_name", "mortgagee_address", "loan_number", "capacity", "source",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "flood_insurance": (_MORTGAGEE_CLAUSE_ENTRIES_LIST,),


### 035-k-1-schedule-1065-1120s (k_1_schedule_1065_1120s) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.k_1_schedule_1065_1120s import extract_k_1_schedule_1065_1120s
# ... and inside the EXTRACTORS dict:
    "k_1_schedule_1065_1120s": extract_k_1_schedule_1065_1120s,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "entity_ein": (PiiKind.ACCOUNT, False),
    "partner_or_shareholder_tin": (PiiKind.SSN, False),

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_K1_BOX_ITEMS_LIST = ListSpec(
    name="k1_box_items",
    fields=("box_number", "box_label", "amount", "code", "source",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "k_1_schedule_1065_1120s": (_K1_BOX_ITEMS_LIST,),


### 036-master-insurance-policy-for-condominium (master_insurance_policy_for_condominium) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.master_insurance_policy_for_condominium import extract_master_insurance_policy_for_condominium
# ... and inside the EXTRACTORS dict:
    "master_insurance_policy_for_condominium": extract_master_insurance_policy_for_condominium,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "policy_number": (PiiKind.ACCOUNT, False),

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_BUILDING_LIMITS_LIST = ListSpec(
    name="building_limits",
    fields=("building_identifier_or_address", "coverage_limit", "deductible", "wind_hail_named_storm_deductible", "source",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "master_insurance_policy_for_condominium": (_BUILDING_LIMITS_LIST,),


### 037-profit-and-loss-statement-balance-sheet — DIFF REPORT (app/ai/extraction/profit_and_loss.py)
# Diff-mode report — profit_and_loss (existing: app/ai/extraction/profit_and_loss.py)
#
# A shipping extractor exists. This is a REPORT of what the spec adds, NOT a patch
# (guide §6 / D6). Apply the ADD items by hand; each BLOCKED item is its own ticket.

## Typed-core additions (16)
- ADD      issuer_name: TypedField[str] / coerce_str
- ADD      statement_type: TypedField[str] / coerce_str
- ADD      accounting_basis: TypedField[str] / coerce_str
- ADD      prepared_by: TypedField[str] / coerce_str
- ADD      preparer_relationship: TypedField[str] / coerce_str
- ADD      cpa_review_compilation_or_audit_level: TypedField[str] / coerce_str
- ADD      total_cost_of_goods_sold: TypedField[Decimal] / coerce_decimal
- ADD      gross_profit: TypedField[Decimal] / coerce_decimal
- ADD      operating_income: TypedField[Decimal] / coerce_decimal
- ADD      total_assets: TypedField[Decimal] / coerce_decimal
- ADD      cash_and_cash_equivalents: TypedField[Decimal] / coerce_decimal
- ADD      total_liabilities: TypedField[Decimal] / coerce_decimal
- ADD      owner_or_shareholder_equity: TypedField[Decimal] / coerce_decimal
- ADD      management_certification: TypedField[str] / coerce_str
- ADD      signer_name_title: TypedField[str] / coerce_str
- ADD      signature_and_date: TypedField[str] / coerce_str

## Nested lists (1) — GENERIC (LP-437): a declaration, not ~5 files
- ADD      financial_line_items: 4 row fields (+ a per-rule consumer — enumerator or derived recipe — as separate follow-up)

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_FINANCIAL_LINE_ITEMS_LIST = ListSpec(
    name="financial_line_items",
    fields=("section", "label", "amount", "source",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "profit_and_loss": (_FINANCIAL_LINE_ITEMS_LIST,),


### 038-resident-alien-card (resident_alien_card) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.resident_alien_card import extract_resident_alien_card
# ... and inside the EXTRACTORS dict:
    "resident_alien_card": extract_resident_alien_card,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "uscis_number_or_a_number": (PiiKind.ACCOUNT, False),
    "card_number": (PiiKind.ACCOUNT, False),


### 039-social-security-award-letter (social_security_award_letter) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.social_security_award_letter import extract_social_security_award_letter
# ... and inside the EXTRACTORS dict:
    "social_security_award_letter": extract_social_security_award_letter,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "claim_number_masked": (PiiKind.ACCOUNT, True),

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_MEDICARE_OR_OTHER_DEDUCTIONS_LIST = ListSpec(
    name="medicare_or_other_deductions",
    fields=("label", "amount", "source",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "social_security_award_letter": (_MEDICARE_OR_OTHER_DEDUCTIONS_LIST,),


### 044-aba (aba) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.aba import extract_aba
# ... and inside the EXTRACTORS dict:
    "aba": extract_aba,

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_AFFILIATE_ENTRIES_LIST = ListSpec(
    name="affiliate_entries",
    fields=("provider_name", "service_type", "nature_of_relationship", "estimated_charge_or_range", "source",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "aba": (_AFFILIATE_ENTRIES_LIST,),


### 045-alimony-income-verification (alimony_income_verification) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.alimony_income_verification import extract_alimony_income_verification
# ... and inside the EXTRACTORS dict:
    "alimony_income_verification": extract_alimony_income_verification,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "deposit_account_last4": (PiiKind.ACCOUNT, True),

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_PAYMENT_HISTORY_LIST = ListSpec(
    name="payment_history",
    fields=("date", "amount", "status", "source",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "alimony_income_verification": (_PAYMENT_HISTORY_LIST,),


### 046-application-loe (application_loe) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.application_loe import extract_application_loe
# ... and inside the EXTRACTORS dict:
    "application_loe": extract_application_loe,

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_EVENT_CHRONOLOGY_LIST = ListSpec(
    name="event_chronology",
    fields=("date", "event", "source",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "application_loe": (_EVENT_CHRONOLOGY_LIST,),


### 047-appraisal-payment (appraisal_payment) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.appraisal_payment import extract_appraisal_payment
# ... and inside the EXTRACTORS dict:
    "appraisal_payment": extract_appraisal_payment,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "card_or_account_last4": (PiiKind.ACCOUNT, True),
    "check_number_or_transaction_reference": (PiiKind.ACCOUNT, False),


### 048-authorization-to-run-credit (authorization_to_run_credit) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.authorization_to_run_credit import extract_authorization_to_run_credit
# ... and inside the EXTRACTORS dict:
    "authorization_to_run_credit": extract_authorization_to_run_credit,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "borrower_ssn_or_itin": (PiiKind.SSN, False),
    "borrower_ssn_or_itin_2": (PiiKind.SSN, False),


### 049-bank-deposit-slip (bank_deposit_slip) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.bank_deposit_slip import extract_bank_deposit_slip
# ... and inside the EXTRACTORS dict:
    "bank_deposit_slip": extract_bank_deposit_slip,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "account_number_masked": (PiiKind.ACCOUNT, True),

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_CHECK_ITEMS_LIST = ListSpec(
    name="check_items",
    fields=("payer_or_drawer", "amount", "check_number", "source",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "bank_deposit_slip": (_CHECK_ITEMS_LIST,),


### 050-bankruptcy-discharge-notice (bankruptcy_discharge_notice) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.bankruptcy_discharge_notice import extract_bankruptcy_discharge_notice
# ... and inside the EXTRACTORS dict:
    "bankruptcy_discharge_notice": extract_bankruptcy_discharge_notice,


### 051-bankruptcy-filing (bankruptcy_filing) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.bankruptcy_filing import extract_bankruptcy_filing
# ... and inside the EXTRACTORS dict:
    "bankruptcy_filing": extract_bankruptcy_filing,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "ssn_or_itin_last4": (PiiKind.SSN, True),
    "ssn_or_itin_last4_2": (PiiKind.SSN, True),


### 052-birth-certificate (birth_certificate) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.birth_certificate import extract_birth_certificate
# ... and inside the EXTRACTORS dict:
    "birth_certificate": extract_birth_certificate,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "certificate_or_state_file_number": (PiiKind.ACCOUNT, False),
    "local_file_or_registration_number": (PiiKind.ACCOUNT, False),


### 053-boarder-proof-of-residency (boarder_proof_of_residency) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.boarder_proof_of_residency import extract_boarder_proof_of_residency
# ... and inside the EXTRACTORS dict:
    "boarder_proof_of_residency": extract_boarder_proof_of_residency,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "account_or_reference_number_masked": (PiiKind.ACCOUNT, True),

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_SUPPORTING_DOCUMENTS_LIST = ListSpec(
    name="supporting_documents",
    fields=("document_name",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "boarder_proof_of_residency": (_SUPPORTING_DOCUMENTS_LIST,),


### 054-boarder-rental-payments (boarder_rental_payments) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.boarder_rental_payments import extract_boarder_rental_payments
# ... and inside the EXTRACTORS dict:
    "boarder_rental_payments": extract_boarder_rental_payments,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "recipient_account_last4": (PiiKind.ACCOUNT, True),

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_PAYMENT_HISTORY_LIST = ListSpec(
    name="payment_history",
    fields=("date", "amount", "method", "status",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "boarder_rental_payments": (_PAYMENT_HISTORY_LIST,),


### 055-borrower-authorization-and-certification (borrower_authorization_and_certification) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.borrower_authorization_and_certification import extract_borrower_authorization_and_certification
# ... and inside the EXTRACTORS dict:
    "borrower_authorization_and_certification": extract_borrower_authorization_and_certification,


### 056-borrower-s-authorization-for-counseling (borrower_s_authorization_for_counseling) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.borrower_s_authorization_for_counseling import extract_borrower_s_authorization_for_counseling
# ... and inside the EXTRACTORS dict:
    "borrower_s_authorization_for_counseling": extract_borrower_s_authorization_for_counseling,


### 057-building-permits (building_permits) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.building_permits import extract_building_permits
# ... and inside the EXTRACTORS dict:
    "building_permits": extract_building_permits,

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_INSPECTION_RESULTS_LIST = ListSpec(
    name="inspection_results",
    fields=("type", "date", "result",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "building_permits": (_INSPECTION_RESULTS_LIST,),


### 058-business-existence-verification-cpa-ltr-bus-lic (business_existence_verification_cpa_ltr_bus_lic) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.business_existence_verification_cpa_ltr_bus_lic import extract_business_existence_verification_cpa_ltr_bus_lic
# ... and inside the EXTRACTORS dict:
    "business_existence_verification_cpa_ltr_bus_lic": extract_business_existence_verification_cpa_ltr_bus_lic,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "ein_or_state_entity_number_masked": (PiiKind.ACCOUNT, True),


### 059-business-federal-tax-returns (business_federal_tax_returns) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.business_federal_tax_returns import extract_business_federal_tax_returns
# ... and inside the EXTRACTORS dict:
    "business_federal_tax_returns": extract_business_federal_tax_returns,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "ein": (PiiKind.ACCOUNT, False),

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_OWNER_PARTNER_SHAREHOLDER_RECORDS_LIST = ListSpec(
    name="owner_partner_shareholder_records",
    fields=("owner_name", "ownership_percentage", "distribution_or_k1_share",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "business_federal_tax_returns": (_OWNER_PARTNER_SHAREHOLDER_RECORDS_LIST,),


### 060-cancelled-checks-evidencing-receipt-of-note-income (cancelled_checks_evidencing_receipt_of_note_income) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.cancelled_checks_evidencing_receipt_of_note_income import extract_cancelled_checks_evidencing_receipt_of_note_income
# ... and inside the EXTRACTORS dict:
    "cancelled_checks_evidencing_receipt_of_note_income": extract_cancelled_checks_evidencing_receipt_of_note_income,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "drawer_account_last4": (PiiKind.ACCOUNT, True),
    "deposit_account_last4": (PiiKind.ACCOUNT, True),


### 061-certificate-of-eligibility (certificate_of_eligibility) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.certificate_of_eligibility import extract_certificate_of_eligibility
# ... and inside the EXTRACTORS dict:
    "certificate_of_eligibility": extract_certificate_of_eligibility,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "social_security_number_masked": (PiiKind.SSN, True),

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_PRIOR_VA_LOAN_OR_ENTITLEMENT_CHARGES_LIST = ListSpec(
    name="prior_va_loan_or_entitlement_charges",
    fields=("prior_loan_reference", "entitlement_amount_charged", "prior_loan_status",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "certificate_of_eligibility": (_PRIOR_VA_LOAN_OR_ENTITLEMENT_CHARGES_LIST,),


### 062-consent-to-use-electronic-records-and-signatures (consent_to_use_electronic_records_and_signatures) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.consent_to_use_electronic_records_and_signatures import extract_consent_to_use_electronic_records_and_signatures
# ... and inside the EXTRACTORS dict:
    "consent_to_use_electronic_records_and_signatures": extract_consent_to_use_electronic_records_and_signatures,


### 063-credit-card-authorization (credit_card_authorization) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.credit_card_authorization import extract_credit_card_authorization
# ... and inside the EXTRACTORS dict:
    "credit_card_authorization": extract_credit_card_authorization,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "card_number_last4_or_token": (PiiKind.ACCOUNT, True),
    "expiration_month_year": (PiiKind.ACCOUNT, False),


### 064-custom (custom) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.custom import extract_custom
# ... and inside the EXTRACTORS dict:
    "custom": extract_custom,

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_UNMAPPED_KEY_VALUE_PAIRS_LIST = ListSpec(
    name="unmapped_key_value_pairs",
    fields=("label", "value",),
    redact=frozenset({"value"}),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "custom": (_UNMAPPED_KEY_VALUE_PAIRS_LIST,),


### 065-disability-award-letter (disability_award_letter) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.disability_award_letter import extract_disability_award_letter
# ... and inside the EXTRACTORS dict:
    "disability_award_letter": extract_disability_award_letter,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "claim_or_account_number_masked": (PiiKind.ACCOUNT, True),

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_DEDUCTIONS_OR_OFFSETS_LIST = ListSpec(
    name="deductions_or_offsets",
    fields=("label", "amount", "source",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "disability_award_letter": (_DEDUCTIONS_OR_OFFSETS_LIST,),


### 066-divorce-decree — DIFF REPORT (app/ai/extraction/divorce_decree.py)
# Diff-mode report — divorce_decree (existing: app/ai/extraction/divorce_decree.py)
#
# A shipping extractor exists. This is a REPORT of what the spec adds, NOT a patch
# (guide §6 / D6). Apply the ADD items by hand; each BLOCKED item is its own ticket.

## Typed-core additions (12)
- ADD      court_name: TypedField[str] / coerce_str
- ADD      court_jurisdiction: TypedField[str] / coerce_str
- ADD      case_number: TypedField[str] / coerce_str
- ADD      decree_final_date: TypedField[date] / coerce_date
- ADD      decree_status: TypedField[str] / coerce_str
- ADD      dissolution_granted_indicator: TypedField[str] / coerce_str
- ADD      marriage_date: TypedField[date] / coerce_date
- ADD      separation_date: TypedField[date] / coerce_date
- ADD      name_change_order: TypedField[str] / coerce_str
- ADD      incorporated_settlement_agreement: TypedField[str] / coerce_str
- ADD      judge_name: TypedField[str] / coerce_str
- ADD      appeal_or_stay_indicator: TypedField[str] / coerce_str

## Nested lists (1) — GENERIC (LP-437): a declaration, not ~5 files
- ADD      support_obligations: 6 row fields (+ a per-rule consumer — enumerator or derived recipe — as separate follow-up)

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_SUPPORT_OBLIGATIONS_LIST = ListSpec(
    name="support_obligations",
    fields=("obligation_type", "amount", "frequency", "payer", "recipient", "source",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "divorce_decree": (_SUPPORT_OBLIGATIONS_LIST,),


### 067-earnest-money-emd-receipt (earnest_money_emd_receipt) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.earnest_money_emd_receipt import extract_earnest_money_emd_receipt
# ... and inside the EXTRACTORS dict:
    "earnest_money_emd_receipt": extract_earnest_money_emd_receipt,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "payer_account_last4": (PiiKind.ACCOUNT, True),


### 068-evidence-of-payment (evidence_of_payment) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.evidence_of_payment import extract_evidence_of_payment
# ... and inside the EXTRACTORS dict:
    "evidence_of_payment": extract_evidence_of_payment,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "account_or_case_number_masked": (PiiKind.ACCOUNT, True),
    "source_account_last4": (PiiKind.ACCOUNT, True),

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_RECURRING_PAYMENT_HISTORY_LIST = ListSpec(
    name="recurring_payment_history",
    fields=("date", "amount", "status", "source",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "evidence_of_payment": (_RECURRING_PAYMENT_HISTORY_LIST,),


### 069-financial-statements (financial_statements) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.financial_statements import extract_financial_statements
# ... and inside the EXTRACTORS dict:
    "financial_statements": extract_financial_statements,

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_ASSET_LINE_ITEMS_LIST = ListSpec(
    name="asset_line_items",
    fields=("category", "description", "value", "source",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "financial_statements": (_ASSET_LINE_ITEMS_LIST,),


### 070-foster-care-verification (foster_care_verification) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.foster_care_verification import extract_foster_care_verification
# ... and inside the EXTRACTORS dict:
    "foster_care_verification": extract_foster_care_verification,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "case_provider_or_account_number_masked": (PiiKind.ACCOUNT, True),

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_PAYMENT_HISTORY_LIST = ListSpec(
    name="payment_history",
    fields=("period", "amount", "date_paid", "source",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "foster_care_verification": (_PAYMENT_HISTORY_LIST,),


### 071-government-issued-id (government_issued_id) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.government_issued_id import extract_government_issued_id
# ... and inside the EXTRACTORS dict:
    "government_issued_id": extract_government_issued_id,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "document_number": (PiiKind.ACCOUNT, True),


### 072-hoa-certification (hoa_certification) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.hoa_certification import extract_hoa_certification
# ... and inside the EXTRACTORS dict:
    "hoa_certification": extract_hoa_certification,

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_SPECIAL_ASSESSMENTS_LIST = ListSpec(
    name="special_assessments",
    fields=("description", "amount", "status", "date",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "hoa_certification": (_SPECIAL_ASSESSMENTS_LIST,),


### 073-homeowner-s-insurance-quote (homeowner_s_insurance_quote) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.homeowner_s_insurance_quote import extract_homeowner_s_insurance_quote
# ... and inside the EXTRACTORS dict:
    "homeowner_s_insurance_quote": extract_homeowner_s_insurance_quote,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "policy_number": (PiiKind.ACCOUNT, True),

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_MORTGAGEE_OR_LIENHOLDER_ENTRIES_LIST = ListSpec(
    name="mortgagee_or_lienholder_entries",
    fields=("lender_name", "loan_number", "clause_address",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "homeowner_s_insurance_quote": (_MORTGAGEE_OR_LIENHOLDER_ENTRIES_LIST,),


### 074-k-1-shareholder-profit-and-loss-transcripts (k_1_shareholder_profit_and_loss_transcripts) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.k_1_shareholder_profit_and_loss_transcripts import extract_k_1_shareholder_profit_and_loss_transcripts
# ... and inside the EXTRACTORS dict:
    "k_1_shareholder_profit_and_loss_transcripts": extract_k_1_shareholder_profit_and_loss_transcripts,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "entity_ein_masked": (PiiKind.ACCOUNT, True),
    "shareholder_or_partner_tin_masked": (PiiKind.SSN, True),

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_TRANSCRIPT_LINE_ITEMS_LIST = ListSpec(
    name="transcript_line_items",
    fields=("line_code", "description", "amount",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "k_1_shareholder_profit_and_loss_transcripts": (_TRANSCRIPT_LINE_ITEMS_LIST,),


### 075-letter-of-explanation-asset (letter_of_explanation_asset) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.letter_of_explanation_asset import extract_letter_of_explanation_asset
# ... and inside the EXTRACTORS dict:
    "letter_of_explanation_asset": extract_letter_of_explanation_asset,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "account_number_last4": (PiiKind.ACCOUNT, True),

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_TRANSFER_PATH_OR_CHRONOLOGY_LIST = ListSpec(
    name="transfer_path_or_chronology",
    fields=("date", "from", "to", "amount",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "letter_of_explanation_asset": (_TRANSFER_PATH_OR_CHRONOLOGY_LIST,),


### 076-letter-of-explanation-child-care (letter_of_explanation_child_care) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.letter_of_explanation_child_care import extract_letter_of_explanation_child_care
# ... and inside the EXTRACTORS dict:
    "letter_of_explanation_child_care": extract_letter_of_explanation_child_care,


### 077-letter-of-explanation-income (letter_of_explanation_income) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.letter_of_explanation_income import extract_letter_of_explanation_income
# ... and inside the EXTRACTORS dict:
    "letter_of_explanation_income": extract_letter_of_explanation_income,


### 078-letter-of-explanation-misc (letter_of_explanation_misc) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.letter_of_explanation_misc import extract_letter_of_explanation_misc
# ... and inside the EXTRACTORS dict:
    "letter_of_explanation_misc": extract_letter_of_explanation_misc,


### 079-letter-of-explanation-property (letter_of_explanation_property) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.letter_of_explanation_property import extract_letter_of_explanation_property
# ... and inside the EXTRACTORS dict:
    "letter_of_explanation_property": extract_letter_of_explanation_property,


### 080-life-insurance-policy (life_insurance_policy) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.life_insurance_policy import extract_life_insurance_policy
# ... and inside the EXTRACTORS dict:
    "life_insurance_policy": extract_life_insurance_policy,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "policy_number_masked": (PiiKind.ACCOUNT, True),


### 081-military-leave-and-earning-statement-les (military_leave_and_earning_statement_les) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.military_leave_and_earning_statement_les import extract_military_leave_and_earning_statement_les
# ... and inside the EXTRACTORS dict:
    "military_leave_and_earning_statement_les": extract_military_leave_and_earning_statement_les,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "social_security_number_masked": (PiiKind.SSN, True),
    "direct_deposit_account_last4": (PiiKind.ACCOUNT, True),

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_ENTITLEMENTS_LIST = ListSpec(
    name="entitlements",
    fields=("label", "amount",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "military_leave_and_earning_statement_les": (_ENTITLEMENTS_LIST,),


### 082-miscellaneous-document (miscellaneous_document) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.miscellaneous_document import extract_miscellaneous_document
# ... and inside the EXTRACTORS dict:
    "miscellaneous_document": extract_miscellaneous_document,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "account_case_or_reference_number": (PiiKind.ACCOUNT, False),

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_KEY_VALUE_PAIRS_LIST = ListSpec(
    name="key_value_pairs",
    fields=("key", "value",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "miscellaneous_document": (_KEY_VALUE_PAIRS_LIST,),


### 083-mortgage-loan-origination-agreement (mortgage_loan_origination_agreement) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.mortgage_loan_origination_agreement import extract_mortgage_loan_origination_agreement
# ... and inside the EXTRACTORS dict:
    "mortgage_loan_origination_agreement": extract_mortgage_loan_origination_agreement,

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_ORIGINATION_AND_BROKER_FEE_ITEMS_LIST = ListSpec(
    name="origination_and_broker_fee_items",
    fields=("fee_name", "amount",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "mortgage_loan_origination_agreement": (_ORIGINATION_AND_BROKER_FEE_ITEMS_LIST,),


### 084-other-property-note (other_property_note) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.other_property_note import extract_other_property_note
# ... and inside the EXTRACTORS dict:
    "other_property_note": extract_other_property_note,


### 085-proof-of-occupancy (proof_of_occupancy) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.proof_of_occupancy import extract_proof_of_occupancy
# ... and inside the EXTRACTORS dict:
    "proof_of_occupancy": extract_proof_of_occupancy,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "account_or_reference_number_masked": (PiiKind.ACCOUNT, True),


### 086-property-profile-non-subject (property_profile_non_subject) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.property_profile_non_subject import extract_property_profile_non_subject
# ... and inside the EXTRACTORS dict:
    "property_profile_non_subject": extract_property_profile_non_subject,


### 087-property-profile-subject (property_profile_subject) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.property_profile_subject import extract_property_profile_subject
# ... and inside the EXTRACTORS dict:
    "property_profile_subject": extract_property_profile_subject,


### 088-property-survey (property_survey) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.property_survey import extract_property_survey
# ... and inside the EXTRACTORS dict:
    "property_survey": extract_property_survey,

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_ENCROACHMENTS_OR_OVERLAPS_LIST = ListSpec(
    name="encroachments_or_overlaps",
    fields=("description", "affected_boundary", "location",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "property_survey": (_ENCROACHMENTS_OR_OVERLAPS_LIST,),


### 089-property-tax-bill-non-subject (property_tax_bill_non_subject) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.property_tax_bill_non_subject import extract_property_tax_bill_non_subject
# ... and inside the EXTRACTORS dict:
    "property_tax_bill_non_subject": extract_property_tax_bill_non_subject,

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_INSTALLMENTS_AND_DUE_DATES_LIST = ListSpec(
    name="installments_and_due_dates",
    fields=("installment_label", "amount", "due_date", "paid_indicator",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "property_tax_bill_non_subject": (_INSTALLMENTS_AND_DUE_DATES_LIST,),


### 090-retirement-check (retirement_check) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.retirement_check import extract_retirement_check
# ... and inside the EXTRACTORS dict:
    "retirement_check": extract_retirement_check,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "plan_claim_or_account_last4": (PiiKind.ACCOUNT, True),
    "deposit_account_last4": (PiiKind.ACCOUNT, True),


### 091-retirement-pension-award-letter (retirement_pension_award_letter) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.retirement_pension_award_letter import extract_retirement_pension_award_letter
# ... and inside the EXTRACTORS dict:
    "retirement_pension_award_letter": extract_retirement_pension_award_letter,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "plan_or_claim_number_masked": (PiiKind.ACCOUNT, True),


### 092-seller-signature-authority (seller_signature_authority) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.seller_signature_authority import extract_seller_signature_authority
# ... and inside the EXTRACTORS dict:
    "seller_signature_authority": extract_seller_signature_authority,

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_SIGNATURES_AND_NOTARY_LIST = ListSpec(
    name="signatures_and_notary",
    fields=("signer_name", "capacity", "signed_indicator", "notary_indicator", "date",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "seller_signature_authority": (_SIGNATURES_AND_NOTARY_LIST,),


### 093-social-security-administration-ssa-89 (social_security_administration_ssa_89) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.social_security_administration_ssa_89 import extract_social_security_administration_ssa_89
# ... and inside the EXTRACTORS dict:
    "social_security_administration_ssa_89": extract_social_security_administration_ssa_89,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "social_security_number": (PiiKind.SSN, False),


### 094-social-security-card-copy (social_security_card_copy) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.social_security_card_copy import extract_social_security_card_copy
# ... and inside the EXTRACTORS dict:
    "social_security_card_copy": extract_social_security_card_copy,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "social_security_number": (PiiKind.SSN, False),


### 095-statement-of-account (statement_of_account) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.statement_of_account import extract_statement_of_account
# ... and inside the EXTRACTORS dict:
    "statement_of_account": extract_statement_of_account,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "account_number_masked": (PiiKind.ACCOUNT, True),

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_TRANSACTIONS_OR_ACTIVITY_LIST = ListSpec(
    name="transactions_or_activity",
    fields=("date", "description", "amount", "type", "running_balance",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "statement_of_account": (_TRANSACTIONS_OR_ACTIVITY_LIST,),


### 096-termite-completion (termite_completion) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.termite_completion import extract_termite_completion
# ... and inside the EXTRACTORS dict:
    "termite_completion": extract_termite_completion,

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_TREATMENT_OR_REPAIR_ITEMS_COMPLETED_LIST = ListSpec(
    name="treatment_or_repair_items_completed",
    fields=("item", "method_or_chemical", "area", "status",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "termite_completion": (_TREATMENT_OR_REPAIR_ITEMS_COMPLETED_LIST,),


### 097-termite-report (termite_report) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.termite_report import extract_termite_report
# ... and inside the EXTRACTORS dict:
    "termite_report": extract_termite_report,

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_FINDINGS_LIST = ListSpec(
    name="findings",
    fields=("category", "insect_or_damage_type", "location", "description",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "termite_report": (_FINDINGS_LIST,),


### 098-transcripts-of-1099 (transcripts_of_1099) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.transcripts_of_1099 import extract_transcripts_of_1099
# ... and inside the EXTRACTORS dict:
    "transcripts_of_1099": extract_transcripts_of_1099,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "recipient_tin_masked": (PiiKind.ACCOUNT, True),

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_INFORMATION_RETURN_RECORDS_LIST = ListSpec(
    name="information_return_records",
    fields=("form_type", "payer_name", "payer_tin_masked", "box_or_income_type", "amount", "account_number_masked",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "transcripts_of_1099": (_INFORMATION_RETURN_RECORDS_LIST,),


### 099-trust-agreement (trust_agreement) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.trust_agreement import extract_trust_agreement
# ... and inside the EXTRACTORS dict:
    "trust_agreement": extract_trust_agreement,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "tax_identification_number_masked": (PiiKind.ACCOUNT, True),


### 100-trust-documents (trust_documents) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.trust_documents import extract_trust_documents
# ... and inside the EXTRACTORS dict:
    "trust_documents": extract_trust_documents,

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_AUTHORIZED_SIGNER_NAMES_AND_CAPACITY_LIST = ListSpec(
    name="authorized_signer_names_and_capacity",
    fields=("name", "capacity", "signature_present",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "trust_documents": (_AUTHORIZED_SIGNER_NAMES_AND_CAPACITY_LIST,),


### 101-trust-federal-tax-returns (trust_federal_tax_returns) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.trust_federal_tax_returns import extract_trust_federal_tax_returns
# ... and inside the EXTRACTORS dict:
    "trust_federal_tax_returns": extract_trust_federal_tax_returns,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "ein": (PiiKind.ACCOUNT, False),

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_BENEFICIARY_K1_RECORDS_LIST = ListSpec(
    name="beneficiary_k1_records",
    fields=("beneficiary_name", "beneficiary_tin_masked", "distributive_share_amount", "income_type", "source",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "trust_federal_tax_returns": (_BENEFICIARY_K1_RECORDS_LIST,),


### 102-unsecured-note (unsecured_note) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.unsecured_note import extract_unsecured_note
# ... and inside the EXTRACTORS dict:
    "unsecured_note": extract_unsecured_note,

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_PAYMENT_HISTORY_LIST = ListSpec(
    name="payment_history",
    fields=("period", "payment_amount", "payment_status", "remaining_balance", "source",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "unsecured_note": (_PAYMENT_HISTORY_LIST,),


### 103-verbal-voe (verbal_voe) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.verbal_voe import extract_verbal_voe
# ... and inside the EXTRACTORS dict:
    "verbal_voe": extract_verbal_voe,


### 104-verification-of-assets (verification_of_assets) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.verification_of_assets import extract_verification_of_assets
# ... and inside the EXTRACTORS dict:
    "verification_of_assets": extract_verification_of_assets,

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_VERIFIED_ACCOUNTS_LIST = ListSpec(
    name="verified_accounts",
    fields=("institution_name", "account_number_masked", "account_type", "account_holder_name", "current_balance", "available_balance", "average_balance", "source",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "verification_of_assets": (_VERIFIED_ACCOUNTS_LIST,),


### 105-verification-of-deposit (verification_of_deposit) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.verification_of_deposit import extract_verification_of_deposit
# ... and inside the EXTRACTORS dict:
    "verification_of_deposit": extract_verification_of_deposit,

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_DEPOSIT_ACCOUNTS_LIST = ListSpec(
    name="deposit_accounts",
    fields=("account_type", "account_number_masked", "current_balance", "average_balance", "date_opened", "source",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "verification_of_deposit": (_DEPOSIT_ACCOUNTS_LIST,),


### 106-verification-of-mortgage (verification_of_mortgage) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.verification_of_mortgage import extract_verification_of_mortgage
# ... and inside the EXTRACTORS dict:
    "verification_of_mortgage": extract_verification_of_mortgage,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "loan_number_masked": (PiiKind.ACCOUNT, True),

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_PAYMENT_HISTORY_MONTHS_LIST = ListSpec(
    name="payment_history_months",
    fields=("month", "payment_status", "amount_paid", "source",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "verification_of_mortgage": (_PAYMENT_HISTORY_MONTHS_LIST,),


### 107-verification-of-rent (verification_of_rent) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.verification_of_rent import extract_verification_of_rent
# ... and inside the EXTRACTORS dict:
    "verification_of_rent": extract_verification_of_rent,

# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.
# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec

_RENT_PAYMENT_HISTORY_LIST = ListSpec(
    name="rent_payment_history",
    fields=("month", "amount_due", "amount_paid", "payment_status", "source",),
)

# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, never a patch — D2):
    "verification_of_rent": (_RENT_PAYMENT_HISTORY_LIST,),


### 108-work-visa-ead-card (work_visa_ead_card) — new module
# Add to app/ai/extraction/__init__.py:
from app.ai.extraction.work_visa_ead_card import extract_work_visa_ead_card
# ... and inside the EXTRACTORS dict:
    "work_visa_ead_card": extract_work_visa_ead_card,

# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS (a snippet, never a patch):
    "document_or_card_number": (PiiKind.ACCOUNT, True),
    "uscis_or_a_number": (PiiKind.ACCOUNT, True),
    "receipt_number": (PiiKind.ACCOUNT, True),
    "passport_number": (PiiKind.ACCOUNT, True),
    "visa_number": (PiiKind.ACCOUNT, True),
    "i94_admission_number": (PiiKind.ACCOUNT, True),

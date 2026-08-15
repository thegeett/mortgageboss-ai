"""Human-facing reason vocabulary (LP-376-C) — findings speak MORTGAGE, not engine.

A `couldnt_check` reason is what a processor reads and acts on. The evaluators know the SHAPE of a failure
(a missing document, fewer than two sources, a low-confidence read) but interpolated an ENGINE id — a tag
(`id.dob`), an operand, a content-id hash — that a loan processor cannot read. This module is the DECLARED
registry (keyed by tag id — the sanctioned pattern, NOT a per-rule-id branch) that translates a fact-tag into
the mortgage noun phrase it represents, plus small humanizers for a document-type slug and an enum value.

WHERE THE LINE IS (D1): the evaluator names WHAT IS MISSING (this module) and a SHAPE-appropriate next step
(it knows the failure kind); it does NOT invent a DOMAIN action ("request the 1003") — that is per-rule
knowledge that belongs in a spec's ``how_to_fix`` (a scoped follow-up). A tag id may still appear in the
provenance card — that is the engineer's view, rendered deliberately (LP-376).
"""

from __future__ import annotations

# tag_id → the mortgage fact it represents, as a noun phrase a processor reads. Seeded with every tag that
# surfaces in a live rule's couldnt_check reason; extend as rules go live. An unmapped tag falls back to a
# humanized stem (never a raw dotted id) — see ``fact_label``.
_FACT_LABELS: dict[str, str] = {
    "id.dob": "borrower's date of birth",
    "id.ssn_hash": "borrower's Social Security number",
    "id.name_normalized": "borrower's name",
    "id.address_normalized": "borrower's residence address",
    "id.current_address_type": "address type (residence vs mailing)",
    "id.id_expiration": "ID expiration date",
    "id.citizenship": "borrower's citizenship",
    "id.app_required_fields_present": "1003 completeness",
    "id.title_vesting_consistent": "title-vesting consistency",
    "id.poa_present_and_acceptable": "power-of-attorney acceptability",
    "occupancy.stated": "stated occupancy",
    "occupancy.consistent_with_signals": "occupancy consistency with the 1003 signals",
    "program.type": "loan program",
    "income.pay_date": "pay-stub date",
    "income.days_since_most_recent_pay": "pay-stub recency",
    "income.qualifying_monthly": "qualifying income",
    # LP-389 — the first activation pass; each live rule's reason tag gets a curated mortgage phrase.
    "income.documented_income_shortfall_pct": "documented-vs-stated income shortfall",  # IN-1
    "income.ytd_annualized_shortfall_pct": "YTD-annualized income shortfall",  # IN-3 (LP-390-9)
    "income.employer_normalized": "employer name",  # IN-5
    # LP-389-A — ID-5 went live per-borrower; its couldnt_check reads on these two derived inputs.
    "id.borrower_id_expiration": "borrower's government ID expiration date",  # ID-5
    "contract.loan_closing_date": "loan's closing date",  # ID-5
    "contract.days_until_closing": "days from the file date to the closing date",  # PC-7 (LP-410 / LP-406-1b)
    # LP-485 — the date-compare family. Each label names the MISSING FACT in mortgage terms (never the tag
    # id), because it is what a processor reads when the rule couldnt_checks.
    "liab.is_disputed": "tradeline's dispute status on the credit report",  # CR-12 (LP-486)
    # CR-12's applicability predicate: the structural marker saying WHICH source a liability subject came
    # from (a credit-report tradeline vs an application-stated liability). It scopes CR-12 to the
    # credit-report leg, so a processor seeing it needs the plain-language reason the check did not apply.
    "liability.source": "whether the debt came from the credit report or the application",
    "rate_lock.days_to_closing": "rate lock's expiration date and the loan's closing date",  # CL-1
    "credit.report_age_months_at_closing": "credit report's pull date and the loan's closing date",  # CR-13
    "property.appraisal_age_months_at_closing": "appraisal's effective date and the loan's closing date",  # PR-6
    "contract.loan_sales_price": "purchase contract's sale price",  # PC-2 (LP-407-2 / LP-407-3)
    "property.purchase_price": "purchase price stated in the loan file",  # PC-2 (LP-407-3)
    "ins.loan_effective_date": "insurance policy's effective date",  # IH-3 (LP-417)
    # IH-9 (LP-509-D1). Phrased as the POLICY PERIOD rather than "whether the policy has expired": the
    # label completes a couldnt_check sentence ("the … could not be determined"), and what the processor
    # must go and find is the binder's dates, not the verdict.
    "ins.policy_expired": "insurance policy's coverage period",
    "ins.dwelling_settlement_basis": "dwelling loss-settlement basis",  # IH-1 (LP-447)
    "ins.mortgagee_clause_correct": "mortgagee named on the insurance binder",  # IH-2 (LP-487)
    "ins.condo_master_policy": "condominium project's master insurance policy",  # IH-7 (LP-487)
    "property.type": "property type",  # IH-7's applicability predicate (LP-487)
    "loan.ltv_percent": "loan-to-value ratio",  # MI-1 (LP-488)
    "mi.fha_ufmip_percent": "upfront FHA mortgage insurance premium financed into the note",  # MI-4 (LP-488)
    "condo.questionnaire_present": "condo questionnaire",  # CO-1 (LP-488)
    # LP-494 — the condo project lane (CO-4 reserves, CO-5 eligibility).
    "condo.reserve_pct": "HOA budgeted replacement-reserve percentage",
    "ins.condo_fidelity_coverage": "condominium project's fidelity / crime coverage",
    "condo.fidelity_present_raw": "master policy's fidelity / crime indicator",
    "condo.fidelity_amount": "fidelity / crime coverage amount",
    "condo.reserve_adequacy": "HOA replacement-reserve adequacy",
    # LP-498 — FR-3. Phrased as what a processor reads, and deliberately non-accusatory.
    "contract.unusual_credits": "seller credits and side-agreement references on the purchase contract",
    "contract.credits_warrant_review": "whether the contract's credit terms need a look",
    # LP-497 — AS-4 went live; its couldnt_check reads on this tag.
    "reserves.required_months": "reserve requirement for this occupancy and unit count",
    # LP-496a — program eligibility (PE-1, PE-3).
    "program.conforming_eligibility": "loan amount against the conforming loan limit",
    "program.fha_min_investment_met": "FHA minimum required investment",
    "condo.delinquent_units_pct": "percentage of units 60+ days delinquent on assessments",
    "condo.commercial_space_pct": "project's commercial / mixed-use share",
    "condo.total_units": "project's total unit count",
    "condo.single_entity_owned_units": "units owned by a single entity",
    "condo.litigation_disclosed": "condo questionnaire's litigation answer",
    "condo.project_eligibility": "condo project eligibility (delinquency, concentration, litigation)",
    "loan.application_received_date": "loan application date",
    # LP-495a — the REO reconciliation lane (RE-1 / DT-6) and LOE completeness (LO-2).
    "reo.statement_disclosure": "whether this mortgage statement's obligation is on the application",
    "reo.statement_payment_coverage": "stated monthly payment against the servicer's billed payment",
    "loe.is_explanation_letter": "whether this document is a letter of explanation",
    "loe.completeness": "letter of explanation's explanation, date and signature",
    # LP-495b — the judgmental cohort: other-income continuance, rental support, and ATR documentation.
    "income.continuance_3yr": "whether this income will continue long enough to be used",
    "income.type": "income category",
    "income.other_income_continues": "other income's continuance and documentation",  # IN-13
    "income.rental_income_supportable": "whether the rental income can be used to qualify",  # IN-14
    "occupancy.rental_support": "rental-income supporting documents (lease, rent schedule, Schedule E)",
    "occupancy.investment_rental_supported": "rental support behind the investment occupancy",  # OC-3
    "dti.atr_factors_documented": "documents supporting each ability-to-repay factor",  # DT-7
    "dti.atr_documentation_adequate": "ability-to-repay documentation completeness",  # DT-7 verdict
    "title.vested_owner_matches": "owner of record on the title commitment",  # TI-1 (LP-491)
    "title.vested_owner_name": "owner of record on the title commitment",  # TI-1
    "contract.seller_name": "seller named on the purchase agreement",  # TI-1
    "title.legal_description": "legal description on the title commitment",  # TI-2 (LP-491)
    "title.property_address": "property address on the title commitment",  # TI-2
    "title.chain_transfer_count": "number of transfers in the chain of title",  # TI-6
    "title.chain_has_gap": "continuity of the chain of title",  # TI-6
    "title.chain_shortest_interval_days": "shortest interval between transfers",  # TI-6
    "property.value_vs_price_gap": "appraised value against the purchase price",  # PR-2 (LP-492)
    "loan.purpose": "loan purpose (purchase or refinance)",  # PR-2's applicability predicate (LP-492)
    "property.condition_rating": "appraisal's condition rating",  # PR-5 (LP-492)
    "property.condition_rating_raw": "appraisal's condition rating",  # PR-5
    "property.appraisal_address_match": "property address on the appraisal",  # PR-7 (LP-492)
    "property.appraisal_completion_condition": "whether the appraisal is made subject to repairs",  # PR-4
    "property.appraisal_property_type": "property type stated on the appraisal",  # PR-3
    "contract.emd_sourced": "earnest money deposit and the account it left",  # PC-5 (LP-493)
    "contract.emd_amount": "earnest money deposit on the contract",  # PC-5
    "contract.personal_property": "personal property included in the contract",  # PC-8 (LP-493)
    "aus.recommendation": "AUS recommendation",  # AU-3 (LP-488)
    "credit.inquiry_explained": "credit inquiries and their explanations",  # CR-5 (LP-490)
    "liab.derogatory_type": "type of derogatory credit event",  # CR-6 (LP-490)
    "liab.in_application": "whether this debt is on the application",  # CR-1 (LP-490a)
    "credit.undisclosed_tradeline": "debts on the report not stated on the application",  # CR-4
    "liab.is_derogatory": "whether this account carries a derogatory mark",  # CR-6 (LP-490a)
    "credit.has_collections": "collections on the credit report",  # CR-10 (LP-490a)
    "liab.derogatory_date": "date of the derogatory credit event",  # CR-6 (LP-490)
    "credit.derogatory_months_elapsed": "time since the derogatory event",  # CR-6 (LP-490)
    "liab.is_mortgage": "whether this account is a mortgage",  # CR-8 (LP-490)
    "liab.structured_history_confident": "readability of the payment history",  # CR-8 (LP-490)
    "liab.mortgage_late_60_plus_last_12mo": "recent 60-day-or-worse mortgage delinquency",  # CR-8
    "liab.is_medical_collection": "whether this collection is medical",  # CR-10 (LP-490)
    "liab.collection_balance": "collection balance",  # CR-10 (LP-490)
    "credit.collection_aggregate_balance": "total of non-medical collections",  # CR-10 (LP-490)
    "property.occupancy": "property occupancy",  # CR-10 (LP-490)
    "loan.amount": "base loan amount",  # LP-488
    "loan.note_amount": "note amount",  # MI-4 (LP-488)
    "property.value_basis": "property value used for the loan-to-value",  # LP-488
    "property.address_normalized_match": "match between the contract and file property addresses",  # PC-3 (LP-407-4)
    # LP-384 — the second activation pass (AS-9 / IN-4 / AS-10 went live).
    "stmt.page_count_declared": "declared page count (the statement's 'of N')",  # AS-9
    "stmt.page_count_present": "pages actually present",  # AS-9
    "income.max_employment_gap_days": "largest employment gap",  # IN-4
    "stmt.min_account_months": "months of statements on file per account",  # AS-10
    "stmt.continuity": "statement balance continuity across the account",  # AS-8 (LP-410 / LP-406-2b)
    "stmt.owner_matches_borrower": "account-holder match to a borrower",  # AS-6 (LP-429)
    "stmt.holder_name_variance": "account-holder name variance",  # AS-6 (LP-429 — the gated tag)
    "stmt.non_borrower_co_holder": "non-borrower co-holder on the account",  # AS-6 (LP-429)
    "income.employer_coverage": "pay-stub / W-2 employer coverage",  # IN-6 (LP-410 / LP-406-3b)
    "dti.qualifying_income_monthly": "qualifying income",
    "housing.insurance_monthly": "homeowners insurance",
    "housing.taxes_monthly": "property taxes",
    "txn.amount": "deposit amount",
    "txn.date": "deposit date",
    "txn.is_money_in": "deposit direction",
    "txn.has_identified_source": "deposit's source",
    "txn.source_strength": "deposit's source strength",
    "txn.apparent_category": "deposit category",  # LP-390-7: AS-12 (live) reads it — a curated reason label
    # LP-393-6 — the scenario-calibrated income/asset rules went live; their couldnt_check reasons read these.
    "income.same_line_of_work": "same line of work (job-change continuity)",  # IN-7
    "income.is_declining": "year-over-year income trend",  # IN-10
    "income.has_2yr_history": "two-year income history",  # IN-11
    "asset.liquidation_terms": "account's liquidation terms",  # AS-11
    "income.is_self_employed": "self-employment income status",  # IN-12 (LP-423 — its applicability gate)
    "income.terminated_employment": "terminated-employment documentation status",  # IN-15 (LP-430)
    "income.history_documentation": "income-history documentation basis",  # IN-16 (LP-433)
    "income.voe_present": "Verification of Employment",  # IN-8 (LP-428)
    "income.offer_letter_present": "employment offer letter",  # IN-9 (LP-428)
}


def fact_label(tag_id: str) -> str:
    """The mortgage noun phrase a fact-tag represents (e.g. ``id.dob`` → "borrower's date of birth"). An
    unmapped tag degrades to a humanized STEM — the part after the last dot with underscores spaced — so a
    raw dotted id or hash never reaches a processor."""
    label = _FACT_LABELS.get(tag_id)
    if label is not None:
        return label
    stem = tag_id.rsplit(".", 1)[-1]
    return stem.replace("_", " ").strip() or tag_id


def document_label(doc_type: str) -> str:
    """A classifier document-type slug → its English name (``title_commitment`` → "title commitment")."""
    return doc_type.replace("_", " ").strip() or doc_type


def enum_label(value: str) -> str:
    """A tag enum value for a processor (``residence`` stays "residence"; underscores spaced)."""
    return value.replace("_", " ").strip() or value


__all__ = ["document_label", "enum_label", "fact_label"]

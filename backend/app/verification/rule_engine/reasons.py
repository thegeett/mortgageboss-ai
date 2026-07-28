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
    "contract.loan_sales_price": "purchase contract's sale price",  # PC-2 (LP-407-2 / LP-407-3)
    "property.purchase_price": "purchase price stated in the loan file",  # PC-2 (LP-407-3)
    "ins.loan_effective_date": "insurance policy's effective date",  # IH-3 (LP-417)
    # LP-384 — the second activation pass (AS-9 / IN-4 / AS-10 went live).
    "stmt.page_count_declared": "declared page count (the statement's 'of N')",  # AS-9
    "stmt.page_count_present": "pages actually present",  # AS-9
    "income.max_employment_gap_days": "largest employment gap",  # IN-4
    "stmt.min_account_months": "months of statements on file per account",  # AS-10
    "stmt.continuity": "statement balance continuity across the account",  # AS-8 (LP-410 / LP-406-2b)
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

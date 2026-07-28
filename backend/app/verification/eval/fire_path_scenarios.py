"""LP-414 Part B — the standalone FIRE-PATH scenario snapshots.

Three live/written rules ship with their FIRE branches unexercised on real-data-shaped snapshots (the clean
LF-6T3N realism anchor never triggers them): AS-8's ``broken`` (a statement balance break), and PC-7's two
fired outcomes (a PAST closing date, a FAR-FUTURE one). This gives each a deliberate, minimal scenario that
DOES fire — plus a housing scenario whose single subject documents let ``housing.taxes_monthly`` /
``housing.hoa_monthly`` materialize a REAL figure (DT-4 / DT-2 input provability, which LF-6T3N's two-bill file
cannot show).

Standalone, per the LP-393-1 / LP-398 pattern: own loan/borrower/content ids (the ``95…`` namespace, disjoint
from LF-6T3N's ``1111…/2222…``, the income fixture's ``93…``, and the owner-match fixture's ``94…``); never
merged into, never imported by, any of them. Each scenario is a SEPARATE snapshot carrying only the documents
its target needs (a break is never stacked on a past closing date — one problem per file, so each verdict is
attributable).

NOT built (LP-414 B3): a DTI HOA-gate scenario. LP-413's gate lives in the DB DTI path (``build_dti_calculation``)
and is unit-tested there (``test_dti._seed_hoa``); the snapshot's ``calculations.map_dti`` gates only on the
REQUIRED taxes/insurance tags (HOA is not among them), so a snapshot scenario could not even exhibit the gate —
it would be redundant fixture surface with no coverage gain.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    BorrowerRef,
    DocumentEntry,
    DocumentsSection,
    MismoSection,
    Snapshot,
    SnapshotField,
    TagsSection,
)

# Own id namespace — the "95…" prefix, disjoint from LF-6T3N (1111…/2222…), income (93…), owner-match (94…).
_LOAN_BREAK = UUID("95000000-0000-4000-8000-000000000001")
_LOAN_PAST = UUID("95000000-0000-4000-8000-000000000002")
_LOAN_FUTURE = UUID("95000000-0000-4000-8000-000000000003")
_LOAN_HOUSING = UUID("95000000-0000-4000-8000-000000000004")
_LOAN_INS_INFORCE = UUID(
    "95000000-0000-4000-8000-000000000005"
)  # LP-417 — binder effective BEFORE closing
_LOAN_INS_LATE = UUID(
    "95000000-0000-4000-8000-000000000006"
)  # LP-417 — binder effective AFTER closing
_LOAN_INS_AMBIG = UUID("95000000-0000-4000-8000-000000000007")  # LP-417 — two binders disagree
_LOAN_INS_DECREE_ONLY = UUID(
    "95000000-0000-4000-8000-000000000008"
)  # LP-417 review — a divorce_decree effective_date, NO binder (must couldnt_check)
_LOAN_INS_DECREE_PLUS = UUID(
    "95000000-0000-4000-8000-000000000009"
)  # LP-417 review — binder + a decree with a different effective_date (must resolve to the binder)
_LOAN_ADDR_MATCH = UUID(
    "95000000-0000-4000-8000-00000000000a"
)  # LP-407-4 — contract addr == file addr
_LOAN_ADDR_MISMATCH = UUID("95000000-0000-4000-8000-00000000000b")  # LP-407-4 — different property
_LOAN_ADDR_ABBREV = UUID(
    "95000000-0000-4000-8000-00000000000c"
)  # LP-407-4 review — suffix/state/ZIP+4 variants the canonicalizer NOW resolves (→ satisfied)
_LOAN_ADDR_MAILING = UUID(
    "95000000-0000-4000-8000-00000000000d"
)  # LP-407-4 — only a mailing address (trap)
_LOAN_ADDR_UNIT = UUID(
    "95000000-0000-4000-8000-00000000000e"
)  # LP-407-4 review — a unit-designator residue the canonicalizer leaves (→ needs_review)
_LOAN_VOE_OFFER = UUID(
    "95000000-0000-4000-8000-00000000000f"
)  # LP-418 — VOE + offer-letter labeling n
_LOAN_OTHER_INCOME = UUID(
    "95000000-0000-4000-8000-000000000010"
)  # LP-418 — other-income continuance n
_RUN = UUID("95000000-0000-4000-8000-0000000000ff")
# The file (snapshot) date every closing date is measured against (deterministic — never a wall-clock now()).
_FILE_DATE = datetime(2026, 7, 1, tzinfo=UTC)


def _f(value: str) -> Field:
    return Field.present(value, source=FieldSource.EXTRACTED)


def _doc(cid: str, dtype: str, **fields: str) -> DocumentEntry:
    return DocumentEntry(
        content_id=cid,
        document_type=dtype,
        belongs_to=None,
        fields={k: _f(v) for k, v in fields.items()},
    )


def _snapshot(
    loan_id: UUID, docs: list[DocumentEntry], mismo: dict[str, SnapshotField] | None = None
) -> Snapshot:
    return Snapshot(
        loan_file_id=loan_id,
        run_id=_RUN,
        created_at=_FILE_DATE,
        documents=DocumentsSection.present(docs),
        mismo=MismoSection.present(mismo or {}),
        tags=TagsSection.present({}),
    )


# --------------------------------------------------------------------------- #
# AS-8 — a statement BALANCE BREAK (stmt.continuity -> "broken" -> AS-8 fired)
# --------------------------------------------------------------------------- #
def build_statement_break_snapshot() -> Snapshot:
    """Two consecutive statements for ONE account where statement 1's ending balance (1500) does NOT carry
    into statement 2's opening balance (1200) — a break. resolve_accounts groups them by (bank_name,
    account_number_masked); the period dates order them; stmt.continuity -> "broken" -> AS-8 FIRES."""
    common = {
        "account_holder_name": "Dana Brooks",
        "bank_name": "Cedar Valley Bank",
        "account_number_masked": "****3344",
        "account_type": "checking",
    }
    return _snapshot(
        _LOAN_BREAK,
        [
            _doc(
                "95-stmt-mar",
                "bank_statement",
                **common,
                statement_period_start="2026-03-01",
                statement_period_end="2026-03-31",
                beginning_balance="1000.00",
                ending_balance="1500.00",
            ),
            _doc(
                "95-stmt-apr",
                "bank_statement",
                **common,
                statement_period_start="2026-04-01",
                statement_period_end="2026-04-30",
                beginning_balance="1200.00",  # != 1500.00 — the break
                ending_balance="1800.00",
            ),
        ],
    )


# --------------------------------------------------------------------------- #
# PC-7 — a PAST closing date and a FAR-FUTURE one (contract.days_until_closing -> PC-7 fired, twice over)
# --------------------------------------------------------------------------- #
def build_past_closing_snapshot() -> Snapshot:
    """A purchase contract whose closing date (2026-05-01) is BEFORE the file date (2026-07-01) — 61 days in
    the PAST. contract.days_until_closing == "-61" < min (0) -> PC-7 FIRES ("has already passed")."""
    return _snapshot(
        _LOAN_PAST,
        [
            _doc(
                "95-pa-past",
                "purchase_agreement",
                property_address="12 Cedar Ct, Rivertown IL 60000",
                sales_price="300000.00",
                closing_date="2026-05-01",
                buyer_name="Dana Brooks",
                seller_name="Reese Alvarez",
            )
        ],
    )


def build_far_future_closing_snapshot() -> Snapshot:
    """A purchase contract whose closing date (2026-12-01) is 153 days AHEAD of the file date (2026-07-01) —
    beyond Priya's 90-day window. contract.days_until_closing == "153" > max (90) -> PC-7 FIRES (far-future)."""
    return _snapshot(
        _LOAN_FUTURE,
        [
            _doc(
                "95-pa-future",
                "purchase_agreement",
                property_address="34 Birch Rd, Rivertown IL 60000",
                sales_price="300000.00",
                closing_date="2026-12-01",
                buyer_name="Dana Brooks",
                seller_name="Reese Alvarez",
            )
        ],
    )


# --------------------------------------------------------------------------- #
# housing.taxes_monthly / housing.hoa_monthly — a single subject property's docs materialize a REAL figure
# (DT-4 / DT-2 input provability with the REAL extractor field names — LF-6T3N's two-bill file cannot show it)
# --------------------------------------------------------------------------- #
def build_subject_housing_snapshot() -> Snapshot:
    """One subject-property tax bill (annual_tax_amount 6000 -> 500/mo) + one HOA statement (dues 300 monthly
    -> 300/mo), each with the REAL extractor field names, so housing.taxes_monthly and housing.hoa_monthly
    materialize a REAL number instead of abstaining. Proves the DT-4 / DT-2 inputs resolve end-to-end."""
    return _snapshot(
        _LOAN_HOUSING,
        [
            _doc(
                "95-tax",
                "property_tax_bill",
                property_address="34 Birch Rd, Rivertown IL 60000",
                assessed_value="250000.00",
                annual_tax_amount="6000.00",
                due_dates="2026-09-01",
            ),
            _doc(
                "95-hoa",
                "hoa_statement",
                association_name="Birch Rd HOA",
                property_address="34 Birch Rd, Rivertown IL 60000",
                dues_amount="300.00",
                dues_frequency="monthly",
            ),
        ],
    )


# --------------------------------------------------------------------------- #
# IH-3 (LP-417) — insurance effective date vs closing. Each scenario carries a homeowners_insurance binder
# (the effective date) + a purchase agreement (the closing date, which contract.loan_closing_date promotes).
# IH-3 is loan-enumerated; ins.loan_effective_date + contract.loan_closing_date are both loan-level.
# --------------------------------------------------------------------------- #
def _binder(cid: str, effective_date: str) -> DocumentEntry:
    return _doc(
        cid,
        "homeowners_insurance",
        carrier_name="Rivertown Mutual",
        policy_number="RM-0001",
        coverage_amount="300000.00",
        annual_premium="1200.00",
        effective_date=effective_date,
        expiration_date="2027-06-01",
    )


def _contract(cid: str, closing_date: str) -> DocumentEntry:
    return _doc(
        cid,
        "purchase_agreement",
        property_address="34 Birch Rd, Rivertown IL 60000",
        sales_price="300000.00",
        closing_date=closing_date,
    )


def build_insurance_in_force_snapshot() -> Snapshot:
    """A binder effective 2026-06-01, BEFORE the 2026-07-15 closing → coverage in force at closing → IH-3
    SATISFIED. The clean case."""
    return _snapshot(
        _LOAN_INS_INFORCE,
        [_binder("95-binder-ok", "2026-06-01"), _contract("95-pa-ins-ok", "2026-07-15")],
    )


def build_insurance_late_snapshot() -> Snapshot:
    """A binder effective 2026-08-15, AFTER the 2026-07-15 closing → a coverage gap → IH-3 FIRED (with the two
    dates interpolated)."""
    return _snapshot(
        _LOAN_INS_LATE,
        [_binder("95-binder-late", "2026-08-15"), _contract("95-pa-ins-late", "2026-07-15")],
    )


def build_insurance_two_binder_snapshot() -> Snapshot:
    """TWO binders stating DIFFERENT effective dates → the multi-binder abstain → ins.loan_effective_date
    "unknown" → IH-3 COULDNT_CHECK (never a silently-picked binder)."""
    return _snapshot(
        _LOAN_INS_AMBIG,
        [
            _binder("95-binder-a", "2026-06-01"),
            _binder("95-binder-b", "2026-08-15"),
            _contract("95-pa-ins-ambig", "2026-07-15"),
        ],
    )


def _divorce_decree(cid: str, effective_date: str) -> DocumentEntry:
    # A divorce_decree ALSO carries an `effective_date` field (the divorce_decree extractor's typed core) — the
    # SAME field name the homeowners_insurance binder uses. The parsed ins.effective_date tag is scoped by field
    # NAME, so it materializes on this decree too; _loan_effective_date must NOT count it as an insurance date.
    return _doc(
        cid,
        "divorce_decree",
        party_1_name="Dana Brooks",
        party_2_name="Riley Brooks",
        effective_date=effective_date,
    )


def build_insurance_decree_only_snapshot() -> Snapshot:
    """A divorce_decree with an effective_date AFTER closing but NO insurance binder. IH-3 must COULDNT_CHECK
    (no binder → an honest missing-insurance gap) — NOT fire on the decree's date as if it were a policy.
    Regression for the effective_date field-name collision (a divorce decree is not an insurance binder)."""
    return _snapshot(
        _LOAN_INS_DECREE_ONLY,
        [
            _divorce_decree("95-decree-only", "2026-09-01"),
            _contract("95-pa-decree-only", "2026-07-15"),
        ],
    )


def build_insurance_binder_plus_decree_snapshot() -> Snapshot:
    """A real binder effective BEFORE closing PLUS a divorce_decree whose effective_date DIFFERS. IH-3 must
    resolve to the BINDER's date and SATISFY — the decree must not create a false multi-binder disagreement
    that abstains to couldnt_check (a false negative). Regression for the effective_date collision."""
    return _snapshot(
        _LOAN_INS_DECREE_PLUS,
        [
            _binder("95-binder-decree", "2026-06-01"),
            _divorce_decree("95-decree-plus", "2026-09-01"),
            _contract("95-pa-decree-plus", "2026-07-15"),
        ],
    )


# --------------------------------------------------------------------------- #
# PC-3 (LP-407-4) — the purchase contract's subject-property address vs the loan file's (MISMO) subject-property
# address. Each carries a purchase_agreement (property_address) + the MISMO SUBJECT address (property.address_*).
# PC-3 is loan-enumerated; property.address_normalized_match is loan-level. "no" routes to needs_review (ADR-325).
# --------------------------------------------------------------------------- #
def _addr_contract(cid: str, property_address: str) -> DocumentEntry:
    return _doc(
        cid, "purchase_agreement", property_address=property_address, closing_date="2026-07-15"
    )


def _subject_mismo(line: str, city: str, state: str, postal: str) -> dict[str, SnapshotField]:
    """The MISMO SUBJECT-property address (property.address_* — NOT a mailing address)."""
    return {
        "property.address_line": _f(line),
        "property.city": _f(city),
        "property.state": _f(state),
        "property.postal_code": _f(postal),
    }


def build_address_match_snapshot() -> Snapshot:
    """The contract's property address == the file's MISMO subject address (after normalization) → PC-3
    SATISFIED. The clean case."""
    return _snapshot(
        _LOAN_ADDR_MATCH,
        [_addr_contract("95-pa-addr-ok", "789 Birchwood Ln, Springfield IL 62711")],
        _subject_mismo("789 Birchwood Ln", "Springfield", "IL", "62711"),
    )


def build_address_mismatch_snapshot() -> Snapshot:
    """The contract is for one property, the file states a DIFFERENT one → PC-3 NEEDS_REVIEW (surfaced for a
    human, never auto-fired — ADR-325)."""
    return _snapshot(
        _LOAN_ADDR_MISMATCH,
        [_addr_contract("95-pa-addr-diff", "789 Birchwood Ln, Springfield IL 62711")],
        _subject_mismo("456 Oak Street", "Rivertown", "IL", "60000"),
    )


def build_address_abbrev_snapshot() -> Snapshot:
    """The former FALSE-POSITIVE case, now RESOLVED deterministically (LP-407-4 review): same property, but the
    contract writes "Lane" / "Illinois" / a ZIP+4 while the file has "Ln" / "IL" / ZIP5. The address
    canonicalizer (_norm_address: street suffixes + state names + ZIP+4→ZIP5) unifies all three, so PC-3 now
    SATISFIES instead of routing this common same-property rendering to needs_review noise."""
    return _snapshot(
        _LOAN_ADDR_ABBREV,
        [
            _addr_contract(
                "95-pa-addr-abbrev", "789 Birchwood Lane, Springfield Illinois 62711-0142"
            )
        ],
        _subject_mismo("789 Birchwood Ln", "Springfield", "IL", "62711"),
    )


def build_address_unit_variant_snapshot() -> Snapshot:
    """THE RESIDUE the canonicalizer deliberately leaves (LP-407-4 review): the SAME property, but the unit is
    written "Apt 2" on the contract vs "Unit 2" in the file. Unit designators are NOT canonicalized (too varied
    to unify safely), so this still reads as a mismatch → PC-3 NEEDS_REVIEW (surfaced for a human, never
    fired) — the ADR-325 routing survives for the surface forms the deterministic matcher cannot resolve."""
    return _snapshot(
        _LOAN_ADDR_UNIT,
        [_addr_contract("95-pa-addr-unit", "789 Birchwood Ln Apt 2, Springfield IL 62711")],
        {
            "property.address_line": _f("789 Birchwood Ln"),
            "property.address_line_2": _f("Unit 2"),
            "property.city": _f("Springfield"),
            "property.state": _f("IL"),
            "property.postal_code": _f("62711"),
        },
    )


def build_address_mailing_only_snapshot() -> Snapshot:
    """THE MAILING-ADDRESS TRAP (D1): the file has a borrower MAILING address but NO subject-property address
    (property.address_* absent). PC-3 must COULDNT_CHECK — never compare the contract against the mailing
    address as a substitute."""
    return _snapshot(
        _LOAN_ADDR_MAILING,
        [_addr_contract("95-pa-addr-mailing", "789 Birchwood Ln, Springfield IL 62711")],
        {
            "borrower.1.current_address_line": _f("PO Box 55, Elsewhere IL 60000")
        },  # mailing, NOT property.*
    )


# --------------------------------------------------------------------------- #
# LP-418 #5 — a VOE + offer-letter LABELING fixture. income_docs (subject:document, applies_to:None → EVERY
# document) perceives income.voe_present / income.offer_letter_present / income.future_employment per document.
# LP-395 measured voe_present n=3 and offer_letter_present n=0 (an EMPTY positive class → IN-9 uncalibratable).
# This standalone file supplies a positive class for both: six VOE docs + six employment_offer_letter docs, so
# each tag has ≥6 labelable rows on ONE fixture. The values are the AI's to assign at calibration; the fixture's
# job is to guarantee the ROWS exist. Documents need no borrower attribution here (income_docs is per-document).
# --------------------------------------------------------------------------- #
_VOE_EMPLOYERS = (
    "Lakeside Systems",
    "Cedar Analytics",
    "Birch Media",
    "Rivertown Foods",
    "Oak Freight",
    "Elm Retail",
)
_OFFER_EMPLOYERS = (
    "Summit Robotics",
    "Harbor Logistics",
    "Vista Health",
    "Delta Print",
    "Nova Legal",
    "Pine Foundry",
)


def build_voe_offer_labeling_snapshot() -> Snapshot:
    """Six verification-of-employment forms + six employment offer letters (each with a future start date), so
    income_docs has a real positive class for BOTH income.voe_present and income.offer_letter_present — the
    LP-395 gap (offer_letter_present had zero positives → IN-9 could not calibrate). Standalone (95… namespace,
    its own loan); the AI assigns the labels, the fixture guarantees ≥6 labelable rows per tag."""
    docs: list[DocumentEntry] = []
    for i, emp in enumerate(_VOE_EMPLOYERS):
        docs.append(
            _doc(
                f"95-voe-{i}",
                "voe",
                employer_name=emp,
                employee_name="Dana Brooks",
                position="Analyst",
                start_date="2024-07-01",
                employment_status="active",
            )
        )
    for i, emp in enumerate(_OFFER_EMPLOYERS):
        docs.append(
            _doc(
                f"95-offer-{i}",
                "employment_offer_letter",
                employer_name=emp,
                candidate_name="Dana Brooks",
                position="Analyst",
                start_date="2026-09-01",  # a FUTURE start date — the offer_letter_present signal
                annual_salary="95000.00",
            )
        )
    return _snapshot(_LOAN_VOE_OFFER, docs)


# --------------------------------------------------------------------------- #
# LP-418 #6 — an OTHER-INCOME continuance fixture. income_stability (subject:borrower, applies_to includes the
# 1003) perceives income.continuance_3yr per borrower — "does this income continue 3+ years?", the question that
# only bites for fixed-term / other income (pension, alimony, child support, disability, note). LP-395 measured
# continuance_3yr all-unknown (n=1) because no fixture stated other income with a continuance horizon. This
# supplies six borrowers, each a 1003 declaring a different other-income type, so continuance_3yr has ≥6
# labelable rows. Per-borrower → each doc is attributed (belongs_to) and each borrower has a MISMO id.
# --------------------------------------------------------------------------- #
_OTHER_INCOME = (
    ("pension", "Retirement pension, $1,800/mo, no stated end"),
    ("alimony", "Alimony, $1,200/mo, court-ordered through 2031"),
    ("child_support", "Child support, $900/mo, youngest child age 9"),
    ("disability", "Long-term disability, $1,500/mo, permanent rating"),
    ("social_security", "Social Security retirement, $2,100/mo"),
    ("note_receivable", "Installment note income, $700/mo, matures 2027"),
)


def build_other_income_continuance_snapshot() -> Snapshot:
    """Six borrowers, each a 1003 (uniform_residential_loan_application) declaring one other-income type with a
    continuance horizon (pension / alimony / child support / disability / Social Security / a maturing note), so
    income_stability produces income.continuance_3yr for six borrowers — the positive class LP-395 lacked (it
    read all-unknown, n=1). Standalone; per-borrower attribution + MISMO ids so BorrowerSubject enumerates six."""
    docs: list[DocumentEntry] = []
    mismo: dict[str, SnapshotField] = {}
    for i, (kind, description) in enumerate(_OTHER_INCOME, start=1):
        bid = UUID(f"95000000-0000-4000-8000-0000000001{i:02d}")
        name = f"Borrower {i}"
        mismo[f"borrower.{i}.borrower_id"] = _f(str(bid))
        mismo[f"borrower.{i}.first_name"] = _f(name)
        docs.append(
            DocumentEntry(
                content_id=f"95-1003-{i}",
                document_type="uniform_residential_loan_application",
                belongs_to=(BorrowerRef(borrower_id=bid, name=name),),
                fields={
                    "other_income_type": _f(kind),
                    "other_income_description": _f(description),
                },
            )
        )
    return _snapshot(_LOAN_OTHER_INCOME, docs, mismo)


# The expected fired/materialized outcomes — recorded HERE / in tests, never predicted in prose (LP-337).
EXPECTED_TAXES_MONTHLY = "500.00"  # 6000 / 12
EXPECTED_HOA_MONTHLY = "300.00"  # 300 monthly
EXPECTED_INS_EFFECTIVE_IN_FORCE = "2026-06-01"  # <= 2026-07-15 closing → satisfied
EXPECTED_INS_EFFECTIVE_LATE = "2026-08-15"  # > 2026-07-15 closing → fired

__all__ = [
    "EXPECTED_HOA_MONTHLY",
    "EXPECTED_INS_EFFECTIVE_IN_FORCE",
    "EXPECTED_INS_EFFECTIVE_LATE",
    "EXPECTED_TAXES_MONTHLY",
    "build_address_abbrev_snapshot",
    "build_address_mailing_only_snapshot",
    "build_address_match_snapshot",
    "build_address_mismatch_snapshot",
    "build_address_unit_variant_snapshot",
    "build_far_future_closing_snapshot",
    "build_insurance_binder_plus_decree_snapshot",
    "build_insurance_decree_only_snapshot",
    "build_insurance_in_force_snapshot",
    "build_insurance_late_snapshot",
    "build_insurance_two_binder_snapshot",
    "build_other_income_continuance_snapshot",
    "build_past_closing_snapshot",
    "build_statement_break_snapshot",
    "build_subject_housing_snapshot",
    "build_voe_offer_labeling_snapshot",
]

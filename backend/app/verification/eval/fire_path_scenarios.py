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
_LOAN_SELF_EMPLOYED = UUID(
    "95000000-0000-4000-8000-000000000011"
)  # LP-419 — a self-employed borrower (IN-12 fire path)
_SE_BORROWER = UUID(
    "95000000-0000-4000-8000-0000000001aa"
)  # LP-419 — the self-employed borrower id
_LOAN_SCHEDULES = UUID(
    "95000000-0000-4000-8000-000000000012"
)  # LP-421 — a tax return with real Schedule C / E
_SCHED_BORROWER = UUID("95000000-0000-4000-8000-0000000001bb")  # LP-421 — the schedules borrower id
_LOAN_TERMINATED = UUID(
    "95000000-0000-4000-8000-000000000013"
)  # LP-430 — terminated-employment scenario
_LOAN_PAY_STUB_ONLY = UUID(
    "95000000-0000-4000-8000-000000000014"
)  # LP-433 — pay-stub-only documentation scenario
_LOAN_INS_RC = UUID(
    "95000000-0000-4000-8000-000000000015"
)  # LP-447 — replacement-cost basis (IH-1 satisfied)
_LOAN_INS_ACV = UUID(
    "95000000-0000-4000-8000-000000000016"
)  # LP-447 — actual-cash-value basis (IH-1 fired)
_LOAN_INS_BASIS_UNREADABLE = UUID(
    "95000000-0000-4000-8000-000000000017"
)  # LP-447 — an UNRECOGNISED basis string (IH-1 couldnt_check — fail closed)
# LP-487 — IH-2 (mortgagee clause) and IH-7 (condo master policy).
_LOAN_IH2_MATCH = UUID("95000000-0000-4000-8000-000000000018")
_LOAN_IH2_MISMATCH = UUID("95000000-0000-4000-8000-000000000019")
_LOAN_IH2_NO_LENDER = UUID("95000000-0000-4000-8000-00000000001a")
_LOAN_IH2_LE_ONLY = UUID("95000000-0000-4000-8000-00000000001b")
_LOAN_IH7_ADEQUATE = UUID("95000000-0000-4000-8000-00000000001c")
_LOAN_IH7_ABSENT = UUID("95000000-0000-4000-8000-00000000001d")
_LOAN_IH7_LOW_LIABILITY = UUID("95000000-0000-4000-8000-00000000001e")
_LOAN_IH7_NOT_CONDO = UUID("95000000-0000-4000-8000-00000000001f")
_LOAN_IH7_BASIS_UNREADABLE = UUID("95000000-0000-4000-8000-000000000020")
# LP-488 — MI-1 (conventional MI requirement) and the PROGRAM axis.
_LOAN_MI1_HIGH_LTV = UUID("95000000-0000-4000-8000-000000000021")
_LOAN_MI1_LOW_LTV = UUID("95000000-0000-4000-8000-000000000022")
_LOAN_MI1_FHA = UUID("95000000-0000-4000-8000-000000000023")
_LOAN_MI1_NO_PROGRAM = UUID("95000000-0000-4000-8000-000000000024")
_LOAN_MI1_NO_VALUE = UUID("95000000-0000-4000-8000-000000000025")
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
def _binder(cid: str, effective_date: str, *, settlement_basis: str | None = None) -> DocumentEntry:
    fields = {
        "carrier_name": "Rivertown Mutual",
        "policy_number": "RM-0001",
        "coverage_amount": "300000.00",
        "annual_premium": "1200.00",
        "effective_date": effective_date,
        "expiration_date": "2027-06-01",
    }
    # LP-447 — the dwelling loss-settlement basis (IH-1's input). Omitted by default so the IH-3 scenarios
    # (which read only the effective date) keep byte-identical contexts.
    if settlement_basis is not None:
        fields["replacement_cost_or_coinsurance_basis"] = settlement_basis
    return _doc(cid, "homeowners_insurance", **fields)


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


def build_insurance_two_basis_binders_snapshot() -> Snapshot:
    """TWO current binders with DIFFERENT dwelling settlement bases — one replacement cost, one actual cash
    value. IH-1 is per_document, so it judges EACH: SATISFIED on the RC binder AND FIRED on the ACV binder,
    on the same file (LP-447 review — pins the per-binder behavior; whether multiple binders should be
    reconciled to an operative policy is an OPEN Priya question, see IH-1.yaml)."""
    return _snapshot(
        _LOAN_INS_AMBIG,
        [
            _binder("95-binder-rc", "2026-06-01", settlement_basis="Replacement Cost"),
            _binder("95-binder-acv", "2026-06-01", settlement_basis="Actual Cash Value"),
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
# IH-1 (LP-447) — insurance adequacy: the binder's DWELLING loss-settlement basis. Each scenario carries a
# homeowners_insurance binder whose replacement_cost_or_coinsurance_basis field drives ins.dwelling_settlement_
# basis (the derived normalisation). IH-1 is per_document; no closing date needed (unlike IH-3).
# --------------------------------------------------------------------------- #
def build_insurance_replacement_cost_snapshot() -> Snapshot:
    """A binder stating a REPLACEMENT-COST dwelling basis (mixed casing, as real policies do) → IH-1 SATISFIED.
    The clean adequate case; also proves the normaliser folds 'Replacement Cost' → replacement_cost."""
    return _snapshot(
        _LOAN_INS_RC,
        [_binder("95-binder-rc", "2026-06-01", settlement_basis="Replacement Cost")],
    )


def build_insurance_acv_snapshot() -> Snapshot:
    """A binder stating an ACTUAL-CASH-VALUE dwelling basis → IH-1 FIRED (inadequate, a depreciated settlement)."""
    return _snapshot(
        _LOAN_INS_ACV,
        [_binder("95-binder-acv", "2026-06-01", settlement_basis="Actual Cash Value")],
    )


def build_insurance_unreadable_basis_snapshot() -> Snapshot:
    """A binder whose stated basis is NOT a recognised replacement-cost/actual-cash-value term → the normaliser
    abstains → ins.dwelling_settlement_basis "unknown" → IH-1 COULDNT_CHECK (fail closed, never a guessed pass)."""
    return _snapshot(
        _LOAN_INS_BASIS_UNREADABLE,
        [_binder("95-binder-basis-x", "2026-06-01", settlement_basis="see policy declarations")],
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


# --------------------------------------------------------------------------- #
# LP-419 #D5 — a SELF-EMPLOYED borrower (the IN-12 fire path). LP-393-1 found the income-scenario fixture is
# all-employment (income_stability does not read tax_returns, so IN-12's self-employment case is un-exercisable
# there). This standalone scenario gives ONE self-employed borrower with a tax return, so — once the income AI
# group perceives income.type == self_employment — the derived income.is_self_employed (LP-418) promotes to
# "yes" at the borrower, IN-12's applicability gate opens, and (with no 2-year history) IN-12 FIRES. Per-borrower
# → the tax_return is attributed (belongs_to) and the borrower has a MISMO id so BorrowerSubject enumerates it.
# --------------------------------------------------------------------------- #
def build_self_employed_no_history_snapshot() -> Snapshot:
    """One self-employed borrower: a tax_return (self-employment income) + a 1003, attributed to the borrower,
    with a MISMO borrower id. The documents carry NO tags of their own — the test materializes income.type ==
    self_employment (income AI group) and income.has_2yr_history == no (income_stability) via a stub, then the
    LP-418 derived income.is_self_employed promotes to "yes" and IN-12 FIRES (LP-419). Standalone (95… loan)."""
    ref = BorrowerRef(borrower_id=_SE_BORROWER, name="Sam Enterline")
    docs = [
        DocumentEntry(
            content_id="95-se-1040",
            document_type="tax_return",
            belongs_to=(ref,),
            fields={
                "tax_year": _f("2025"),
                "business_name": _f("Enterline Woodworks (Schedule C)"),
                "net_profit": _f("82000.00"),
            },
        ),
        DocumentEntry(
            content_id="95-se-1003",
            document_type="uniform_residential_loan_application",
            belongs_to=(ref,),
            fields={"employment_type": _f("self_employed")},
        ),
    ]
    return _snapshot(
        _LOAN_SELF_EMPLOYED,
        docs,
        {
            "borrower.1.borrower_id": _f(str(_SE_BORROWER)),
            "borrower.1.first_name": _f("Sam"),
        },
    )


# --------------------------------------------------------------------------- #
# LP-421 — a tax return carrying REAL nested Schedule C (self-employment) + Schedule E (rental, 2 properties),
# surfaced THROUGH the extraction→snapshot mapping (build_schedule_c / build_schedule_e). LP-419's stub baked
# FLAT fields (no schedules, materialized via a stub reasoner); this proves the two-level structure survives the
# real mapping into the snapshot — the input a future producer (IN-12 / IN-13's next ticket) would read.
# Standalone (95…), NOT LF-6T3N. The `extracted` dict below is the exact stored shape the tax-return extractor
# produces (each field a {value, source, confidence} TypedField dump).
# --------------------------------------------------------------------------- #
def build_tax_return_with_schedules_snapshot() -> Snapshot:
    """One borrower with a tax_return whose Schedule C (net_profit 82000) and Schedule E (2 properties, rents
    18000 / 9600) reach the snapshot via build_schedule_c / build_schedule_e — the LP-421 typed path proven end
    to end. The flat 1040 core (tax_year / filing_status) surfaces as ordinary fields, unchanged."""
    from app.verification.snapshot.documents_section import build_schedule_c, build_schedule_e

    extracted = {
        "tax_year": {"value": "2025", "source": None, "confidence": None},
        "filing_status": {"value": "single", "source": None, "confidence": None},
        "schedule_c": [
            {
                "business_name": {
                    "value": "Enterline Woodworks",
                    "source": None,
                    "confidence": 0.9,
                },
                "gross_receipts": {"value": "140000.00", "source": None, "confidence": None},
                "total_expenses": {"value": "58000.00", "source": None, "confidence": None},
                "net_profit": {"value": "82000.00", "source": None, "confidence": 0.9},
            }
        ],
        "schedule_e": {
            "total_net_rental_income": {"value": "21000.00", "source": None, "confidence": None},
            "depreciation": {"value": "6600.00", "source": None, "confidence": None},
            "properties": [
                {
                    "address": {
                        "value": "12 Oak St, Rivertown IL",
                        "source": None,
                        "confidence": None,
                    },
                    "rents_received": {"value": "18000.00", "source": None, "confidence": None},
                    "total_expenses": {"value": "7200.00", "source": None, "confidence": None},
                    "net_income": {"value": "10800.00", "source": None, "confidence": None},
                },
                {
                    "address": {
                        "value": "9 Elm Ave, Rivertown IL",
                        "source": None,
                        "confidence": None,
                    },
                    "rents_received": {"value": "9600.00", "source": None, "confidence": None},
                    "total_expenses": {"value": "3400.00", "source": None, "confidence": None},
                    "net_income": {"value": "6200.00", "source": None, "confidence": None},
                },
            ],
        },
    }
    ref = BorrowerRef(borrower_id=_SCHED_BORROWER, name="Sam Enterline")
    tax_doc = DocumentEntry(
        content_id="95-1040-sched",
        document_type="tax_return",
        belongs_to=(ref,),
        fields={"tax_year": _f("2025"), "filing_status": _f("single")},  # the flat core, unchanged
        schedule_c=build_schedule_c(extracted, "tax_return"),
        schedule_e=build_schedule_e(extracted, "tax_return"),
    )
    return _snapshot(
        _LOAN_SCHEDULES, [tax_doc], {"borrower.1.borrower_id": _f(str(_SCHED_BORROWER))}
    )


# --------------------------------------------------------------------------- #
# LP-430 — the TERMINATED-EMPLOYMENT documentation scenario (IN-15). Four borrowers, one per branch of
# Priya's B14 separate-documentation check (a PAST VOE end date requires a subsequent pay stub):
#   B1 (fire):    a VOE with a PAST end date (2026-05-01, before the 2026-07-01 file date), NO pay stub
#                 -> income.terminated_employment = needs_pay_stub -> IN-15 FIRES (asks for the pay stub).
#   B2 (satisfy): a past end date (2026-05-01) + a pay stub dated AFTER it (2026-06-15, any employer)
#                 -> cleared -> IN-15 satisfied.
#   B3 (n/a):     a VOE end date in the FUTURE (2027-01-01) -> not_terminated -> IN-15 not_applicable
#                 (a future end date is a continuation concern — IN-13's territory — not a termination).
#   B4 (n/a):     NO VOE, only a pay stub -> not_terminated -> IN-15 not_applicable (no past end date).
# Per-borrower attribution (belongs_to + MISMO ids) so BorrowerSubject enumerates four; B2's pay stub is
# attributed to B2 ONLY, so it can never clear B1's termination (the per-borrower isolation the recipe
# guarantees). VOE end dates -> income.employment_end (parsed); pay dates -> income.pay_date (parsed).
# --------------------------------------------------------------------------- #
def _terminated_borrower(i: int) -> UUID:
    return UUID(f"95000000-0000-4000-8000-0000000002{i:02d}")


def build_terminated_employment_snapshot() -> Snapshot:
    """Four borrowers exercising IN-15's branches (fire / satisfy / future-end n/a / no-VOE n/a). Standalone
    (95… namespace, its own loan). The file date is 2026-07-01, so 2026-05-01 is a PAST end date and
    2027-01-01 a FUTURE one. Materialize parsed + derived (no AI needed) to produce income.terminated_*."""
    docs: list[DocumentEntry] = []
    mismo: dict[str, SnapshotField] = {}
    for i in range(1, 5):
        bid = _terminated_borrower(i)
        mismo[f"borrower.{i}.borrower_id"] = _f(str(bid))
        mismo[f"borrower.{i}.first_name"] = _f(f"Borrower {i}")

    def _attr(cid: str, dtype: str, i: int, **fields: str) -> DocumentEntry:
        return DocumentEntry(
            content_id=cid,
            document_type=dtype,
            belongs_to=(BorrowerRef(borrower_id=_terminated_borrower(i), name=f"Borrower {i}"),),
            fields={k: _f(v) for k, v in fields.items()},
        )

    # B1 — FIRE: a past end date, no pay stub.
    docs.append(
        _attr(
            "95-voe-t1",
            "voe",
            1,
            employer_name="Acme Logistics",
            employee_name="Borrower 1",
            employment_status="former",
            start_date="2022-01-01",
            end_date="2026-05-01",
        )
    )
    # B2 — SATISFY: a past end date CLEARED by a pay stub dated after it (a NEW employer — the permissive read).
    docs.append(
        _attr(
            "95-voe-t2",
            "voe",
            2,
            employer_name="Beta Manufacturing",
            employee_name="Borrower 2",
            employment_status="former",
            start_date="2022-01-01",
            end_date="2026-05-01",
        )
    )
    docs.append(_attr("95-ps-t2", "pay_stub", 2, employer_name="Gamma Corp", pay_date="2026-06-15"))
    # B3 — NOT_APPLICABLE: a FUTURE end date (a fixed-term contract still running).
    docs.append(
        _attr(
            "95-voe-t3",
            "voe",
            3,
            employer_name="Delta Inc",
            employee_name="Borrower 3",
            employment_status="current",
            start_date="2022-01-01",
            end_date="2027-01-01",
        )
    )
    # B4 — NOT_APPLICABLE: no VOE at all, only a pay stub.
    docs.append(
        _attr("95-ps-t4", "pay_stub", 4, employer_name="Epsilon LLC", pay_date="2026-06-15")
    )
    return _snapshot(_LOAN_TERMINATED, docs, mismo)


# --------------------------------------------------------------------------- #
# LP-433 — the PAY-STUB-ONLY documentation scenario (IN-16). Four borrowers, one per branch of Priya's B12
# separate-documentation check (a 2-year history cannot rest on pay stubs alone — a W-2 or 1099 is required):
#   B1 (fire):    pay stubs only, no W-2 and no 1099 -> income.history_documentation = pay_stub_only -> IN-16
#                 FIRES (asks for a W-2 or 1099).
#   B2 (satisfy): a W-2 attributed -> w2_or_1099 -> IN-16 satisfied.
#   B3 (satisfy): a 1099 attributed (NO W-2) -> w2_or_1099 -> IN-16 satisfied (proves the "or 1099" leg).
#   B4 (n/a):     a VOE only, no pay stubs / W-2 / 1099 -> no_pay_stubs -> IN-16 not_applicable (a VOE-only
#                 borrower is out of scope — her ruling is about pay-stub-only history; NOT broadened to accept
#                 the VOE, and NOT fired since there is no pay-stub history to challenge).
# Per-borrower attribution (belongs_to + MISMO ids) so BorrowerSubject enumerates four; B2's W-2 is attributed
# to B2 ONLY, so it never satisfies B1 (the per-borrower isolation the recipe guarantees). Document-type
# PRESENCE only — no extracted-field dependency (the IN-8/IN-9 discipline).
# --------------------------------------------------------------------------- #
def _pay_stub_only_borrower(i: int) -> UUID:
    return UUID(f"95000000-0000-4000-8000-0000000003{i:02d}")


def build_pay_stub_only_snapshot() -> Snapshot:
    """Four borrowers exercising IN-16's branches (fire / W-2 satisfy / 1099 satisfy / VOE-only n/a). Standalone
    (95… namespace, its own loan). Materialize the derived producer (no AI needed) to produce
    income.history_documentation; IN-16 reads it per borrower."""
    docs: list[DocumentEntry] = []
    mismo: dict[str, SnapshotField] = {}
    for i in range(1, 5):
        bid = _pay_stub_only_borrower(i)
        mismo[f"borrower.{i}.borrower_id"] = _f(str(bid))
        mismo[f"borrower.{i}.first_name"] = _f(f"Borrower {i}")

    def _attr(cid: str, dtype: str, i: int, **fields: str) -> DocumentEntry:
        return DocumentEntry(
            content_id=cid,
            document_type=dtype,
            belongs_to=(BorrowerRef(borrower_id=_pay_stub_only_borrower(i), name=f"Borrower {i}"),),
            fields={k: _f(v) for k, v in fields.items()},
        )

    # B1 — FIRE: pay stubs only (no W-2, no 1099).
    docs.append(
        _attr("95-ps-p1", "pay_stub", 1, employer_name="Acme Freight", pay_date="2026-06-15")
    )
    docs.append(
        _attr("95-ps-p1b", "pay_stub", 1, employer_name="Acme Freight", pay_date="2026-05-15")
    )
    # B2 — SATISFY (W-2): a W-2 documents the history.
    docs.append(_attr("95-w2-p2", "w2", 2, employer_name="Beta Manufacturing", tax_year="2025"))
    # B3 — SATISFY (1099): a 1099, no W-2 — the "or 1099" leg.
    docs.append(_attr("95-1099-p3", "1099", 3, payer_name="Gamma Contracting", tax_year="2025"))
    # B4 — NOT_APPLICABLE: a VOE only (no pay stubs / W-2 / 1099).
    docs.append(
        _attr("95-voe-p4", "voe", 4, employer_name="Delta Inc", employment_status="current")
    )
    return _snapshot(_LOAN_PAY_STUB_ONLY, docs, mismo)


# The expected fired/materialized outcomes — recorded HERE / in tests, never predicted in prose (LP-337).
EXPECTED_TAXES_MONTHLY = "500.00"  # 6000 / 12
EXPECTED_HOA_MONTHLY = "300.00"  # 300 monthly
EXPECTED_INS_EFFECTIVE_IN_FORCE = "2026-06-01"  # <= 2026-07-15 closing → satisfied
EXPECTED_INS_EFFECTIVE_LATE = "2026-08-15"  # > 2026-07-15 closing → fired
EXPECTED_INS_BASIS_RC = (
    "replacement_cost"  # LP-447 — "Replacement Cost" normalises here → IH-1 satisfied
)
EXPECTED_INS_BASIS_ACV = "actual_cash_value"  # LP-447 — "Actual Cash Value" → IH-1 fired


# --------------------------------------------------------------------------- #
# LP-487 — IH-2 (mortgagee clause). Each scenario carries a homeowners binder (its mortgagee_name) plus a
# closing document stating this loan's lender. ⚠️ THE MORTGAGEE NAMES ARE THE REAL CORPUS FORMS — the
# ISAOA/ATIMA and c/o variants are what carriers actually print, not invented shapes.
# --------------------------------------------------------------------------- #
def _mortgagee_binder(cid: str, mortgagee_name: str | None) -> DocumentEntry:
    fields = {
        "carrier_name": "Rivertown Mutual",
        "policy_number": "RM-0001",
        "effective_date": "2026-06-01",
        "expiration_date": "2027-06-01",
    }
    if mortgagee_name is not None:
        fields["mortgagee_name"] = mortgagee_name
    return _doc(cid, "homeowners_insurance", **fields)


def _closing_disclosure(cid: str, lender_name: str) -> DocumentEntry:
    return _doc(cid, "closing_disclosure", lender_name=lender_name, closing_date="2026-07-15")


def build_ih2_clause_matches_snapshot() -> Snapshot:
    """The clause names the lender, in the carrier's ISAOA form → IH-2 SATISFIED. The variance the
    normaliser exists for: "United Wholesale Mortgage, LLC ISAOA" vs the CD's "United Wholesale
    Mortgage, LLC"."""
    return _snapshot(
        _LOAN_IH2_MATCH,
        [
            _mortgagee_binder("95-binder-ih2-ok", "United Wholesale Mortgage, LLC ISAOA"),
            _closing_disclosure("95-cd-ih2-ok", "United Wholesale Mortgage, LLC"),
        ],
    )


def build_ih2_clause_mismatch_snapshot() -> Snapshot:
    """THE CORRESPONDENT CASE, from the corpus: the CD names "Sistar Mortgage Company" and the clause
    names "United Wholesale Mortgage". Both may be correct → IH-2 NEEDS_REVIEW, never fired."""
    return _snapshot(
        _LOAN_IH2_MISMATCH,
        [
            _mortgagee_binder("95-binder-ih2-x", "United Wholesale Mortgage"),
            _closing_disclosure("95-cd-ih2-x", "Sistar Mortgage Company"),
        ],
    )


def build_ih2_no_lender_snapshot() -> Snapshot:
    """A binder with a mortgagee but NO closing document stating a lender → nothing to compare against →
    IH-2 COULDNT_CHECK (never a guessed match)."""
    return _snapshot(
        _LOAN_IH2_NO_LENDER,
        [_mortgagee_binder("95-binder-ih2-nolender", "United Wholesale Mortgage")],
    )


def build_ih2_loan_estimate_only_snapshot() -> Snapshot:
    """No Closing Disclosure yet — the Loan Estimate is the FALLBACK, so a file early in processing is
    still checkable → IH-2 SATISFIED."""
    return _snapshot(
        _LOAN_IH2_LE_ONLY,
        [
            _mortgagee_binder("95-binder-ih2-le", "ROCKET MORTGAGE, LLC."),
            _doc("95-le-ih2", "loan_estimate", lender_name="Rocket Mortgage, LLC"),
        ],
    )


# --------------------------------------------------------------------------- #
# LP-487 — IH-7 (condo master policy). The property type comes from MISMO (property.type, the
# PropertyType enum), the master policy from a master_insurance_policy_for_condominium document.
# ⚠️ THE BASIS STRINGS ARE THE REAL CORPUS FORMS — free prose, not codes.
# --------------------------------------------------------------------------- #
def _master_policy(cid: str, *, basis: str | None, liability: str | None) -> DocumentEntry:
    fields = {
        "insurance_carrier": "Rivertown Commercial",
        "policy_number": "MP-0001",
        "condominium_project_name": "Birch Court Condominiums",
    }
    if basis is not None:
        fields["replacement_cost_indicator"] = basis
    if liability is not None:
        fields["general_liability_each_occurrence_limit"] = liability
    return _doc(cid, "master_insurance_policy_for_condominium", **fields)


def build_ih7_adequate_snapshot() -> Snapshot:
    """A condo with a master policy on a replacement-cost basis and $2M liability → IH-7 SATISFIED. The
    basis string is the corpus's longest real form, which an EXACT-match vocabulary would abstain on."""
    return _snapshot(
        _LOAN_IH7_ADEQUATE,
        [
            _master_policy(
                "95-mp-ok",
                basis="REPLACEMENT COST AT AGREED VALUE WITH NO CO-INSURANCE",
                liability="2000000",
            )
        ],
        {"property.type": _f("condo")},
    )


def build_ih7_absent_snapshot() -> Snapshot:
    """A condo with NO master policy in the file → IH-7 FIRED (a real, actionable gap)."""
    return _snapshot(_LOAN_IH7_ABSENT, [], {"property.type": _f("condo")})


def build_ih7_low_liability_snapshot() -> Snapshot:
    """A condo master policy with only $500k general liability — below B7-4-01's $1M floor → IH-7 FIRED."""
    return _snapshot(
        _LOAN_IH7_LOW_LIABILITY,
        [_master_policy("95-mp-low", basis="Replacement Cost", liability="500000")],
        {"property.type": _f("condo")},
    )


def build_ih7_not_condo_snapshot() -> Snapshot:
    """A single-family property → IH-7 NOT_APPLICABLE (no master policy is required)."""
    return _snapshot(_LOAN_IH7_NOT_CONDO, [], {"property.type": _f("single_family")})


def build_ih7_unreadable_basis_snapshot() -> Snapshot:
    """A condo master policy whose coverage basis is not a recognised term → IH-7 COULDNT_CHECK. Fail
    closed: an unrecognised basis is NEVER read as inadequate, and never as adequate."""
    return _snapshot(
        _LOAN_IH7_BASIS_UNREADABLE,
        [_master_policy("95-mp-x", basis="Special Form — see schedule", liability="2000000")],
        {"property.type": _f("condo")},
    )


# --------------------------------------------------------------------------- #
# LP-488 — MI-1. The PROGRAM AXIS's first use: `program.type` is an APPLICABILITY PREDICATE, so an FHA
# file is not_applicable and a file stating NO program is couldnt_check (never silently skipped).
# All facts are MISMO: loan.program, loan.amount (BaseLoanAmount), property.purchase_price.
# --------------------------------------------------------------------------- #
def _mi_mismo(
    *, program: str | None, base_loan: str | None, purchase_price: str | None
) -> dict[str, SnapshotField]:
    facts: dict[str, SnapshotField] = {"loan.purpose": _f("purchase")}
    if program is not None:
        facts["loan.program"] = _f(program)
    if base_loan is not None:
        facts["loan.amount"] = _f(base_loan)
    if purchase_price is not None:
        facts["property.purchase_price"] = _f(purchase_price)
    return facts


def build_mi1_high_ltv_snapshot() -> Snapshot:
    """Conventional, $340,000 on a $400,000 purchase = 85% LTV → MI-1 NEEDS_REVIEW (MI is required).
    ⚠️ NOT fired — MI-1 cannot see whether an MI certificate is in the file."""
    return _snapshot(
        _LOAN_MI1_HIGH_LTV,
        [],
        _mi_mismo(program="conventional", base_loan="340000.00", purchase_price="400000.00"),
    )


def build_mi1_low_ltv_snapshot() -> Snapshot:
    """Conventional, $300,000 on a $400,000 purchase = 75% LTV → MI-1 SATISFIED (no MI required)."""
    return _snapshot(
        _LOAN_MI1_LOW_LTV,
        [],
        _mi_mismo(program="conventional", base_loan="300000.00", purchase_price="400000.00"),
    )


def build_mi1_fha_snapshot() -> Snapshot:
    """⚠️ THE PROGRAM-SCOPING PROOF, FHA side. An 85% LTV that WOULD trip MI-1 on a conventional file —
    but the program is FHA, so MI-1 is NOT_APPLICABLE and never fires. MI-4 covers FHA."""
    return _snapshot(
        _LOAN_MI1_FHA,
        [],
        _mi_mismo(program="fha", base_loan="340000.00", purchase_price="400000.00"),
    )


def build_mi1_no_program_snapshot() -> Snapshot:
    """⚠️ THE PROGRAM-SCOPING PROOF, absent side. The same 85% LTV with NO stated program →
    COULDNT_CHECK, never silently skipped. This is why the scoping is a predicate, not an outcome."""
    return _snapshot(
        _LOAN_MI1_NO_PROGRAM,
        [],
        _mi_mismo(program=None, base_loan="340000.00", purchase_price="400000.00"),
    )


def build_mi1_no_value_snapshot() -> Snapshot:
    """Conventional with a loan amount but NO purchase price and no appraisal → no value basis → the LTV
    abstains → MI-1 COULDNT_CHECK. Never satisfied on a missing value."""
    return _snapshot(
        _LOAN_MI1_NO_VALUE,
        [],
        _mi_mismo(program="conventional", base_loan="340000.00", purchase_price=None),
    )


__all__ = [
    "EXPECTED_HOA_MONTHLY",
    "EXPECTED_INS_BASIS_ACV",
    "EXPECTED_INS_BASIS_RC",
    "EXPECTED_INS_EFFECTIVE_IN_FORCE",
    "EXPECTED_INS_EFFECTIVE_LATE",
    "EXPECTED_TAXES_MONTHLY",
    "build_address_abbrev_snapshot",
    "build_address_mailing_only_snapshot",
    "build_address_match_snapshot",
    "build_address_mismatch_snapshot",
    "build_address_unit_variant_snapshot",
    "build_far_future_closing_snapshot",
    "build_ih2_clause_matches_snapshot",
    "build_ih2_clause_mismatch_snapshot",
    "build_ih2_loan_estimate_only_snapshot",
    "build_ih2_no_lender_snapshot",
    "build_ih7_absent_snapshot",
    "build_ih7_adequate_snapshot",
    "build_ih7_low_liability_snapshot",
    "build_ih7_not_condo_snapshot",
    "build_ih7_unreadable_basis_snapshot",
    "build_insurance_acv_snapshot",
    "build_insurance_binder_plus_decree_snapshot",
    "build_insurance_decree_only_snapshot",
    "build_insurance_in_force_snapshot",
    "build_insurance_late_snapshot",
    "build_insurance_replacement_cost_snapshot",
    "build_insurance_two_binder_snapshot",
    "build_insurance_unreadable_basis_snapshot",
    "build_mi1_fha_snapshot",
    "build_mi1_high_ltv_snapshot",
    "build_mi1_low_ltv_snapshot",
    "build_mi1_no_program_snapshot",
    "build_mi1_no_value_snapshot",
    "build_other_income_continuance_snapshot",
    "build_past_closing_snapshot",
    "build_pay_stub_only_snapshot",
    "build_self_employed_no_history_snapshot",
    "build_statement_break_snapshot",
    "build_subject_housing_snapshot",
    "build_tax_return_with_schedules_snapshot",
    "build_terminated_employment_snapshot",
    "build_voe_offer_labeling_snapshot",
]

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
    DocumentEntry,
    DocumentsSection,
    MismoSection,
    Snapshot,
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


def _snapshot(loan_id: UUID, docs: list[DocumentEntry]) -> Snapshot:
    return Snapshot(
        loan_file_id=loan_id,
        run_id=_RUN,
        created_at=_FILE_DATE,
        documents=DocumentsSection.present(docs),
        mismo=MismoSection.present({}),
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
    "build_far_future_closing_snapshot",
    "build_insurance_binder_plus_decree_snapshot",
    "build_insurance_decree_only_snapshot",
    "build_insurance_in_force_snapshot",
    "build_insurance_late_snapshot",
    "build_insurance_two_binder_snapshot",
    "build_past_closing_snapshot",
    "build_statement_break_snapshot",
    "build_subject_housing_snapshot",
]

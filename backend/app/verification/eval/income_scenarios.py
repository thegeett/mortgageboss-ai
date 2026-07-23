"""LP-393-1 — the STANDALONE income-scenario snapshot builder (Level 1: synthetic data structures, not PDFs).

Six rules (IN-7, IN-10, IN-11, IN-12, IN-13, AS-11) are blocked purely on SAMPLE SIZE: their tags are
per-borrower and LF-6T3N has only 2 borrowers, so each caps at n=2 (AS-11 at n=3) — a smoke test, not a
measurement (LP-390-5/6, confirmed on real data by LP-392). The ceiling is the FILE, not the code: the wiring
is fixed (LP-385/390-1) and the tags produce; it is a DATA problem.

This builds ~11 scenario borrowers (+ asset accounts) so the per-borrower income tags and asset.liquidation_terms
reach n>=6 and can actually be calibrated. It measures the AI's REASONING about income scenarios — which is what
is blocked; document EXTRACTION is separately calibrated (documented_monthly / employer_normalized both 100%),
so re-testing it via fake PDFs would buy nothing (ADR: why Level 1).

⚠️ COMPLETELY SEPARATE FROM LF-6T3N (the realism anchor). Own loan id / borrower ids / content-ids — NO
collision. This module NEVER imports the LF-6T3N builders and they never import it (asserted both ways); merging
scenario borrowers into LF-6T3N would destroy its realism and break its frozen tests. The two fixtures answer
different questions: LF-6T3N = "do rules work on realistic data"; this = "scenario variety for measurement".

⚠️ MINIMUM DOCUMENTS PER SCENARIO — each borrower carries ONLY the documents its scenario needs (a decline test
carries 2 W-2s; no bank statement, no DL, no MISMO beyond the borrower id). Extra documents are cost + noise.

⚠️ ANTI-ANCHORING (LP-337) — the AMBIGUOUS scenarios carry NO encoded expected answer anywhere a labeling
worksheet could surface it. The clear-cut expectations live HERE (``CLEARCUT_EXPECTATIONS``) for the probe/tests
+ the doc — never written into a worksheet (that is LP-393-2/3, and Priya labels the ambiguous cases blind).

The income_stability group (LP-385) reads, per borrower: its MISMO facts + attributed w2/pay_stub/voe/1003
documents (``subjects._borrower_context``). It reasons over ``tax_year`` + ``wages_tips_other_comp`` (history /
decline), ``employer_name`` + the role (same_line_of_work), and a stated income END (continuance_3yr). The
scenarios vary EXACTLY those fields (D2, verified against the prompt, not assumed).
"""

from __future__ import annotations

from dataclasses import dataclass, field
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

# --------------------------------------------------------------------------- #
# Own id namespace — the "93…" prefix, deliberately DISJOINT from LF-6T3N's borrower ids
# (11111111…/22222222…) and its content-ids. The separation is asserted in the tests both ways.
# --------------------------------------------------------------------------- #
_LOAN_ID = UUID("93000000-0000-4000-8000-000000000000")
_RUN_ID = UUID("93000000-0000-4000-8000-0000000000ff")
_CREATED = datetime(2026, 7, 23, tzinfo=UTC)


def _borrower_uuid(n: int) -> UUID:
    # a stable, LF-6T3N-disjoint borrower id per scenario number (B3..B15 -> 03..15)
    return UUID(f"93000000-0000-4000-8000-0000000000{n:02d}")


def _f(value: str) -> Field:
    return Field.present(value, source=FieldSource.EXTRACTED)


@dataclass(frozen=True)
class _Doc:
    """One scenario document — a document_type + its fields (all sent to the AI verbatim)."""

    dtype: str
    fields: dict[str, str]


@dataclass(frozen=True)
class _Scenario:
    """One scenario borrower: its number (B{n}), the tag it primarily exercises, its minimum documents, and —
    for a CLEAR-CUT case only — the expected tag values (recorded here for the probe/tests, NEVER a worksheet).
    An AMBIGUOUS case leaves ``expected`` empty: Priya labels it blind (her label becomes the definition)."""

    n: int
    label: str
    primary_tag: str
    docs: tuple[_Doc, ...]
    expected: dict[str, str] = field(
        default_factory=dict
    )  # {tag: value} — clear-cut only; NEVER anchored


def _w2(*, year: str, employer: str, wages: str, occupation: str | None = None) -> _Doc:
    fields = {"tax_year": year, "employer_name": employer, "wages_tips_other_comp": wages}
    if occupation is not None:
        fields["occupation"] = (
            occupation  # the role signal for same_line_of_work (context sends all fields)
        )
    return _Doc("w2", fields)


def _voe(
    *, employer: str, start: str, end: str | None = None, occupation: str | None = None
) -> _Doc:
    fields = {"employer_name": employer, "start_date": start}
    if end is not None:
        fields["end_date"] = (
            end  # a STATED income end — the only signal continuance_3yr can read (D4)
        )
    if occupation is not None:
        fields["occupation"] = occupation
    return _Doc("voe", fields)


# --------------------------------------------------------------------------- #
# THE SCENARIO MATRIX (the ticket's B3..B13 + D4's continuance probes B14/B15)
# --------------------------------------------------------------------------- #
_SCENARIOS: tuple[_Scenario, ...] = (
    # ----- CLEAR-CUT: the expected answer is known (proves the tag CATCHES what it should) -----
    _Scenario(
        3,
        "declining income (same employer)",
        "income.is_declining",
        (
            _w2(year="2024", employer="Acme Freight Co", wages="80000"),
            _w2(year="2025", employer="Acme Freight Co", wages="60000"),
        ),
        {"income.is_declining": "yes"},
    ),
    _Scenario(
        4,
        "rising income (same employer)",
        "income.is_declining",
        (
            _w2(year="2024", employer="Acme Freight Co", wages="60000"),
            _w2(year="2025", employer="Acme Freight Co", wages="75000"),
        ),
        {"income.is_declining": "no"},
    ),
    _Scenario(
        5,
        "one year only",
        "income.has_2yr_history",
        (_w2(year="2025", employer="Bright Retail LLC", wages="52000"),),
        {"income.has_2yr_history": "no"},
    ),
    _Scenario(
        6,
        "three consecutive years (same employer)",
        "income.has_2yr_history",
        (
            _w2(year="2023", employer="Cedar Manufacturing", wages="58000"),
            _w2(year="2024", employer="Cedar Manufacturing", wages="60000"),
            _w2(year="2025", employer="Cedar Manufacturing", wages="61500"),
        ),
        {"income.has_2yr_history": "yes"},
    ),
    _Scenario(
        7,
        "nurse -> nurse, employer change",
        "income.same_line_of_work",
        (
            _w2(
                year="2024",
                employer="Springfield General Hospital",
                wages="72000",
                occupation="Registered Nurse",
            ),
            _w2(
                year="2025",
                employer="Riverside Medical Center",
                wages="74000",
                occupation="Registered Nurse",
            ),
        ),
        {"income.same_line_of_work": "yes"},
    ),
    _Scenario(
        8,
        "warehouse -> office, career change",
        "income.same_line_of_work",
        (
            _w2(
                year="2024",
                employer="Pioneer Distribution",
                wages="45000",
                occupation="Warehouse Picker",
            ),
            _w2(
                year="2025",
                employer="Delta Business Services",
                wages="48000",
                occupation="Office Administrator",
            ),
        ),
        {"income.same_line_of_work": "no"},
    ),
    # ----- AMBIGUOUS: built but NOT pre-answered (Priya labels blind; her label becomes the definition) -----
    _Scenario(
        9,
        "small 2% drop",
        "income.is_declining",
        (
            _w2(year="2024", employer="Harbor Foods Inc", wages="70000"),
            _w2(year="2025", employer="Harbor Foods Inc", wages="68500"),
        ),
    ),
    _Scenario(
        10,
        "18 months of history (mid-2024 start)",
        "income.has_2yr_history",
        (
            _voe(employer="Lakeside Systems", start="2024-07-01"),
            _w2(year="2025", employer="Lakeside Systems", wages="63000"),
        ),
    ),
    _Scenario(
        11,
        "retail cashier -> retail supervisor (promotion)",
        "income.same_line_of_work",
        (
            _w2(year="2024", employer="Summit Stores", wages="38000", occupation="Retail Cashier"),
            _w2(
                year="2025", employer="Summit Stores", wages="46000", occupation="Retail Supervisor"
            ),
        ),
    ),
    _Scenario(
        12,
        "base down, bonus up, total flat",
        "income.is_declining",
        (
            _Doc(
                "pay_stub",
                {
                    "tax_year": "2024",
                    "employer_name": "Vertex Capital",
                    "base_salary": "90000",
                    "bonus": "10000",
                    "wages_tips_other_comp": "100000",
                },
            ),
            _Doc(
                "pay_stub",
                {
                    "tax_year": "2025",
                    "employer_name": "Vertex Capital",
                    "base_salary": "78000",
                    "bonus": "22000",
                    "wages_tips_other_comp": "100000",
                },
            ),
        ),
    ),
    _Scenario(
        13,
        "two full years, two different employers",
        "income.has_2yr_history",
        (
            _w2(year="2024", employer="Northwind Logistics", wages="64000"),
            _w2(year="2025", employer="Crestline Freight", wages="66000"),
        ),
    ),
    # ----- D4: continuance_3yr probes — a STATED income end is the only thing continuance_3yr can read.
    #       Standard W-2 employment honestly yields "unknown" (LP-385); these give the tag a real (if narrow) n.
    _Scenario(
        14,
        "fixed-term contract ending within 3 years",
        "income.continuance_3yr",
        (
            _voe(
                employer="Beacon Contract Staffing",
                start="2024-07-01",
                end="2026-06-30",
                occupation="Project Analyst",
            ),
            _w2(year="2024", employer="Beacon Contract Staffing", wages="70000"),
            _w2(year="2025", employer="Beacon Contract Staffing", wages="71000"),
        ),
    ),
    _Scenario(
        15,
        "open-ended employment (no stated end)",
        "income.continuance_3yr",
        (
            _voe(
                employer="Evergreen Utilities",
                start="2019-03-01",
                occupation="Operations Specialist",
            ),
            _w2(year="2024", employer="Evergreen Utilities", wages="82000"),
            _w2(year="2025", employer="Evergreen Utilities", wages="84000"),
        ),
    ),
)


# --------------------------------------------------------------------------- #
# THE ASSET ACCOUNTS (AS-11 asset.liquidation_terms) — 6 documents so the tag reaches n>=6 STANDALONE (this
# fixture never merges with LF-6T3N's 3 assets). Fields mirror the LF-6T3N asset-doc shape (institution / type /
# values / vesting) so asset_facts reasons over the same signals. A 401(k) vesting schedule + a Roth (Priya
# disagreed with the AI on a Roth in LP-390-5) exercise the judgment.
# --------------------------------------------------------------------------- #
_ASSET_DOCS: tuple[_Doc, ...] = (
    _Doc(
        "brokerage_statement",
        {
            "institution_name": "Vanguard",
            "account_type": "brokerage",
            "total_value": "120000.00",
            "vested_balance": "120000.00",
        },
    ),
    _Doc(
        "brokerage_statement",
        {
            "institution_name": "Fidelity",
            "account_type": "brokerage",
            "total_value": "64500.00",
            "vested_balance": "64500.00",
        },
    ),
    _Doc(
        "retirement_account",
        {
            "institution_name": "Empower 401(k)",
            "account_type": "401k",
            "total_value": "150000.00",
            "vested_balance": "90000.00",
            "vesting_schedule": "60% vested (graded, 6-year)",
        },
    ),
    _Doc(
        "retirement_account",
        {
            "institution_name": "Principal 401(k)",
            "account_type": "401k",
            "total_value": "80000.00",
            "vested_balance": "80000.00",
            "vesting_schedule": "100% vested",
        },
    ),
    _Doc(
        "retirement_account",
        {
            "institution_name": "Schwab Roth IRA",
            "account_type": "roth_ira",
            "total_value": "41500.00",
            "vested_balance": "41500.00",
        },
    ),
    _Doc(
        "investment_account",
        {
            "institution_name": "Betterment Roth IRA",
            "account_type": "roth_ira",
            "total_value": "28000.00",
            "vested_balance": "28000.00",
        },
    ),
)


def _document_entries() -> list[DocumentEntry]:
    entries: list[DocumentEntry] = []
    for sc in _SCENARIOS:
        ref = BorrowerRef(borrower_id=_borrower_uuid(sc.n), name=f"Scenario B{sc.n}")
        for i, doc in enumerate(sc.docs, start=1):
            entries.append(
                DocumentEntry(
                    content_id=f"inc-b{sc.n}-{doc.dtype}-{i}",  # 93-namespace content-id, no LF-6T3N collision
                    document_type=doc.dtype,
                    belongs_to=(ref,),
                    fields={k: _f(v) for k, v in doc.fields.items()},
                )
            )
    for i, doc in enumerate(_ASSET_DOCS, start=1):
        entries.append(
            DocumentEntry(
                content_id=f"inc-asset-{i}",
                document_type=doc.dtype,
                belongs_to=None,  # asset_facts is per-DOCUMENT — no borrower attribution needed
                fields={k: _f(v) for k, v in doc.fields.items()},
            )
        )
    return entries


def _borrower_mismo() -> dict[str, SnapshotField]:
    # the MINIMUM viable borrower (D1): just the borrower_id link the per-borrower enumerator reads — no
    # employer/income MISMO (the scenario's DOCUMENTS carry the income signals).
    mismo: dict[str, SnapshotField] = {}
    for i, sc in enumerate(_SCENARIOS, start=1):
        mismo[f"borrower.{i}.borrower_id"] = _f(str(_borrower_uuid(sc.n)))
    return mismo


def build_income_calibration_snapshot() -> Snapshot:
    """The standalone income-scenario snapshot: ~11 scenario borrowers (+ D4 continuance probes) and 6 asset
    accounts, each built to the MINIMUM viable structure for the tag it exercises. Deterministic, keyless,
    and DISJOINT from LF-6T3N (own loan/borrower/content ids). Never merged into the LF-6T3N builders."""
    return Snapshot(
        loan_file_id=_LOAN_ID,
        run_id=_RUN_ID,
        created_at=_CREATED,
        documents=DocumentsSection.present(_document_entries()),
        mismo=MismoSection.present(_borrower_mismo()),
        tags=TagsSection.present({}),
    )


# The clear-cut expectations for the probe + tests (NEVER written to a worksheet — LP-337 anti-anchoring).
CLEARCUT_EXPECTATIONS: dict[int, dict[str, str]] = {
    sc.n: dict(sc.expected) for sc in _SCENARIOS if sc.expected
}

# The scenario borrower ids, for the separation assertion (disjoint from LF-6T3N).
SCENARIO_BORROWER_IDS: frozenset[str] = frozenset(str(_borrower_uuid(sc.n)) for sc in _SCENARIOS)

__all__ = [
    "CLEARCUT_EXPECTATIONS",
    "SCENARIO_BORROWER_IDS",
    "build_income_calibration_snapshot",
]

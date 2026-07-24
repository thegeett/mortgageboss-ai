"""LP-398 — the NEGATIVE-case scenario fixture for ``stmt.owner_matches_borrower`` (AS-6).

LP-390-8a made the tag produce, but every golden was ``yes`` — the tag had only ever seen statements that DO
belong to a borrower. AS-6 exists to catch the OPPOSITE: a statement that does NOT belong to the borrower (the
dangerous FN direction — someone else's assets accepted as the borrower's). This builds that untested direction:
6 negative statements (each resembling a borrower in a specific way, to probe exactly where LP-390-8a's TOLERANT
matching becomes wrong) plus 2 positive controls (so a future score covers BOTH directions and a strictness
regression false-flagging a borrower's own account is caught).

Standalone, per the LP-393-1 pattern: own loan/borrower/content ids (the ``94…`` namespace, disjoint from
LF-6T3N's ``1111…/2222…`` and the income fixture's ``93…``); never merged into, never imported by, either. The
MISMO wires two borrowers WITH NAMES so the LP-390-8a roster (``loan_borrower_roster`` reads
``borrower.{n}.first/middle/last_name``) is non-empty — an empty roster would make every case abstain (the
LP-379-B trap), rendering the probe meaningless.

The clear-cut expectations (N2/N3/N4/N6 → ``no``; P1/P2 → ``yes``) live HERE, never in a worksheet. The two
AMBIGUOUS cases — N1 (a DIFFERENT middle initial: a relative, or tolerable variation?) and N5 (a joint account
with a non-borrower co-holder) — carry NO expected answer: Priya labels them blind and her label is the
definition (anti-anchoring, LP-337).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    DocumentEntry,
    DocumentsSection,
    MismoSection,
    Snapshot,
    SnapshotField,
    TagsSection,
)

# --------------------------------------------------------------------------- #
# Own id namespace — the "94…" prefix, disjoint from LF-6T3N (1111…/2222…) and the income fixture (93…).
# --------------------------------------------------------------------------- #
_LOAN_ID = UUID("94000000-0000-4000-8000-000000000000")
_RUN_ID = UUID("94000000-0000-4000-8000-0000000000ff")
_CREATED = datetime(2026, 7, 23, tzinfo=UTC)
_B1 = UUID(
    "94000000-0000-4000-8000-000000000001"
)  # Jordan A Rivera (the middle initial matters for N1/P1)
_B2 = UUID(
    "94000000-0000-4000-8000-000000000002"
)  # Robert Chen (for the nickname/one-letter cases N2/P2)


def _f(value: str) -> Field:
    return Field.present(value, source=FieldSource.EXTRACTED)


@dataclass(frozen=True)
class OwnerCase:
    """One statement: its account holder, the tolerance CLAUSE it probes, and — for a CLEAR-CUT case only — the
    expected ``owner_matches_borrower`` value. ``expected=None`` marks an AMBIGUOUS case Priya labels blind."""

    key: str  # N1..N6 / P1 / P2
    holder: str  # the account_holder_name on the statement
    probes: str  # the LP-390-8a tolerance clause this tests (D3) — a description, NOT an answer
    expected: str | None  # "yes" | "no" (clear-cut), or None (ambiguous — never anchored)


# The two borrowers on the loan (the comparison roster): Jordan A Rivera + Robert Chen.
_ROSTER = {
    _B1: ("Jordan", "A", "Rivera"),
    _B2: ("Robert", "", "Chen"),
}

# 6 negatives (resembling a borrower in one specific way) + 2 positive controls.
_CASES: tuple[OwnerCase, ...] = (
    # AMBIGUOUS — a DIFFERENT middle initial (M vs the borrower's A): a relative, or tolerable variation? The
    # sharpest case; the middle-name tolerance clause is exactly what could swallow it. Priya's call.
    OwnerCase(
        "N1", "Jordan M Rivera", "middle-name clause: a DIFFERENT middle initial (M vs A)", None
    ),
    # CLEAR-CUT no — Roberta is a different given name than Robert (one letter, a different person).
    OwnerCase("N2", "Roberta Chen", "nickname/variant clause: Roberta is NOT Robert", "no"),
    # CLEAR-CUT no — a name-containing TRUST is a different legal entity, not the person.
    OwnerCase("N3", "The Rivera Family Trust", "entity clause: a name-containing trust", "no"),
    # CLEAR-CUT no — a completely unrelated name; the sanity check. If this matches, tolerance is badly broken.
    OwnerCase("N4", "Marcus Whitfield", "the sanity check: a completely unrelated name", "no"),
    # AMBIGUOUS — a JOINT account listing a borrower (Jordan Rivera) AND a non-borrower (Marcus Whitfield). The
    # "match if EITHER is a borrower" rule says yes; should a non-borrower co-holder be flagged instead? Priya's.
    OwnerCase(
        "N5", "JORDAN RIVERA AND MARCUS WHITFIELD", "joint clause: a non-borrower co-holder", None
    ),
    # CLEAR-CUT no — a business entity (LLC), not the personal borrower.
    OwnerCase("N6", "Rivera Holdings LLC", "entity clause: a business LLC", "no"),
    # CLEAR-CUT yes (control) — the benign middle-DROP variant already known to work; guards over-correction.
    OwnerCase(
        "P1",
        "Jordan Rivera",
        "control: benign middle-drop (Jordan Rivera vs Jordan A Rivera)",
        "yes",
    ),
    # CLEAR-CUT yes (control) — a nickname the tolerance SHOULD accept; guards over-strictness.
    OwnerCase("P2", "Bob Chen", "control: nickname (Bob = Robert)", "yes"),
)

# The clear-cut expectations — recorded HERE / in tests only, NEVER a worksheet (anti-anchoring, LP-337).
CLEARCUT_EXPECTATIONS: dict[str, str] = {
    c.key: c.expected for c in _CASES if c.expected is not None
}
AMBIGUOUS_CASES: tuple[str, ...] = tuple(c.key for c in _CASES if c.expected is None)  # N1, N5


def _roster_mismo() -> dict[str, SnapshotField]:
    """Two borrowers WITH NAMES (D2): the borrower_id link the enumerator reads PLUS first/middle/last so the
    LP-390-8a roster (``loan_borrower_roster``) is non-empty and the group can actually compare."""
    mismo: dict[str, SnapshotField] = {}
    for i, (bid, (first, middle, last)) in enumerate(_ROSTER.items(), start=1):
        mismo[f"borrower.{i}.borrower_id"] = _f(str(bid))
        mismo[f"borrower.{i}.first_name"] = _f(first)
        if middle:
            mismo[f"borrower.{i}.middle_name"] = _f(middle)
        mismo[f"borrower.{i}.last_name"] = _f(last)
    return mismo


def _statements() -> list[DocumentEntry]:
    """One bank statement per case — the MINIMUM viable structure (D1): a holder name to compare against the
    roster. ``bank_statement`` type so ``stmt_facts`` actually runs (D4 — it is scoped to bank/money-market)."""
    return [
        DocumentEntry(
            content_id=f"own-{c.key.lower()}",
            document_type="bank_statement",
            belongs_to=None,  # owner_matches compares holder-vs-roster; belongs_to is irrelevant to it
            fields={
                "account_holder_name": _f(c.holder),
                "bank_name": _f("First Springfield Bank"),
                "ending_balance": _f("5000.00"),
            },
        )
        for c in _CASES
    ]


def build_owner_match_scenario_snapshot() -> Snapshot:
    """The standalone negative-case snapshot for ``stmt.owner_matches_borrower``: two named borrowers + 8 bank
    statements (6 negative, 2 positive control), each built to the minimum structure. Deterministic, keyless,
    DISJOINT from LF-6T3N and the income fixture. Never merged into either builder."""
    return Snapshot(
        loan_file_id=_LOAN_ID,
        run_id=_RUN_ID,
        created_at=_CREATED,
        documents=DocumentsSection.present(_statements()),
        mismo=MismoSection.present(_roster_mismo()),
        tags=TagsSection.present({}),
    )


# --------------------------------------------------------------------------- #
# LP-399 — the BLIND labeling worksheet
# --------------------------------------------------------------------------- #
OWNER_MATCH_WORKSHEET_FILE = "owner-match-scenario-labels.csv"
_OWNER_TAG = "stmt.owner_matches_borrower"

# The NEUTRAL label question. It asks ONLY the core question (holder-vs-roster) and deliberately does NOT
# restate the AI's tolerance clauses ("be tolerant of middle initials / nicknames / maiden names") — restating
# them would hand Priya the answer key (she must judge blind whether "Jordan M Rivera" is the borrower). The
# "yes / no / unknown" are the tag's allowed values, not a prediction.
_OWNER_LABEL_PROMPT = (
    "Does the account holder on this statement match one of the loan's borrowers listed above? "
    "yes / no / unknown"
)

# A DETERMINISTIC order that does NOT group the negatives (N*) then the positives (P*) — else the sheet would
# telegraph which rows are which. The two positive controls sit at positions 2 and 5, interspersed among the
# negatives; no run of the 6 negatives is contiguous. (Anti-anchoring, LP-337 — the order must reveal nothing.)
_ROW_ORDER: tuple[str, ...] = ("N3", "P1", "N1", "N6", "P2", "N2", "N5", "N4")


def write_owner_match_worksheet(out_dir: Path) -> Path:
    """LP-399 — generate the committable BLIND labeling worksheet for ``stmt.owner_matches_borrower``. One row
    per statement (8), context = the statement's own fields PLUS the loan's borrower roster (she must see BOTH
    to judge a match — an absent roster would make every row unjudgeable, the LP-390-3 missing-field lesson),
    then the neutral question. Predictions / expected answers / AI reasoning NEVER reach it: the context is
    built by ``build_worksheet`` from the snapshot ONLY (no AI), the roster is a snapshot fact, and the two
    ambiguous cases (N1/N5) carry no encoded answer. Deterministic + keyless. Returns the written path."""
    from app.verification.eval.worksheet import build_worksheet, render_csv
    from app.verification.tag_materialization.subjects import loan_borrower_roster

    snap = build_owner_match_scenario_snapshot()
    roster_line = "loan_borrowers: " + "; ".join(
        loan_borrower_roster(snap)
    )  # she compares against these
    by_key = {
        r.subject_id.rsplit("-", 1)[1].upper(): r
        for r in build_worksheet(snap, only_tags=frozenset({_OWNER_TAG}))
    }
    ordered = [
        replace(
            by_key[key], context=f"{by_key[key].context} || {roster_line} | {_OWNER_LABEL_PROMPT}"
        )
        for key in _ROW_ORDER
    ]
    path = out_dir / OWNER_MATCH_WORKSHEET_FILE
    path.write_text(render_csv(ordered), encoding="utf-8")
    return path


__all__ = [
    "AMBIGUOUS_CASES",
    "CLEARCUT_EXPECTATIONS",
    "OWNER_MATCH_WORKSHEET_FILE",
    "OwnerCase",
    "build_owner_match_scenario_snapshot",
    "write_owner_match_worksheet",
]

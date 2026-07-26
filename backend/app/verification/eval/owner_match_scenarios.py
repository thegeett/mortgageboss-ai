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
_B3 = UUID(
    "94000000-0000-4000-8000-000000000003"
)  # Sarah Chen (LP-401 — for N7's surname_differs: holder "Sarah Nguyen")


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


# The borrowers on the loan (the comparison roster). LP-401 added Sarah Chen for N7's surname case; D1 verified
# the addition does NOT disturb the original 8's results (they compare against Jordan A Rivera / Robert Chen).
_ROSTER = {
    _B1: ("Jordan", "A", "Rivera"),
    _B2: ("Robert", "", "Chen"),
    _B3: ("Sarah", "", "Chen"),
}

# 6 negatives (resembling a borrower in one specific way) + 2 positive controls.
_CASES: tuple[OwnerCase, ...] = (
    # AMBIGUOUS — a DIFFERENT middle initial (M vs the borrower's A): a relative, or tolerable variation? The
    # sharpest case; the middle-name tolerance clause is exactly what could swallow it. Priya's call.
    OwnerCase(
        "N1", "Jordan M Rivera", "middle-name clause: a DIFFERENT middle initial (M vs A)", None
    ),
    # AMBIGUOUS (LP-401 reclassified from clear-cut `no`) — "Roberta Chen" vs "Robert Chen" is GENUINELY
    # ambiguous: the model flipped across three runs (LP-398 unknown -> LP-400 no -> LP-401 yes "a common
    # feminine variant"). A different person, or a variant? Its instability is N2's OWN (the roster change did
    # not cause it — it moved in LP-400 with no roster change; N9 proves the roster works). Priya's call.
    OwnerCase(
        "N2",
        "Roberta Chen",
        "given-name clause: Roberta vs Robert (a variant, or a different person?)",
        None,
    ),
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
    # LP-401 — the two-gap fillers. `expected` is the OWNER_MATCHES clear-cut only (None = ambiguous).
    # AMBIGUOUS owner_matches — "Sarah Nguyen" vs borrower "Sarah Chen": a maiden/married surname change, or a
    # different person? Its holder_name_variance (surname_differs) gives that value its FIRST case (was n=0).
    OwnerCase("N7", "Sarah Nguyen", "surname clause: Sarah Nguyen vs borrower Sarah Chen", None),
    # AMBIGUOUS owner_matches — a JOINT account with a spouse-shaped non-borrower co-holder (Linda Chen). Its
    # non_borrower_co_holder (yes) is the SECOND `yes` case (was n=1, N5 only). Robert Chen IS a borrower.
    OwnerCase(
        "N8",
        "ROBERT CHEN AND LINDA CHEN",
        "joint clause: a spouse-shaped non-borrower co-holder",
        None,
    ),
    # CLEAR-CUT owner_matches yes — a JOINT account where BOTH holders are borrowers. The DISCRIMINATING control
    # for non_borrower_co_holder (clear-cut `no`): joint is not automatically a problem. Without it the tag
    # could pass by answering "is this joint?" instead of "is a holder a non-borrower?".
    OwnerCase(
        "N9",
        "JORDAN A RIVERA AND ROBERT CHEN",
        "joint clause: BOTH holders are borrowers (control)",
        "yes",
    ),
)

# The clear-cut expectations — recorded HERE / in tests only, NEVER a worksheet (anti-anchoring, LP-337).
# owner_matches: derived from OwnerCase.expected (adds N9=yes; N7/N8 stay ambiguous with N1/N5).
CLEARCUT_EXPECTATIONS: dict[str, str] = {
    c.key: c.expected for c in _CASES if c.expected is not None
}
AMBIGUOUS_CASES: tuple[str, ...] = tuple(c.key for c in _CASES if c.expected is None)  # N1,N5,N7,N8
# non_borrower_co_holder is DETERMINABLE for every case (a describe fact, not a judgment): single-holder → no;
# N5/N8 have a non-borrower co-holder → yes; N9 (both borrowers) → no — THE discriminating control.
CLEARCUT_CO_HOLDER: dict[str, str] = {
    "N1": "no",
    "N2": "no",
    "N3": "no",
    "N4": "no",
    "N6": "no",
    "N7": "no",
    "P1": "no",
    "P2": "no",
    "N5": "yes",
    "N8": "yes",
    "N9": "no",
}


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
# LP-399 / LP-401 — the BLIND labeling worksheet (LP-401: all THREE tags, 11 statements = 33 rows)
# --------------------------------------------------------------------------- #
OWNER_MATCH_WORKSHEET_FILE = "owner-match-scenario-labels.csv"
_OWNER_TAG = "stmt.owner_matches_borrower"
_VARIANCE_TAG = "stmt.holder_name_variance"
_CO_HOLDER_TAG = "stmt.non_borrower_co_holder"

# NEUTRAL questions — each asks ONLY its core question and does NOT restate the AI's selection rules (LP-399:
# the sheet omits "be tolerant of middle initials / nicknames / maiden names" — that would hand her the answer
# key). D3: holder_name_variance NEEDS its allowed VALUES shown (she can't pick from a taxonomy she can't see) —
# so the values are listed, but NOT the model's rules for CHOOSING one (e.g. never "a dropped middle = absent").
_LABEL_PROMPTS: dict[str, str] = {
    _OWNER_TAG: (
        "Does the account holder on this statement match one of the loan's borrowers listed above? "
        "yes / no / unknown"
    ),
    _VARIANCE_TAG: (
        "If the holder matches a borrower but the name is not identical, how does the name DIFFER? "
        "Choose one: none / middle_absent / middle_differs / nickname / surname_differs / other / unknown"
    ),
    _CO_HOLDER_TAG: (
        "Is there an ADDITIONAL account holder who is NOT one of the loan's borrowers (a joint account)? "
        "yes / no / unknown"
    ),
}

# D4 — the row order. GROUP BY TAG (all match rows, then all variance, then all co-holder) so a scenario's THREE
# rows sit 11 apart — a labeler's answer on one tag can't reflexively bias the same scenario's next tag. Within
# each tag, a DETERMINISTIC statement order that does NOT cluster the positives (P1 at index 1, P2 at index 5)
# — the LP-399 anti-grouping principle, extended to 11.
_TAG_ORDER: tuple[str, ...] = (_OWNER_TAG, _VARIANCE_TAG, _CO_HOLDER_TAG)
_STATEMENT_ORDER: tuple[str, ...] = (
    "N3",
    "P1",
    "N1",
    "N8",
    "N6",
    "P2",
    "N7",
    "N2",
    "N5",
    "N9",
    "N4",
)


def write_owner_match_worksheet(out_dir: Path) -> Path:
    """LP-399 / LP-401 — generate the committable BLIND labeling worksheet for the three statement-holder tags
    (owner_matches_borrower / holder_name_variance / non_borrower_co_holder), one row per (tag, statement) = 33.
    Context = the statement's own fields PLUS the loan's borrower roster (she must see BOTH — an absent roster is
    the LP-390-3 missing-field trap), then the tag's neutral question. Predictions / expected answers / AI
    reasoning NEVER reach it (LP-398 AND LP-400 both published the AI's answers): the context is built by
    ``build_worksheet`` from the snapshot ONLY, the roster is a snapshot fact, the golden column is blank, and
    the ambiguous cases carry no encoded answer. Deterministic + keyless. Returns the written path."""
    from app.verification.eval.worksheet import build_worksheet, render_csv
    from app.verification.tag_materialization.declarations import _allowed_values_by_tag
    from app.verification.tag_materialization.subjects import loan_borrower_roster

    snap = build_owner_match_scenario_snapshot()
    roster_line = "loan_borrowers: " + "; ".join(loan_borrower_roster(snap))
    allowed = _allowed_values_by_tag()
    # base rows carry the statement facts + source_document (no prompt — owner_matches declares none); reused for
    # every tag on that statement, with the tag id / allowed values / prompt swapped.
    base = {
        r.subject_id.rsplit("-", 1)[1].upper(): r
        for r in build_worksheet(snap, only_tags=frozenset({_OWNER_TAG}))
    }
    rows = [
        replace(
            base[key],
            tag_id=tag,
            allowed_values=" | ".join(allowed[tag] or ()),
            consuming_rules="",  # LP-400 deferred AS-6's consumption — no rule reads these yet
            context=f"{base[key].context} || {roster_line} | {_LABEL_PROMPTS[tag]}",
        )
        for tag in _TAG_ORDER
        for key in _STATEMENT_ORDER
    ]
    path = out_dir / OWNER_MATCH_WORKSHEET_FILE
    path.write_text(render_csv(rows), encoding="utf-8")
    return path


__all__ = [
    "AMBIGUOUS_CASES",
    "CLEARCUT_CO_HOLDER",
    "CLEARCUT_EXPECTATIONS",
    "OWNER_MATCH_WORKSHEET_FILE",
    "OwnerCase",
    "build_owner_match_scenario_snapshot",
    "write_owner_match_worksheet",
]

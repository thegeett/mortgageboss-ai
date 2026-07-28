"""LP-420 — the combined blind labeling worksheets for the income-docs tags that passed the D1 census.

The plan was ONE Priya session for the six/seven tags blocking IN-8, IN-9, IN-12, IN-13, IN-14, AS-7, OC-1.
The D1 labelability census (docs/tickets/LP-420.md) EXCLUDED four of them — never spend her time on a thin or
one-sided tag (the LP-395 / AS-6 lesson):

  * income.type — 25 rows but one-sided (23/25 base wage); its consuming values self_employment (IN-12) and
    rental (IN-13) are STRUCTURALLY unreachable (income_amounts reads only pay_stub/w2, never tax returns).
  * txn.is_nsf_or_overdraft — n=0; per-transaction; building means inventing bank lines whose NSF label we'd
    then "judge" (labeling our own invention).
  * occupancy.rental_support / occupancy.consistent_with_signals — n=0 and LOAN-subject (one row per loan);
    n>=6 means authoring 6+ whole loan files with the declaration/lease (in)consistency we'd then judge.

Three tags PASSED (n>=6 AND a genuine two/multi-sided value distribution), both feeding LP-418's committed
fixtures — so NO new scenario is invented here:

  * income.voe_present        (12 rows: 6 VOE -> yes, 6 offer -> no)     — unblocks IN-8
  * income.offer_letter_present (12 rows: 6 offer -> yes, 6 VOE -> no/n/a) — unblocks IN-9
  * income.continuance_3yr    (6 rows: pension/alimony/child-support/disability/SS/note) — advances IN-13

BLIND (LP-399 / LP-401): built by ``build_worksheet`` from the snapshot FACTS only (no AI, no key), golden
column blank, a neutral prompt that shows the allowed VALUES but never the model's rules for choosing, and a
deterministic NON-GROUPING row order (the insertion order clusters all yes-shaped rows then all no-shaped ones,
telegraphing them). Two committable files; see docs/tickets/LP-420.md for the session agenda.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from app.verification.eval.fire_path_scenarios import (
    build_other_income_continuance_snapshot,
    build_voe_offer_labeling_snapshot,
)
from app.verification.eval.worksheet import WorksheetRow, build_worksheet, render_csv

# The two committable worksheet files (docs/calibration/).
VOE_OFFER_WORKSHEET_FILE = "income-docs-voe-offer-labels.csv"
CONTINUANCE_WORKSHEET_FILE = "income-continuance-3yr-labels.csv"

_VOE_TAG = "income.voe_present"
_OFFER_TAG = "income.offer_letter_present"
_CONTINUANCE_TAG = "income.continuance_3yr"

# D4 — neutral label prompts: they show the allowed VALUES (so she can choose) and deliberately DO NOT restate
# the model's rules for choosing (the LP-399 / LP-401 line — no "a VOE is a form from the employer stating...",
# no "an offer letter must have a start date and salary"). Plain ASCII (renders in Excel/Sheets).
_PROMPTS = {
    _VOE_TAG: "Is this document a Verification of Employment (VOE)? yes / no",
    _OFFER_TAG: "Is this an employment offer letter stating a future start date? yes / no / n/a",
    _CONTINUANCE_TAG: "Is this income likely to continue for at least 3 years? yes / no / unknown",
}

# D3 — a one-line "what this decides" note per sheet (plain English, no jargon, NO hint at any answer). Recorded
# here + in the session agenda (docs/tickets/LP-420.md).
SHEET_NOTES = {
    VOE_OFFER_WORKSHEET_FILE: (
        "What this decides: whether the file's employment documents are correctly told apart — a VOE vs an "
        "offer letter. Unblocks IN-8 and IN-9."
    ),
    CONTINUANCE_WORKSHEET_FILE: (
        "What this decides: whether each borrower's non-employment income will last long enough to count. "
        "Advances IN-13."
    ),
}


def _non_grouping(rows: list[WorksheetRow]) -> list[WorksheetRow]:
    """Interleave a tag's rows so the two source document types (voe vs offer — the likely yes vs no) ALTERNATE
    instead of clustering 6-then-6 (the insertion order, which telegraphs the answer — LP-399). Deterministic:
    a stable split by document_type, then round-robin. Types other than voe/offer keep their relative order."""
    voe = [r for r in rows if r.document_type == "voe"]
    offer = [r for r in rows if r.document_type == "employment_offer_letter"]
    other = [r for r in rows if r.document_type not in ("voe", "employment_offer_letter")]
    woven: list[WorksheetRow] = []
    for i in range(max(len(voe), len(offer))):
        if i < len(voe):
            woven.append(voe[i])
        if i < len(offer):
            woven.append(offer[i])
    return woven + other


# D3 — continuance rows have no yes/no-shaped document_type to interleave (all are 1003s); order them by a fixed
# non-alphabetical income-type permutation that does not cluster the likely-continuing types (pension, Social
# Security) apart from the likely-time-limited ones (child support, a maturing note) — deterministic, telegraphs
# nothing (the labels are hers to decide).
_CONTINUANCE_ORDER = (
    "pension",
    "child_support",
    "social_security",
    "note_receivable",
    "disability",
    "alimony",
)


def _income_type_of(row: WorksheetRow) -> str:
    """The other_income_type token from a continuance row's context (for the deterministic order key)."""
    marker = "other_income_type="
    if marker in row.context:
        return row.context.split(marker, 1)[1].split(";", 1)[0].strip()
    return ""


def _ordered_continuance(rows: list[WorksheetRow]) -> list[WorksheetRow]:
    order = {t: i for i, t in enumerate(_CONTINUANCE_ORDER)}
    return sorted(rows, key=lambda r: order.get(_income_type_of(r), len(order)))


def build_voe_offer_rows() -> list[WorksheetRow]:
    """The 24 voe/offer rows: grouped BY TAG (all voe_present, then all offer_letter_present — so a document's
    two tag-rows sit 12 apart and one answer can't bias the other, LP-401), each block interleaved so the source
    types alternate. Neutral prompts injected via build_worksheet's label_prompts (facts-first)."""
    snap = build_voe_offer_labeling_snapshot()
    rows: list[WorksheetRow] = []
    for tag in (_VOE_TAG, _OFFER_TAG):
        tag_rows = build_worksheet(
            snap, only_tags=frozenset({tag}), label_prompts={tag: _PROMPTS[tag]}
        )
        rows.extend(_non_grouping(tag_rows))
    return rows


def build_continuance_rows() -> list[WorksheetRow]:
    """The 6 continuance rows in the fixed non-grouping income-type order, with the neutral prompt."""
    snap = build_other_income_continuance_snapshot()
    rows = build_worksheet(
        snap,
        only_tags=frozenset({_CONTINUANCE_TAG}),
        label_prompts={_CONTINUANCE_TAG: _PROMPTS[_CONTINUANCE_TAG]},
    )
    return _ordered_continuance(rows)


def _blank_labels(rows: list[WorksheetRow]) -> list[WorksheetRow]:
    """Belt-and-braces: golden_label / labeler_note blank (build_worksheet already leaves them blank — this makes
    the blindness explicit and survives any future default change)."""
    return [replace(r, golden_label="", labeler_note="") for r in rows]


def write_voe_offer_worksheet(out_dir: Path) -> Path:
    path = out_dir / VOE_OFFER_WORKSHEET_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_csv(_blank_labels(build_voe_offer_rows())), encoding="utf-8")
    return path


def write_continuance_worksheet(out_dir: Path) -> Path:
    path = out_dir / CONTINUANCE_WORKSHEET_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_csv(_blank_labels(build_continuance_rows())), encoding="utf-8")
    return path


def write_all(out_dir: Path) -> dict[str, Path]:
    """Write both LP-420 worksheets. Deterministic + keyless (no AI, no network)."""
    return {
        VOE_OFFER_WORKSHEET_FILE: write_voe_offer_worksheet(out_dir),
        CONTINUANCE_WORKSHEET_FILE: write_continuance_worksheet(out_dir),
    }


__all__ = [
    "CONTINUANCE_WORKSHEET_FILE",
    "SHEET_NOTES",
    "VOE_OFFER_WORKSHEET_FILE",
    "build_continuance_rows",
    "build_voe_offer_rows",
    "write_all",
    "write_continuance_worksheet",
    "write_voe_offer_worksheet",
]

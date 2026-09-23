"""The local smoke test over the product owner's real condition sheets (LP-906, spec §7.5).

⚠️ NEVER RUNS IN CI, AND NO REAL SHEET EVER ENTERS THE REPO (ADR-405). It is skipped unless
`CONDITION_SHEETS_DIR` points at a folder OUTSIDE the repository — the product owner has one. Every
other fixture in this package is synthetic; this is the only thing that reads a lender's actual PDF,
and it reads it from a machine the repo cannot see.

⚠️ IT PRINTS COUNTS, CODES, READER NAMES AND WARNINGS — NEVER CONDITION TEXT, NAMES OR AMOUNTS
(spec §9.4). A smoke test whose output carried a borrower's name would put NPI into a terminal, a CI
log or a transcript, which is exactly what the readonly layer and the logging rules exist to prevent.
Lender codes are safe: they are the lender's own vocabulary, not the borrower's data.

WHAT IT ACTUALLY PROVES, and which assertion does the work. §7.5 asks for two: that every sheet is
recognised as UWM or Champions with no unassigned lines, and that the sorted multiset of row counts
is exactly `[6, 11, 12, 16, 28]`. The multiset is the load-bearing one — `unassigned_lines == []` is
satisfied TRIVIALLY by a sheet that produced no lines at all, so on a machine without an OCR engine a
scanned sheet would sail through the emptiness check and be caught only by its row count of 0.

⚠️ THIS WILL FAIL ON UWM PDFs UNTIL LP-905, AND THAT IS DELIBERATE. `read_uwm` refuses PDF input by
design (`NotImplementedError`): heading detection needs a column threshold in points, which could not
be calibrated while no PDF fixture existed. Section 3 authored one, so LP-905 is where that closes.
Until then this test reports the refusal rather than pretending to a result — and because it is
skipped without the env var, it blocks nobody.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from app.conditions.readers import (
    detect_format,
    lines_from_pdf,
    read_champions,
    read_generic,
    read_uwm,
)
from app.conditions.readers.model import ParsedSheet
from app.models.condition_round import ConditionSheetFormat

#: The folder of real sheets, outside the repo. Unset in CI and on any machine without a corpus.
_ENV = "CONDITION_SHEETS_DIR"

#: Spec §7.5: the sorted row counts the corpus must produce — round 2, round 1, a third sheet, the
#: two-page master, and the Champions certificate.
EXPECTED_ROW_COUNTS = [6, 11, 12, 16, 28]

pytestmark = pytest.mark.skipif(
    not os.environ.get(_ENV),
    reason=f"{_ENV} is not set; the real-sheet corpus lives outside the repo (spec §7.5)",
)


def _sheets_dir() -> Path:
    directory = Path(os.environ[_ENV]).expanduser()
    if not directory.is_dir():
        pytest.skip(f"{_ENV}={directory} is not a directory")
    return directory


def _read(path: Path) -> ParsedSheet:
    """Route one PDF to the reader its own first line selects."""
    lines = lines_from_pdf(path.read_bytes())
    match detect_format(lines):
        case ConditionSheetFormat.UWM_APPROVAL_LETTER:
            return read_uwm(lines)
        case ConditionSheetFormat.CHAMPIONS_CERTIFICATE:
            return read_champions(lines)
        case _:
            return read_generic(lines)


def test_every_real_sheet_is_recognised_and_fully_assigned() -> None:
    """§7.5's first assertion: a known format, and nothing left unplaced."""
    pdfs = sorted(_sheets_dir().glob("*.pdf"))
    if not pdfs:
        pytest.skip("no PDFs in the corpus directory")

    for index, path in enumerate(pdfs, start=1):
        sheet = _read(path)
        # ⚠️ The file is identified by its POSITION, never its name — a real sheet's filename
        # routinely carries the borrower's surname and the loan number.
        print(f"sheet {index}: format={sheet.sheet_format.value} rows={len(sheet.rows)}")
        print(f"  codes: {[row.lender_code for row in sheet.rows]}")
        print(f"  warnings: {len(sheet.warnings)} unassigned: {len(sheet.unassigned_lines)}")
        for warning in sheet.warnings:
            # ⚠️ THE CATEGORY ONLY, NEVER THE WHOLE WARNING. Several reader warnings deliberately
            # embed a fragment of the sheet so they are useful on a synthetic fixture —
            # `unrecognised loan-information line: 'Borrower  …'`, `unparseable Date Printed: '…'`.
            # On a REAL sheet that fragment is a borrower's name or a figure. §7.5 permits printing
            # warnings and forbids condition text, names and amounts; truncating at the first colon
            # keeps what identifies the PROBLEM and drops what identifies the BORROWER.
            print(f"    - {warning.split(':', 1)[0]}")

        assert sheet.sheet_format in {
            ConditionSheetFormat.UWM_APPROVAL_LETTER,
            ConditionSheetFormat.CHAMPIONS_CERTIFICATE,
        }, f"sheet {index} was not recognised"
        assert sheet.unassigned_lines == [], (
            f"sheet {index} left {len(sheet.unassigned_lines)} lines"
        )


def test_the_corpus_produces_the_expected_row_counts() -> None:
    """§7.5's second assertion, and the one that actually carries weight.

    ⚠️ THIS IS WHAT CATCHES A SHEET THAT READ NOTHING. `unassigned_lines == []` is satisfied by an
    empty parse; a row count of 0 is not. On a machine with no OCR engine a scanned page yields no
    lines at all — silently, with no error — so this multiset is the only assertion standing between
    that and a green run.
    """
    pdfs = sorted(_sheets_dir().glob("*.pdf"))
    if not pdfs:
        pytest.skip("no PDFs in the corpus directory")

    counts = sorted(len(_read(path).rows) for path in pdfs)
    print(f"row counts: {counts}  expected: {EXPECTED_ROW_COUNTS}")

    assert counts == EXPECTED_ROW_COUNTS

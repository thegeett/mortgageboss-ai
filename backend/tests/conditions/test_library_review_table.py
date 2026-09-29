"""LP-938: the product owner's review table IS the library, not a copy of it.

`docs/phases/phase4.5-library-review.md` claimed to be generated from `types.yaml` and was not. It went
stale when the Stage 3A acceptance gave DI-01's disclosure two performers, and still said "LO". These
tests fail when the committed file and the library differ. Regenerate with
`uv run python -m app.conditions.library.review_table`.
"""

from __future__ import annotations

from dataclasses import replace

from app.conditions.library.loader import load_library
from app.conditions.library.review_table import REVIEW_TABLE, TOP_20, render


def _row(text: str, type_id: str) -> str:
    (line,) = [
        line for line in text.splitlines() if line.startswith("| ") and f"**{type_id} " in line
    ]
    return line


def test_the_committed_table_is_the_librarys_output() -> None:
    assert REVIEW_TABLE.read_text(encoding="utf-8") == render(), (
        "phase4.5-library-review.md differs from types.yaml: run "
        "`uv run python -m app.conditions.library.review_table` and commit the result"
    )


def test_the_check_would_notice_a_library_change() -> None:
    """The positive control: a one-word change in the library changes the rendered table, so the
    comparison above is about the library and not about two files that happen to be equal."""
    library = load_library()
    changed = replace(library.types["AS-04"], playbook="Changed.")
    edited = replace(library, types={**library.types, "AS-04": changed})
    assert render(edited) != render(library)


def test_the_owners_two_corrections_are_in_the_table() -> None:
    text = REVIEW_TABLE.read_text(encoding="utf-8")
    # DI-01's re-signed disclosure is the borrower's and the LO's (plan §6; Stage 3A acceptance).
    assert (
        "Re-signed disclosure naming an approved attorney → Borrower + LO (Ask a third party)"
        in _row(text, "DI-01")
    )
    # AS-04's receipt is the earnest money receipt type, which covers the canceled check and the
    # escrow's acknowledgment; the note-income check type is gone.
    earnest = _row(text, "AS-04")
    assert "earnest_money_receipt" in earnest
    assert "cancelled_checks_evidencing_receipt_of_note_income" not in earnest
    receipt = next(i for i in load_library().types["AS-04"].items if i.key == "receipt")
    assert receipt.documents == ("earnest_money_receipt",)


def test_twenty_distinct_types_in_the_library() -> None:
    library = load_library()
    assert len(set(TOP_20)) == 20
    assert set(TOP_20) <= set(library.types)

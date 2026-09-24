"""How "is this the same condition?" is answered (LP-907, spec §LP-904's `text_fingerprint`).

⚠️ THE COLUMN EXISTED WITH NOTHING TO FILL IT. LP-904 created `conditions.text_fingerprint` NOT NULL
and indexed it `(loan_file_id, text_fingerprint)`, `uwm.py` recorded that "the stored
`text_fingerprint` is computed at import", and no code computed one — the only value anywhere was a
test helper's `uuid4().hex * 2`. This is that function, written by the first caller that genuinely
needs it (the enrich merge) and shared with the import that comes next.

WHAT IS REMOVED BEFORE HASHING, AND WHY EACH ONE:

* **Underwriter notes.** `**8/28 Not in Upload` is the underwriter annotating a condition that came
  back; the condition itself did not change. A fingerprint that included the note would make an
  annotated copy a DIFFERENT condition from the clean one, so round 3 would create a new row instead
  of recognising the row it already has — which is the duplication this whole matching exists to
  prevent. `verbatim_text` keeps the note, because the lender wrote one string (ADR-405).
* **Case, and runs of whitespace.** A PDF and a paste of the same sheet differ in spacing — a
  clipboard copy collapses columns, a text fixture keeps them — and the same sentence must fingerprint
  identically through both doors, or attaching a PDF to a pasted round matches nothing.

WHAT IS NOT REMOVED: punctuation, amounts, names, ordering. Two conditions differing only in an
amount are DIFFERENT conditions, and the page-break fixture proves the case — UWM lists `0571` three
times with three different amounts, and collapsing them would silently drop two of the lender's
demands.

⚠️ NOT NPI (ADR-405). A sha256 is one-way, which is exactly why it is the field the readonly views
keep when they drop `verbatim_text`: "did this condition come back?" stays answerable in analytics
without reproducing a word the lender wrote.
"""

from __future__ import annotations

import hashlib

from app.conditions.readers.uwm import note_stripped

#: `String(64)` on the column — sha256 hex is exactly 64 characters.
FINGERPRINT_LENGTH = 64


def fingerprint(text: str) -> str:
    """The stable identity of one condition's wording, as stored in `conditions.text_fingerprint`.

    ⚠️ THE SAME NORMALISATION THE UWM READER USES FOR DEDUPLICATION, imported rather than reimplemented.
    Rule 6 drops a page-overlap duplicate when the code, the note-stripped text and the notes all
    match; this decides whether a condition on a new sheet is one we already have. Two answers to
    "is this the same wording?" that could disagree would mean a row deduplicated within a sheet and
    then duplicated across rounds.
    """
    return hashlib.sha256(note_stripped(text).encode("utf-8")).hexdigest()


__all__ = ["FINGERPRINT_LENGTH", "fingerprint"]

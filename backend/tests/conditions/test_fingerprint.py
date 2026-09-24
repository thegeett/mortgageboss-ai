"""The condition fingerprint (LP-907, spec §LP-904).

⚠️ EVERY ASSERTION HERE IS A MATCHING OUTCOME, NOT A HASH VALUE. Pinning the hex of a sha256 would
test that sha256 is sha256; what matters is which pairs of lender wording are treated as the same
condition, because that decides whether round 3 recognises a row or duplicates it.
"""

from __future__ import annotations

import hashlib

from app.conditions.fingerprint import FINGERPRINT_LENGTH, fingerprint
from app.conditions.readers import read_uwm
from app.conditions.readers.lines import SOFT_HYPHEN, lines_from_text
from app.conditions.readers.uwm import note_stripped
from tests.conditions.fixture_helpers import UWM_ROUND_2, portal_excerpt, sheet_text

CREDIT_INVOICE = "Provide copy of invoice for credit report."


def test_it_is_a_sha256_hex_digest() -> None:
    value = fingerprint(CREDIT_INVOICE)

    assert len(value) == FINGERPRINT_LENGTH
    assert int(value, 16) >= 0


def test_an_underwriter_note_does_not_change_the_condition() -> None:
    """⚠️ THE PROPERTY THE WHOLE MATCHER RESTS ON. `**8/28 Not in Upload` means the underwriter
    annotated a condition that came back — the condition itself did not change. Including the note
    would make the annotated copy a different condition, so the next round would create a new row
    instead of recognising the one already on the file."""
    annotated = f"{CREDIT_INVOICE} **8/28 Not in Upload"

    assert fingerprint(annotated) == fingerprint(CREDIT_INVOICE)


def test_spacing_and_case_do_not_change_it() -> None:
    """A PDF and a paste of the same sheet differ in spacing, and the same sentence has to
    fingerprint identically through both doors or attaching a PDF to a pasted round matches
    nothing."""
    assert fingerprint("Provide  copy   of\tinvoice for credit report.") == fingerprint(
        CREDIT_INVOICE
    )
    assert fingerprint(CREDIT_INVOICE.upper()) == fingerprint(CREDIT_INVOICE)


def test_a_different_amount_is_a_different_condition() -> None:
    """⚠️ NOT NORMALISED AWAY, AND THE PAGE-BREAK FIXTURE IS WHY. UWM lists `0571` three times with
    three different amounts; collapsing them would silently drop two of the lender's demands."""
    assert fingerprint("Provide a Change of Circumstance for $450.") != fingerprint(
        "Provide a Change of Circumstance for $650."
    )


def test_a_different_condition_is_a_different_fingerprint() -> None:
    assert fingerprint(CREDIT_INVOICE) != fingerprint(
        "Provide copy of invoice for final inspection."
    )


def test_the_same_row_read_two_ways_fingerprints_the_same() -> None:
    """⚠️ THE ACCEPTANCE PROPERTY, EXERCISED END TO END RATHER THAN ASSERTED ON STRINGS.

    Spec §8 step 3 attaches round 2's PDF to the round pasted in step 2 and expects the conditions to
    MATCH — "still 11 conditions", no second round. That only holds if a row read from the pasted
    excerpt and the same row read from the whole sheet produce the same fingerprint.
    """
    pasted = read_uwm(lines_from_text(portal_excerpt()), conditions_from=0)
    whole = read_uwm(lines_from_text(sheet_text(UWM_ROUND_2)))

    assert [fingerprint(row.verbatim_text) for row in pasted.rows] == [
        fingerprint(row.verbatim_text) for row in whole.rows
    ]


def test_the_readers_dedup_key_and_the_stored_fingerprint_cannot_drift() -> None:
    """⚠️ TWO ANSWERS TO "IS THIS THE SAME WORDING?", AND EACH IS INDIVIDUALLY CORRECT — which is
    exactly why only a test comparing them DIRECTLY can catch them drifting apart.

    The reader's rule 6 drops a page-overlap duplicate on `(code, note-stripped text, notes)`; the
    stored fingerprint hashes the note-stripped text alone. If the two normalisations diverged, a
    row would be deduplicated within a sheet and then duplicated across rounds — and every test of
    either one on its own would still pass.

    So: the fingerprint must be a pure function of the reader's own normaliser, and the ONLY
    deliberate difference must be the notes, which rule 6 compares as a separate element.
    """
    plain = "Provide copy of invoice for credit report."
    annotated = f"{plain} **8/28 Not in Upload"

    # Same normaliser, asserted by construction rather than by restating the algorithm.
    assert fingerprint(plain) == hashlib.sha256(note_stripped(plain).encode("utf-8")).hexdigest()

    # The deliberate difference: the note vanishes from BOTH normalisations, so the fingerprints
    # match — while rule 6's key still separates them, because it carries the notes alongside.
    assert note_stripped(annotated) == note_stripped(plain)
    assert fingerprint(annotated) == fingerprint(plain)

    rule_six_key = (note_stripped(annotated), ("Not in Upload",))
    assert rule_six_key != (note_stripped(plain), ())


def test_a_soft_hyphen_normalised_by_the_reader_does_not_split_a_match() -> None:
    """The reader turns U+00AD into "-" before the text is ever fingerprinted, so a sheet whose PDF
    pipeline emitted soft hyphens matches the same condition typed with real ones."""
    raw = f"UW {SOFT_HYPHEN} Prior To Final Approval"
    normalised = "UW - Prior To Final Approval"

    assert fingerprint(lines_from_text(raw)[0].text) == fingerprint(normalised)

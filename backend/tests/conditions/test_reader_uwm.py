"""The UWM reader against the spec's three fixtures (LP-906 section 2, spec §7.1-7.3).

⚠️ EVERY EXPECTED VALUE HERE IS THE SPEC'S, NOT MINE. §7.1-7.3 state the exact row counts, the code
order, the note dates and texts, the owner hints, the expiry dates and the duplicate count. Writing
the reader first and then asserting whatever it produced would test that the code does what it does.
So these assertions were transcribed from the spec's expected tables before the reader ran once.

No database, no network. A reader is a pure function over lines.
"""

from __future__ import annotations

from datetime import date

import pytest
from app.conditions.readers import lines_from_text
from app.conditions.readers.uwm import read_uwm
from app.models.condition import BucketKind, OwnerHint, OwnerHintSource
from app.models.condition_round import ConditionSheetFormat
from tests.conditions.fixture_helpers import (
    UWM_PAGEBREAK,
    UWM_ROUND_1,
    UWM_ROUND_2,
    sheet_text,
)


def _read(fixture: str):  # type: ignore[no-untyped-def]
    return read_uwm(lines_from_text(sheet_text(fixture)))


# --------------------------------------------------------------------------- #
# §7.1 — uwm_round1_2026-08-28.txt
# --------------------------------------------------------------------------- #


def test_round1_format_and_date_printed() -> None:
    sheet = _read(UWM_ROUND_1)

    assert sheet.sheet_format is ConditionSheetFormat.UWM_APPROVAL_LETTER
    assert sheet.date_printed == date(2026, 8, 28)


def test_round1_has_eleven_rows_in_the_spec_order() -> None:
    """§7.1: 11 rows, and the ORDER is part of the expectation — the sheet's order is the order the
    processor sees in the lender's portal."""
    sheet = _read(UWM_ROUND_1)

    assert [row.lender_code for row in sheet.rows] == [
        "1228",
        "7086",
        "6132",
        "6637",
        "6178",
        "0132",
        "1947",
        "1582",
        "0006",
        "0007",
        "6378",
    ]


def test_round1_buckets_follow_the_parenthetical_not_the_words() -> None:
    """⚠️ `UW - Prior To Final Approval (PTD)` is PRIOR_TO_DOCS. Reading the WORDS would file it
    under approval — the kind follows the parenthetical, which is spec rule 3."""
    sheet = _read(UWM_ROUND_1)
    kinds = {row.lender_code: row.bucket_kind for row in sheet.rows}

    assert kinds["1228"] is BucketKind.PRIOR_TO_DOCS
    assert kinds["6178"] is BucketKind.PRIOR_TO_DOCS
    assert kinds["0132"] is BucketKind.PRIOR_TO_DOCS  # Compliance - Prior To Closing (PTD)
    assert kinds["1947"] is BucketKind.PRIOR_TO_FUNDING  # Closing (PTF)
    assert kinds["6378"] is BucketKind.PRIOR_TO_FUNDING

    headings = {row.lender_code: row.bucket_heading for row in sheet.rows}
    assert headings["1228"] == "UW - Prior To Final Approval (PTD)"
    assert headings["0132"] == "Compliance - Prior To Closing (PTD)"


def test_round1_underwriter_notes_and_the_three_asterisk_trap() -> None:
    """§7.1: 6132 and 6637 carry a 2026-08-28 "Not in Upload" note; 0132 has NONE.

    ⚠️ `***NOTE***` IS LENDER TEXT, NOT AN UNDERWRITER NOTE. 0132's text contains it twice. The rule
    is "asterisks THEN a date" — three asterisks with no date must not match, or every lender aside
    would be misattributed to the underwriter.
    """
    sheet = _read(UWM_ROUND_1)
    notes = {row.lender_code: row.underwriter_notes for row in sheet.rows}

    assert [(n.date, n.text) for n in notes["6132"]] == [(date(2026, 8, 28), "Not in Upload")]
    assert [(n.date, n.text) for n in notes["6637"]] == [(date(2026, 8, 28), "Not in Upload")]
    assert notes["0132"] == []


def test_round1_exact_text_is_the_lenders_words() -> None:
    """§7.1 names two exact strings. The soft hyphen in `EXAMPLE REAL ESTATE{SHY} LAW FIRM` must
    already be a real hyphen here — normalisation runs before any rule sees the text."""
    sheet = _read(UWM_ROUND_1)
    text = {row.lender_code: row.verbatim_text for row in sheet.rows}

    assert text["0006"] == "Provide copy of invoice for credit report."
    assert "(EXAMPLE REAL ESTATE- LAW FIRM)" in text["0132"]
    assert "SC - Attorney & Insurance Preference disclosure." in text["0132"]


def test_round1_the_verbatim_text_keeps_its_notes() -> None:
    """Spec rule 4 and ADR-405: the lender wrote ONE string. The note is extracted as structure AND
    left in the text; a UI showing the note as ours would misattribute it."""
    sheet = _read(UWM_ROUND_1)
    text = {row.lender_code: row.verbatim_text for row in sheet.rows}

    assert "**8/28 Not in Upload" in text["6132"]


def test_round1_owner_hints_prefer_the_lenders_own_marker() -> None:
    """§7.1: 1947 and 6378 → TITLE by PREFIX (`TC:`); the rest come from the code map."""
    sheet = _read(UWM_ROUND_1)
    hints = {row.lender_code: (row.owner_hint, row.owner_hint_source) for row in sheet.rows}

    assert hints["1947"] == (OwnerHint.TITLE, OwnerHintSource.PREFIX)
    assert hints["6378"] == (OwnerHint.TITLE, OwnerHintSource.PREFIX)
    assert hints["0006"][1] is OwnerHintSource.CODE_MAP


def test_round1_lender_team_and_the_empty_closer() -> None:
    """§7.1 names five roles — and `Closer:` has no value, which must still not crash the pair
    scanner or invent a name."""
    sheet = _read(UWM_ROUND_1)
    team = {entry["role"]: entry for entry in sheet.header["lender_team"]}  # type: ignore[index,union-attr]

    assert team["Senior UW"]["name"] == "Dana Okafor"
    assert team["Senior UW"]["phone_ext"] == "85210"
    assert team["UW II"]["name"] == "Lena Brennan"
    assert team["UW II"]["phone_ext"] == "87044"
    assert team["UW Team"]["name"] == "Tigers"
    assert team["AE"]["name"] == "Sam Moreno"
    assert team["AE"]["phone_ext"] == "5120"


def test_round1_loan_facts() -> None:
    """§7.1's loan facts. `Rate Lock Exp` is EMPTY on this sheet and present on round 2 — the pair
    that proves a blank value is not silently filled from the next column."""
    sheet = _read(UWM_ROUND_1)
    facts = sheet.header["loan_facts"]  # type: ignore[index]

    assert facts["Note Rate"] == "6.374%"  # type: ignore[index]
    assert facts["Housing / Debt Ratios"] == "32.51% / 40.36%"  # type: ignore[index]
    assert facts["Verified Assets"] == "$11,062.18"  # type: ignore[index]
    assert facts["Max Funds to Close"] == "$11,062.18"  # type: ignore[index]
    assert facts["Must Not Close Before"] == "09/30/2026"  # type: ignore[index]
    assert "Rate Lock Exp" not in facts  # type: ignore[operator]


def test_round1_expiry_dates_are_assigned_by_column_not_by_order() -> None:
    """⚠️ THE TEST THE WHOLE POSITIONAL LINE MODEL EXISTS FOR.

    Six of the twelve columns are blank. There are 6 dates and 12 headers, so the Nth date is NOT the
    Nth header — matching by order would put insurance under `other` and nothing would look wrong.
    """
    sheet = _read(UWM_ROUND_1)

    assert sheet.expiry_dates["close_by"] == date(2026, 10, 30)
    assert sheet.expiry_dates["appraisal"] == date(2026, 11, 23)
    assert sheet.expiry_dates["asset"] == date(2026, 10, 30)
    assert sheet.expiry_dates["credit"] == date(2026, 11, 10)
    assert sheet.expiry_dates["income"] == date(2026, 11, 3)
    assert sheet.expiry_dates["insurance"] == date(2027, 9, 30)
    for empty in ("cpl", "other", "payoff", "short_sale", "title", "vob"):
        assert sheet.expiry_dates[empty] is None, empty


def test_round1_mortgagee_clause_is_captured_and_not_a_row() -> None:
    sheet = _read(UWM_ROUND_1)

    assert sheet.mortgagee_clause == (
        "United Wholesale Mortgage ISAOA, ATIMA PO BOX 202175 FLORENCE, SC 29502 "
        "Phone: (800) 981-8898"
    )


def test_round1_is_a_clean_read() -> None:
    """§7.1: no warnings, no unassigned lines, no duplicates. The strictest assertion in the file —
    `unassigned_lines` empty is the §9.2 invariant, and a reader that dropped a line would fail
    here rather than silently lose a lender's demand."""
    sheet = _read(UWM_ROUND_1)

    assert sheet.unassigned_lines == []
    assert sheet.duplicates_dropped == 0
    assert sheet.warnings == []
    assert sheet.needs_ai is False


# --------------------------------------------------------------------------- #
# §7.2 — uwm_round2_2026-09-10.txt
# --------------------------------------------------------------------------- #


def test_round2_six_rows_and_its_own_facts() -> None:
    """§7.2. The same loan a fortnight later: fewer conditions, different numbers, and `Rate Lock
    Exp` now HAS a value where round 1's was blank."""
    sheet = _read(UWM_ROUND_2)

    assert sheet.date_printed == date(2026, 9, 10)
    assert [row.lender_code for row in sheet.rows] == [
        "1228",
        "1947",
        "1582",
        "0006",
        "0007",
        "6378",
    ]
    assert sheet.rows[0].bucket_kind is BucketKind.PRIOR_TO_DOCS
    assert {row.bucket_kind for row in sheet.rows[1:]} == {BucketKind.PRIOR_TO_FUNDING}

    facts = sheet.header["loan_facts"]  # type: ignore[index]
    assert facts["Note Rate"] == "6.490%"  # type: ignore[index]
    assert facts["Housing / Debt Ratios"] == "32.83% / 40.69%"  # type: ignore[index]
    assert facts["Verified Assets"] == "$41,914.42"  # type: ignore[index]
    assert facts["Rate Lock Exp"] == "09/30/2026"  # type: ignore[index]


def test_round2_expiry_and_clean_read() -> None:
    sheet = _read(UWM_ROUND_2)

    assert sheet.expiry_dates["close_by"] == date(2026, 11, 3)
    assert sheet.expiry_dates["appraisal"] == date(2026, 11, 23)
    assert sheet.expiry_dates["asset"] == date(2026, 11, 30)
    assert sheet.expiry_dates["credit"] == date(2026, 11, 10)
    assert sheet.expiry_dates["income"] == date(2026, 11, 3)
    assert sheet.expiry_dates["insurance"] == date(2027, 9, 30)
    assert sheet.warnings == []
    assert sheet.unassigned_lines == []


# --------------------------------------------------------------------------- #
# §7.3 — uwm_master_pagebreak.txt: the hard one
# --------------------------------------------------------------------------- #


def test_pagebreak_sixteen_rows_after_dropping_two_duplicates() -> None:
    """§7.3: 16 rows and exactly 2 duplicates dropped.

    ⚠️ THE THREE `0571` ROWS ARE NOT DUPLICATES OF EACH OTHER. UWM lists 0571 once per change of
    circumstance and all three texts differ (815000 → 805000 and so on). Only the page-overlap
    repeat — the SAME code with the SAME text — is dropped. A reader that deduplicated on code
    alone would silently delete two genuine conditions.
    """
    sheet = _read(UWM_PAGEBREAK)

    assert [row.lender_code for row in sheet.rows] == [
        "0562",
        "7086",
        "7383",
        "1594",
        "5868",
        "6140",
        "4235",
        "0471",
        "5853",
        "1760",
        "0571",
        "0571",
        "0571",
        "1582",
        "0006",
        "6378",
    ]
    assert len(sheet.rows) == 16
    assert sheet.duplicates_dropped == 2


def test_pagebreak_the_three_0571_texts_all_differ() -> None:
    sheet = _read(UWM_PAGEBREAK)
    texts = [row.verbatim_text for row in sheet.rows if row.lender_code == "0571"]

    assert len(texts) == 3
    assert len(set(texts)) == 3


def test_pagebreak_buckets() -> None:
    sheet = _read(UWM_PAGEBREAK)
    kinds = [(row.lender_code, row.bucket_kind) for row in sheet.rows]

    assert kinds[0] == ("0562", BucketKind.MASTER)
    assert all(k is BucketKind.PRIOR_TO_DOCS for _, k in kinds[1:9])
    assert all(k is BucketKind.LENDER_TO_CLEAR for _, k in kinds[9:13])
    assert all(k is BucketKind.PRIOR_TO_FUNDING for _, k in kinds[13:])


def test_pagebreak_underwriter_notes_resolve_against_the_reference_date() -> None:
    """§7.3: 1594 and 4235 carry 2026-08-31 notes. This fixture has NO header, so `date_printed` is
    None — the spec gives `reference_date` = 2026-09-10 for it, which no header supplies, so the
    note dates cannot be resolved from the sheet alone and come back unresolved."""
    sheet = _read(UWM_PAGEBREAK)
    notes = {row.lender_code: row.underwriter_notes for row in sheet.rows}

    assert len(notes["1594"]) == 1
    assert notes["1594"][0].text.startswith(
        "Provide note as mortgage statement alone cannot verify non-ownership"
    )
    assert len(notes["4235"]) == 1
    assert notes["4235"][0].text.startswith("Need clarification on this prior employer as K-1")


def test_pagebreak_owner_hints_from_the_bucket() -> None:
    """§7.3: 1760 and the three 0571 are LENDER by BUCKET (`Underwriter To Obtain And Clear` — the
    lender is doing it, so no ask goes out); 6378 is TITLE by PREFIX."""
    sheet = _read(UWM_PAGEBREAK)
    hints = [(r.lender_code, r.owner_hint, r.owner_hint_source) for r in sheet.rows]

    for code, hint, source in hints:
        if code in {"1760", "0571"}:
            assert (hint, source) == (OwnerHint.LENDER, OwnerHintSource.BUCKET), code

    assert ("6378", OwnerHint.TITLE, OwnerHintSource.PREFIX) in hints


def test_pagebreak_expiry_dates() -> None:
    sheet = _read(UWM_PAGEBREAK)

    assert sheet.expiry_dates["close_by"] == date(2026, 11, 15)
    assert sheet.expiry_dates["appraisal"] == date(2026, 12, 27)
    assert sheet.expiry_dates["asset"] == date(2026, 11, 15)
    assert sheet.expiry_dates["credit"] == date(2026, 11, 30)
    assert sheet.expiry_dates["income"] == date(2026, 11, 30)
    assert sheet.expiry_dates["insurance"] == date(2027, 6, 3)


def test_pagebreak_mortgagee_clause_mid_list_is_an_artifact_not_a_row() -> None:
    """⚠️ THE CLAUSE BREAKS INTO THE MIDDLE OF THE CONDITIONS LIST at the page boundary, between a
    `0571` row and a `Closing (PTF)` heading. §7.3 expects NO unassigned lines: it is a known
    artifact, captured once, and it must not be appended to the row above it as a continuation."""
    sheet = _read(UWM_PAGEBREAK)

    assert sheet.mortgagee_clause is not None
    assert sheet.unassigned_lines == []
    for row in sheet.rows:
        assert "Mortgagee Clause" not in row.verbatim_text


def test_pagebreak_warns_once_per_duplicate_and_once_for_the_missing_header() -> None:
    """§7.3: one warning per dropped duplicate, plus one "header not found".

    A missing header is a WARNING, not a failure — refusing the sheet because its letterhead is
    absent would discard all 16 conditions on it.
    """
    sheet = _read(UWM_PAGEBREAK)

    assert "header not found" in sheet.warnings
    assert sum("duplicate" in w for w in sheet.warnings) == 2
    assert sheet.date_printed is None


@pytest.mark.parametrize("fixture", [UWM_ROUND_1, UWM_ROUND_2, UWM_PAGEBREAK])
def test_every_fixture_reads_without_needing_ai(fixture: str) -> None:
    """`needs_ai` means the RULES could not split the text. A sheet with warnings is still a
    rule-read sheet — setting it merely because a read was imperfect would send known layouts to
    LP-908 and pay for an AI call to redo work the rules already did."""
    sheet = _read(fixture)

    assert sheet.needs_ai is False
    assert all(row.confidence == 1.0 for row in sheet.rows)

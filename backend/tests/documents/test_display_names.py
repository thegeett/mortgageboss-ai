"""LP-943: every document type the condition library uses has a clean display name.

A name is CLEAN when it reads as English to a title company or an underwriter:
- no underscore;
- no stray single letter (the possessive in `borrower_s_…` became "borrower s …");
- no acronym left in lower case ("verbal voe", "government issued id", "hoa statement");
- no internal discriminator: when one type's slug is another's plus a suffix
  (`letter_of_explanation` / `letter_of_explanation_asset`), the longer one needs an explicit name,
  because the suffix is a tag the classifier uses, not a word a person would write.

A type added to the library without one fails here.
"""

from __future__ import annotations

import re

import pytest
from app.conditions.library.loader import load_library
from app.documents.display_names import ACRONYMS, DISPLAY_NAMES, display_name, in_sentence

_LOWER_ACRONYMS = {key for key, value in ACRONYMS.items() if value.upper() == value}


def _library_types() -> list[str]:
    library = load_library()
    return sorted(
        {d for kind in library.types.values() for item in kind.items for d in item.documents}
    )


def _problems(name: str) -> list[str]:
    words = re.findall(r"[A-Za-z0-9'()\-]+", name)
    found = []
    if "_" in name:
        found.append("underscore")
    found += [f"stray letter {w!r}" for w in words if len(w) == 1 and w.isalpha() and w != "a"]
    # Any spelling of a known acronym but its own: "voe" and a sentence-initial "Hoa" alike.
    found += [
        f"acronym spelled {w!r}"
        for w in words
        if w.lower() in _LOWER_ACRONYMS and w != ACRONYMS[w.lower()]
    ]
    return found


def test_the_five_named_by_the_owner() -> None:
    assert display_name("borrower_s_authorization_for_counseling") == (
        "Borrower's authorization for counseling"
    )
    assert display_name("verbal_voe") == "Verbal VOE"
    assert display_name("letter_of_explanation_asset") == "Letter of explanation (assets)"
    assert display_name("government_issued_id") == "Government-issued ID"
    assert display_name("drivers_license") == "Driver's license"


@pytest.mark.parametrize("document_type", _library_types())
def test_every_library_document_type_reads_cleanly(document_type: str) -> None:
    name = display_name(document_type)
    assert _problems(name) == [], f"{document_type} → {name!r}"


def test_a_discriminated_type_has_an_explicit_name() -> None:
    types = set(_library_types())
    discriminated = {t for t in types for base in types if t != base and t.startswith(base + "_")}
    assert discriminated  # the positive control: the library has such pairs
    assert sorted(discriminated - set(DISPLAY_NAMES)) == []


def test_the_check_would_notice_a_bad_name() -> None:
    """The positive control for the rule itself: the old underscore labels fail it."""
    assert _problems("borrower s authorization for counseling")
    assert _problems("verbal voe")
    assert _problems("government issued id")
    assert _problems("Hoa statement")


def test_mid_sentence() -> None:
    assert in_sentence("Borrower's authorization for counseling") == (
        "borrower's authorization for counseling"
    )
    assert in_sentence("HOA statement") == "HOA statement"
    assert in_sentence("W-2") == "W-2"
    assert in_sentence("IRA or 401(k) statement") == "IRA or 401(k) statement"

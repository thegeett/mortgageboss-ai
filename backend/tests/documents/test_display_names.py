"""LP-943: every document type the condition library uses has a clean display name.

A name is CLEAN when it reads as English to a title company or an underwriter:
- no underscore;
- no stray single letter (the possessive in `borrower_s_…` became "borrower s …");
- no acronym left in lower case ("verbal voe", "government issued id", "hoa statement");
- no internal discriminator: when one type's slug is another's plus a suffix
  (`letter_of_explanation` / `letter_of_explanation_asset`), the longer one needs an explicit name,
  because the suffix is a tag the classifier uses, not a word a person would write. THIS RULE IS A PROXY,
  not a closed one: it fires only when the base slug is ALSO a library type, so a tag-suffixed type whose
  base is not in the library would pass;
- no two library types share a name.

`ACRONYMS` is the maintained artefact: an acronym it does not list is invisible to the check.

A type added to the library without one fails here.
"""

from __future__ import annotations

import re

import pytest
from app.conditions.library.loader import load_library
from app.documents.catalog import CATALOG
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
    if name != name.strip() or "  " in name:
        found.append("stray whitespace")
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


@pytest.mark.parametrize("document_type", sorted(CATALOG))
def test_every_catalogued_document_type_reads_cleanly(document_type: str) -> None:
    """THE WHOLE CATALOGUE, not the library's 41 (LP-943 follow-up review): the attention panel names any
    failed or stale document, so every type a document can have is a name she may read."""
    name = display_name(document_type)
    assert _problems(name) == [], f"{document_type} → {name!r}"


def test_the_five_catalogue_names_the_rule_cannot_see() -> None:
    """Four of these pass the cleanliness rule even without their entries ("K1 statement", "Form
    4506c"): a form number is not a pattern the rule knows. So they are pinned by name."""
    assert display_name("social_security_administration_ssa_89") == "Form SSA-89"
    assert display_name("k_1_shareholder_profit_and_loss_transcripts") == (
        "K-1 shareholder profit and loss transcripts"
    )
    assert display_name("k1_statement") == "K-1 statement"
    assert display_name("form_4506c") == "Form 4506-C"
    assert display_name("form_4506t_request_for_transcript") == "Form 4506-T request for transcript"


def test_a_discriminated_type_has_an_explicit_name() -> None:
    types = set(_library_types())
    discriminated = {t for t in types for base in types if t != base and t.startswith(base + "_")}
    assert discriminated  # the positive control: the library has such pairs
    assert sorted(discriminated - set(DISPLAY_NAMES)) == []


def test_no_two_catalogued_types_share_a_name() -> None:
    """A name must also tell the documents apart: one file can ask for two types, and a note or an email
    naming both must say which answers which ask (the LP-943 review found two "Letter of explanation"s).
    A deliberate duplicate would go in `_SAME_ON_PURPOSE` with its reason; there is none today."""
    by_name: dict[str, list[str]] = {}
    for document_type in CATALOG:
        by_name.setdefault(display_name(document_type), []).append(document_type)
    _SAME_ON_PURPOSE: set[str] = set()
    shared = {name: types for name, types in by_name.items() if len(types) > 1}
    assert {n: t for n, t in shared.items() if n not in _SAME_ON_PURPOSE} == {}


def test_the_check_would_notice_a_bad_name() -> None:
    """The positive control for the rule itself: the old underscore labels fail it."""
    assert _problems("borrower s authorization for counseling")
    assert _problems("verbal voe")
    assert _problems("government issued id")
    assert _problems("Hoa statement")
    assert _problems("Bank  statement")
    assert _problems("Social security administration ssa 89")


def test_mid_sentence() -> None:
    assert in_sentence("Borrower's authorization for counseling") == (
        "borrower's authorization for counseling"
    )
    assert in_sentence("HOA statement") == "HOA statement"
    assert in_sentence("W-2") == "W-2"
    assert in_sentence("IRA or 401(k) statement") == "IRA or 401(k) statement"

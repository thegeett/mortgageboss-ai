"""LP-639 — a confident `unknown` can be explained without saying what the document is.

THE PROBLEM. When the classifier answers `unknown`, the only surviving evidence is the model's own
`document_name`, and that is free text which can quote a borrower's details — so it is never logged
or stored. A document that classified as `unknown` was therefore unexplainable: nobody could tell
whether the model described it correctly and the matcher failed, or the model had no idea what it
was looking at. Those need opposite fixes.

On LF-ZE9N that question had to be answered by inference, and the inference was wrong twice — once
from `has_full_text=False`, a field LP-463 stopped populating so it reads False for every document,
and once by assuming a low-resolution scan of a file that turned out to be a text PDF.
"""

from __future__ import annotations

import re

from app.documents.catalog import (
    CATALOG,
    REJECTED_BY_COVERAGE,
    REJECTED_BY_ORDER,
    explain_catalog_match,
    match_catalog_type,
)


def test_it_names_the_type_the_matcher_turned_away() -> None:
    """THE ANSWER THAT PAYS FOR THE WHOLE FEATURE. A name that DID say `closing_disclosure` and was
    rejected on coverage is a different bug from a model that recognised nothing — and until now the
    log said the same thing for both."""
    explanation = explain_catalog_match("a Closing Disclosure for the subject property")

    assert explanation.matched is None
    assert explanation.near_miss == "closing_disclosure"
    assert explanation.rejected_by == REJECTED_BY_COVERAGE
    assert explanation.name_words == 7


def test_a_name_that_says_nothing_is_reported_differently() -> None:
    """The other half of the distinction. No near miss means the words are not there at all, so
    loosening the coverage rule would not help this document."""
    explanation = explain_catalog_match("a photograph of a cat")

    assert explanation.near_miss is None
    assert explanation.rejected_by == REJECTED_BY_ORDER


def test_a_missing_name_is_distinguishable_from_an_unmatched_one() -> None:
    """ "The model produced no name" and "the name matched nothing" look identical in the outcome and
    need different fixes: the first is a prompt problem, the second a matcher problem."""
    absent = explain_catalog_match(None)
    assert absent.name_present is False
    assert absent.name_words == 0

    present = explain_catalog_match("a photograph of a cat")
    assert present.name_present is True


def test_a_match_is_reported_as_a_match() -> None:
    explanation = explain_catalog_match("a closing disclosure")

    assert explanation.matched == "closing_disclosure"
    assert explanation.near_miss is None
    assert explanation.rejected_by is None


def test_the_explanation_never_disagrees_with_the_matcher() -> None:
    """THE DRIFT GUARD. The explanation re-walks the same guards rather than being threaded through
    the matcher, deliberately — observability must not sit on the path that decides whether a
    processor sees a flag. The cost of that choice is two implementations, so this pins them
    together over every catalog slug in both a bare and a naturally-phrased form.
    """
    for slug in CATALOG:
        for name in (slug.replace("_", " "), f"a {slug.replace('_', ' ')}"):
            assert explain_catalog_match(name).matched == match_catalog_type(name), name


def test_the_explanation_carries_no_free_text() -> None:
    """THE GUARANTEE THAT MAKES IT LOGGABLE. Every field is a count, a boolean, or a catalog slug.
    The name must not survive in any form — not truncated, not hashed, not as a substring.

    Written as a property over the whole object rather than a check of today's fields, so a field
    added later that carries the name fails here rather than reaching a log.
    """
    # A name of the shape that makes this unloggable: it carries a person and an address.
    name_with_borrower_details = "Closing Disclosure for Jane Q Borrower at 1312 Example Court"
    explanation = explain_catalog_match(name_with_borrower_details)

    rendered = repr(explanation)
    for word in ("Jane", "Borrower", "1312", "Example", "Court"):
        assert word not in rendered, f"{word!r} leaked into {rendered}"
    # And nothing in it is free text at all: every string value is a catalog slug or a known reason.
    allowed = set(CATALOG) | {REJECTED_BY_COVERAGE, REJECTED_BY_ORDER}
    for value in vars(explanation).values():
        if isinstance(value, str):
            assert value in allowed, f"{value!r} is not from a closed vocabulary"


def test_the_word_count_cannot_reconstruct_the_name() -> None:
    """`name_words` is the one number derived from the text. It is a count, so it is safe — pinned
    because a future 'make it more useful' change (a prefix, a length in characters, a hash) would
    be the moment this stops being safe to log."""
    explanation = explain_catalog_match("a Closing Disclosure for the subject property")

    assert isinstance(explanation.name_words, int)
    assert not re.search(r"[A-Za-z]{3,}", str(explanation.name_words))

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

import inspect

from app.documents.catalog import (
    _MIN_SLUG_COVERAGE,
    _MIN_SLUG_WORDS_FOR_NAME_MATCH,
    CATALOG,
    NO_CATALOG_WORDS,
    REJECTED_BY_COVERAGE,
    REJECTED_BY_MIN_WORDS,
    REJECTED_BY_ORDER,
    UNUSABLE_NAME,
    _matches_in_order_with_small_gaps,
    _normalize_for_match,
    explain_catalog_match,
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
    assert explanation.rejected_by == NO_CATALOG_WORDS


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


def test_the_matched_verdict_is_the_matchers_own() -> None:
    """`matched` is not a second opinion — it is `match_catalog_type`'s, delegated.

    THIS REPLACES A TEST THAT COULD NOT FAIL. The original compared
    `explain_catalog_match(name).matched` with `match_catalog_type(name)` and called itself the
    drift guard that justified the second-pass design. But `explain_catalog_match` assigns
    `matched = match_catalog_type(free_text)`, so it compared a value with itself: corrupting the
    matcher to return a constant left it green over every slug in the catalog. Verified by doing
    exactly that.

    The good news it was hiding: the DECISION is not duplicated at all, so the two-definitions risk
    is smaller than the design note claimed. What is duplicated is the near-miss walk, and
    `test_a_near_miss_means_what_it_says` is what pins that.
    """
    assert inspect.getsource(explain_catalog_match).count("match_catalog_type(") == 1, (
        "`matched` no longer delegates, so it IS a second implementation now and needs a real "
        "agreement test — the one this replaced could never have caught that."
    )


def test_a_near_miss_means_what_it_says() -> None:
    """THE REAL DRIFT GUARD, over what is genuinely duplicated.

    The near-miss walk re-implements the matcher's ordering rule and its minimum-slug-words rule,
    omitting only coverage. If those drift, `near_miss` starts naming slugs the matcher would never
    have considered — and the whole diagnostic value of the field is that it means "the matcher
    would have taken this but for coverage". So this asserts that claim directly, against the
    matcher's own constants, for every name that produces one.
    """
    names = [f"a {slug.replace('_', ' ')} attached for your review and records" for slug in CATALOG]
    checked = 0
    for name in names:
        explanation = explain_catalog_match(name)
        if explanation.near_miss is None:
            continue
        checked += 1
        assert explanation.matched is None, "a near miss cannot coexist with a match"
        words = explanation.near_miss.split("_")
        tokens = _normalize_for_match(name).split()
        assert explanation.near_miss_coverage == round(len(words) / len(tokens), 2)

        # EACH REASON CLAIMS SOMETHING DIFFERENT, and each is checked against the matcher's own
        # constants — that is what stops the two walks drifting apart.
        if explanation.rejected_by == REJECTED_BY_COVERAGE:
            assert len(words) >= _MIN_SLUG_WORDS_FOR_NAME_MATCH
            assert _matches_in_order_with_small_gaps(words, tokens), (
                "near_miss does not actually order correctly — the two walks have drifted"
            )
            assert len(words) / len(tokens) < _MIN_SLUG_COVERAGE, (
                "near_miss passed coverage, so the matcher should have MATCHED it"
            )
        elif explanation.rejected_by == REJECTED_BY_MIN_WORDS:
            assert len(words) < _MIN_SLUG_WORDS_FOR_NAME_MATCH, (
                "min_words was blamed for a slug long enough to be considered"
            )
            assert _matches_in_order_with_small_gaps(words, tokens)
        elif explanation.rejected_by == REJECTED_BY_ORDER:
            assert all(word in tokens for word in words), (
                "order was blamed for a slug whose words are not all present"
            )
            assert not _matches_in_order_with_small_gaps(words, tokens), (
                "order was blamed for a slug that DOES order correctly"
            )
        else:
            raise AssertionError(f"a near miss with no guard behind it: {explanation}")
    assert checked > 10, (
        f"only {checked} names produced a near miss, so this guard is barely exercising anything"
    )


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
    # And nothing in it is free text at all. Checked as a TYPE whitelist first: the earlier version
    # only inspected `str` values, so a field added later as a list or dict of free text — the
    # natural shape for "the words that did match" — would have sailed through the test that exists
    # to stop exactly that.
    allowed = set(CATALOG) | {
        REJECTED_BY_COVERAGE,
        REJECTED_BY_ORDER,
        REJECTED_BY_MIN_WORDS,
        NO_CATALOG_WORDS,
        UNUSABLE_NAME,
    }
    for field, value in vars(explanation).items():
        assert type(value) in (bool, int, float, str, type(None)), (
            f"{field} is a {type(value).__name__}; only counts, booleans, closed-vocabulary strings "
            "and None are safe to log, and a container could carry the name in pieces"
        )
        if isinstance(value, str):
            assert value in allowed, f"{value!r} is not from a closed vocabulary"


def test_only_counts_and_ratios_are_derived_from_the_name() -> None:
    """THIS REPLACES A TEST THAT COULD NOT FAIL.

    The original asserted `not re.search(r"[A-Za-z]{3,}", str(name_words))` — applied to an int,
    whose `str()` never contains letters. Unfalsifiable, while its docstring claimed to pin against
    "a length in characters, a hash": a character count IS an int and a hash stored as an int is an
    int, so both would have passed it unchanged.

    What is actually at risk is a NEW derived field carrying more of the name than a magnitude. So
    this pins the numeric fields to what they are allowed to be — a token count and a ratio bounded
    by it — over names of very different content but the same shape.
    """
    a = explain_catalog_match("a Closing Disclosure for the subject property")
    b = explain_catalog_match("a Closing Disclosure for Jane Borrower Court")

    # Same token count, entirely different content: every number must agree, or something in the
    # object is varying with the name's CONTENT rather than its shape.
    assert a.name_words == b.name_words
    assert (a.name_words, a.near_miss) == (b.name_words, b.near_miss)

    for explanation in (a, b):
        assert explanation.name_words == len(
            _normalize_for_match("a Closing Disclosure for the subject property").split()
        )
        if explanation.near_miss_coverage is not None:
            assert 0.0 < explanation.near_miss_coverage <= 1.0


def test_the_docstring_promise_about_length_is_not_overstated() -> None:
    """`name_words` IS a length of the name, and the guarantee once read "the name never appears...
    including as a length that could distinguish two candidate documents". That is false as written.

    What is true, and what the log actually relies on, is that the length is in WORDS — a handful of
    bits — and that nothing else derived from the name is logged. Pinned as an entropy bound rather
    than a promise nobody can check.
    """
    counts = {
        explain_catalog_match(f"{'word ' * n}bank statement").name_words for n in range(0, 40)
    }
    assert max(counts) < 64, (
        "name_words has grown into a high-cardinality fingerprint; it is meant to be a small count"
    )


def test_the_guard_working_and_the_guard_being_wrong_are_distinguishable() -> None:
    """THE FINDING THAT REWROTE THIS FEATURE.

    `rejected_by=coverage` was documented as "the model DID name a catalog type and the matcher
    turned it away", i.e. loosen the matcher. But it is equally what the guard produces when working
    CORRECTLY: `match_catalog_type`'s own docstring names "an email asking the borrower to send a
    bank statement" as the case coverage exists to reject, and it produced a byte-identical
    explanation to LF-ZE9N's genuine Closing Disclosure. Acting on the field as written would have
    loosened the guard against exactly the names it was measured to exclude.

    The coverage RATIO is what separates them, and the matcher already documents the populations —
    true names 0.5-0.67, mentions 0.18-0.25.
    """
    genuine = explain_catalog_match("a Closing Disclosure for the subject property")
    mention = explain_catalog_match("an email asking the borrower to send a bank statement")

    assert genuine.rejected_by == mention.rejected_by == REJECTED_BY_COVERAGE
    assert genuine.near_miss_coverage is not None and mention.near_miss_coverage is not None
    assert genuine.near_miss_coverage > mention.near_miss_coverage, (
        "the two cases are indistinguishable again — the reason alone cannot be acted on"
    )


def test_a_one_word_catalog_type_is_not_reported_as_nothing() -> None:
    """`_MIN_SLUG_WORDS_FOR_NAME_MATCH = 2` drops `appraisal`, `passport`, `survey`, `w2`, `1099`
    outright, and the first version had no reason for that guard — so a model that named a catalog
    type EXACTLY was logged as having named nothing, which is the misdiagnosis this ticket exists
    to prevent, on entirely ordinary document names."""
    for name, slug in (("Appraisal", "appraisal"), ("Passport", "passport"), ("Survey", "survey")):
        explanation = explain_catalog_match(name)
        assert explanation.near_miss == slug, name
        assert explanation.rejected_by == REJECTED_BY_MIN_WORDS, name
        assert explanation.rejected_by != NO_CATALOG_WORDS


def test_words_present_but_out_of_order_is_its_own_answer() -> None:
    """Previously folded into the same value as "no catalog words at all", so the one guard that
    could be loosened without touching coverage was invisible."""
    explanation = explain_catalog_match("a receipt for the earnest money")

    assert explanation.near_miss == "earnest_money_receipt"
    assert explanation.rejected_by == REJECTED_BY_ORDER

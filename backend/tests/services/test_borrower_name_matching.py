"""Deterministic document→borrower name matcher (LP-202) — pure-logic tests.

Covers: exact single match, joint document → both borrowers, honest no-match,
a below-threshold near-miss (never forced), and the exact/normalized/fuzzy method
tags. No DB, no AI.
"""

from uuid import uuid4

from app.services.borrower_name_matching import (
    NAME_MATCH_THRESHOLD,
    BorrowerName,
    asserted_names_for,
    match_document,
    normalize_name,
)


def _b(first: str | None, last: str | None, middle: str | None = None) -> BorrowerName:
    return BorrowerName(borrower_id=uuid4(), first_name=first, middle_name=middle, last_name=last)


def test_single_borrower_exact_match() -> None:
    akash, priya = _b("Akash", "Patel"), _b("Priya", "Patel")
    results = match_document(["AKASH PATEL"], [akash, priya])
    assert len(results) == 1
    assert results[0].borrower_id == akash.borrower_id
    assert results[0].method == "exact"
    assert results[0].confidence == 1.0


def test_joint_document_links_both_borrowers() -> None:
    akash, priya = _b("Akash", "Patel"), _b("Priya", "Patel")
    results = match_document(["Akash Patel and Priya Patel"], [akash, priya])
    linked = {r.borrower_id for r in results}
    assert linked == {akash.borrower_id, priya.borrower_id}
    assert all(r.confidence >= NAME_MATCH_THRESHOLD for r in results)


def test_no_match_produces_zero_links() -> None:
    akash, priya = _b("Akash", "Patel"), _b("Priya", "Patel")
    assert match_document(["John Williams"], [akash, priya]) == []


def test_low_similarity_near_miss_stays_below_threshold() -> None:
    """A surname typo (Patek vs Patel) must NOT be forced to the closest borrower."""
    akash = _b("Akash", "Patel")
    assert match_document(["Akash Patek"], [akash]) == []


def test_nickname_matches_and_tags_normalized() -> None:
    robert = _b("Robert", "Smith")
    nick = match_document(["Bob Smith"], [robert])
    assert nick[0].method == "normalized" and nick[0].confidence >= NAME_MATCH_THRESHOLD


def test_bare_initial_first_name_does_not_confer_a_match() -> None:
    """'A. Patel' must NOT link to Akash Patel — an initial is not first-name evidence."""
    akash = _b("Akash", "Patel")
    assert match_document(["A. Patel"], [akash]) == []


def test_fuzzy_first_name_typo_above_bar_tagged_fuzzy() -> None:
    """A genuine first-name typo (long enough, above the fuzzy bar) still links, tagged fuzzy."""
    jennifer = _b("Jennifer", "Smith")
    results = match_document(["Jenifer Smith"], [jennifer])  # one dropped 'n', ratio ~0.93
    assert len(results) == 1
    assert results[0].method == "fuzzy"
    assert results[0].confidence >= NAME_MATCH_THRESHOLD


def test_same_surname_middle_initial_does_not_overlink_sibling() -> None:
    """The stray 'A.' in 'Robert A. Smith' must NOT link co-borrower Andrew Smith."""
    robert, andrew = _b("Robert", "Smith"), _b("Andrew", "Smith")
    linked = {r.borrower_id for r in match_document(["Robert A. Smith"], [robert, andrew])}
    assert linked == {robert.borrower_id}


def test_first_name_below_fuzzy_bar_does_not_link() -> None:
    """A near-miss first name (Johnson vs John) fails its own bar → contributes zero → no link."""
    john = _b("John", "Smith")
    assert match_document(["Johnson Smith"], [john]) == []


def test_short_surname_near_miss_does_not_link() -> None:
    """Short surnames (Han/Hahn) must match exactly, never fuzzily."""
    han = _b("David", "Han")
    assert match_document(["David Hahn"], [han]) == []


def test_shared_nickname_links_both_canonicals() -> None:
    """'Steve' → {steven, stephen}; 'Kate' → {katherine, catherine} — the second must link too."""
    stephen = _b("Stephen", "Miller")
    assert match_document(["Steve Miller"], [stephen])
    catherine = _b("Catherine", "Doe")
    assert match_document(["Kate Doe"], [catherine])


def test_1099_uses_the_real_document_type_slug() -> None:
    """Document.document_type for a 1099 is the slug '1099', not 'form_1099'."""
    data = {"recipient_name": {"value": "Akash Patel", "source": None, "confidence": None}}
    assert asserted_names_for(data, "1099") == ["Akash Patel"]


def test_borrower_name_fields_keys_are_real_document_type_slugs() -> None:
    """Guard the parallel BORROWER_NAME_FIELDS map against drift from the extractor registry."""
    from app.ai.extraction import EXTRACTORS
    from app.services.borrower_name_matching import BORROWER_NAME_FIELDS

    assert set(BORROWER_NAME_FIELDS) <= set(EXTRACTORS)


def test_shared_surname_different_first_name_does_not_link() -> None:
    """Same last name is not enough — a different first name must not link."""
    akash = _b("Akash", "Patel")
    # A document about a different Patel (no first-name support) must not match Akash.
    assert match_document(["Sanjay Patel"], [akash]) == []


def test_last_comma_first_is_normalized() -> None:
    akash = _b("Akash", "Patel")
    results = match_document(["Patel, Akash"], [akash])
    assert results and results[0].borrower_id == akash.borrower_id


def test_normalize_drops_suffix_and_punctuation() -> None:
    assert normalize_name("Robert A. Smith Jr.") == ["robert", "a", "smith"]
    assert normalize_name("  ") == []
    assert normalize_name(None) == []


def test_asserted_names_reads_registered_field_excludes_counterparty() -> None:
    # gift_letter: recipient (borrower) is used, donor (counterparty) is not.
    data = {
        "recipient_name": {"value": "Akash Patel", "source": None, "confidence": None},
        "donor_name": {"value": "Rakesh Patel", "source": None, "confidence": None},
    }
    assert asserted_names_for(data, "gift_letter") == ["Akash Patel"]
    # a type with no registered borrower-name field asserts nothing
    assert asserted_names_for({"appraised_value": {"value": "500000"}}, "appraisal") == []
    # absent field → no name
    assert asserted_names_for({}, "pay_stub") == []

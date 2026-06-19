"""Tests for the document-type catalog (LP-58) — tier + category lookups.

The catalog is the single source of truth: each known ``document_type`` maps to a
``(tier, category)``; anything else defaults to the long-tail (Tier 3 / Misc).
These tests pin that contract — the 3 existing Tier-1 types, a planned Tier-1
type, a Tier-2 type, and the unknown default — plus the catalog's internal
consistency (no slug maps to two tiers; every entry has a valid category).
"""

import pytest
from app.documents.catalog import (
    CATALOG,
    get_category,
    get_tier,
    get_tier_and_category,
    is_cataloged,
)
from app.models.document import DocumentCategory, Tier

# --------------------------------------------------------------------------- #
# Tier 1 — the 3 existing types (must stay Tier 1, unchanged)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("document_type", "category"),
    [
        ("pay_stub", DocumentCategory.INCOME_EMPLOYMENT),
        ("w2", DocumentCategory.INCOME_EMPLOYMENT),
        ("bank_statement", DocumentCategory.ASSETS),
    ],
)
def test_existing_types_are_tier_1(document_type: str, category: DocumentCategory) -> None:
    assert get_tier(document_type) is Tier.TIER_1
    assert get_category(document_type) == category
    assert is_cataloged(document_type) is True


# --------------------------------------------------------------------------- #
# Tier 1 — planned types (cataloged now; extractors arrive in LP-60..64)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("document_type", "category"),
    [
        ("1099", DocumentCategory.INCOME_EMPLOYMENT),
        ("voe", DocumentCategory.INCOME_EMPLOYMENT),
        ("tax_return", DocumentCategory.INCOME_EMPLOYMENT),
        ("investment_account", DocumentCategory.ASSETS),
        ("gift_letter", DocumentCategory.ASSETS),
        ("purchase_agreement", DocumentCategory.PROPERTY),
        ("drivers_license", DocumentCategory.BORROWER_INFO),
    ],
)
def test_planned_tier_1_types(document_type: str, category: DocumentCategory) -> None:
    assert get_tier(document_type) is Tier.TIER_1
    assert get_category(document_type) == category


# --------------------------------------------------------------------------- #
# Tier 2 — the starter set
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("document_type", "category"),
    [
        ("credit_report", DocumentCategory.CREDIT),
        ("closing_disclosure", DocumentCategory.DISCLOSURES),
        ("flood_certification", DocumentCategory.PROPERTY),
        ("verification_of_deposit", DocumentCategory.ASSETS),
        ("passport", DocumentCategory.BORROWER_INFO),
    ],
)
def test_tier_2_starter_types(document_type: str, category: DocumentCategory) -> None:
    assert get_tier(document_type) is Tier.TIER_2
    assert get_category(document_type) == category


# --------------------------------------------------------------------------- #
# Unknown / absent → the long-tail default (Tier 3 / Misc)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("document_type", ["boat_registration", "totally_made_up", "", None])
def test_unknown_defaults_to_tier_3_misc(document_type: str | None) -> None:
    assert get_tier(document_type) is Tier.TIER_3
    assert get_category(document_type) == DocumentCategory.MISC
    assert is_cataloged(document_type) is False


def test_get_tier_and_category_matches_individual_getters() -> None:
    for slug in ["pay_stub", "credit_report", "unknown_type", None]:
        tier, category = get_tier_and_category(slug)
        assert tier == get_tier(slug)
        assert category == get_category(slug)


# --------------------------------------------------------------------------- #
# Catalog internal consistency
# --------------------------------------------------------------------------- #


def test_catalog_entries_are_well_formed() -> None:
    """Every catalog entry is a (Tier, DocumentCategory) pair."""
    for slug, (tier, category) in CATALOG.items():
        assert isinstance(slug, str) and slug, f"bad slug: {slug!r}"
        assert isinstance(tier, Tier), f"{slug} has non-Tier {tier!r}"
        assert isinstance(category, DocumentCategory), f"{slug} has non-category {category!r}"


def test_catalog_has_no_tier_3_entries() -> None:
    """Tier 3 is the *default* for uncataloged types — never an explicit entry."""
    tier_3 = [slug for slug, (tier, _) in CATALOG.items() if tier is Tier.TIER_3]
    assert tier_3 == [], f"Tier 3 should be the default, not cataloged: {tier_3}"


def test_existing_three_types_present_as_tier_1() -> None:
    """A guard: the 3 Phase-1 types must remain cataloged as Tier 1."""
    for slug in ("pay_stub", "w2", "bank_statement"):
        assert CATALOG[slug][0] is Tier.TIER_1

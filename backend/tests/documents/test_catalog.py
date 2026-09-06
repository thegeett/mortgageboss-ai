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
    match_catalog_type,
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
        # LP-441: types WITHOUT a schema spec stay Tier-2 (credit_report / flood_certification /
        # verification_of_deposit were promoted by the tier merge — they have specs).
        ("collection_account_letter", DocumentCategory.CREDIT),
        # closing_disclosure / loan_estimate were promoted Tier 2 -> Tier 1 (LP-470, headline spec);
        # truth_in_lending is a still-Tier-2 DISCLOSURES type with no spec.
        ("truth_in_lending", DocumentCategory.DISCLOSURES),
        ("warranty_deed", DocumentCategory.PROPERTY),
        ("money_market_statement", DocumentCategory.ASSETS),
        # passport was promoted Tier-2 -> Tier-1 (LP-472, shared identity extractor + spec 121).
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


# --------------------------------------------------------------------------- #
# Comprehensive taxonomy (LP-59) — ~80 types, ~18 Tier 1, spread across all 7
# categories. The exact count is a starter (refine with Priya); assert the shape.
# --------------------------------------------------------------------------- #


def test_catalog_is_comprehensive() -> None:
    """The taxonomy spans ~80 types (industry-standard starter)."""
    assert len(CATALOG) >= 80


def _spec_document_types() -> set[str]:
    """Every ``document_type`` declared by a schema spec under app/schema_specs/."""
    import json

    from app.schema_specs import SPECS_DIR as specs

    return {
        json.loads(p.read_text(encoding="utf-8"))["document_type"]
        for p in specs.glob("[0-9]*.json")
    }


def _tier1_spec_drift(
    catalog: dict[str, tuple[Tier, DocumentCategory]], spec_types: set[str]
) -> tuple[set[str], set[str]]:
    """The invariant's engine (LP-441): a catalog type is Tier-1 IFF it has a schema spec.

    Returns ``(tier1_without_spec, cataloged_with_spec_not_tier1)`` — both empty ⇔ the invariant holds.
    """
    tier_1 = {slug for slug, (tier, _) in catalog.items() if tier is Tier.TIER_1}
    with_spec = {slug for slug in catalog if slug in spec_types}
    return tier_1 - with_spec, with_spec - tier_1


def test_tier_1_iff_the_type_has_a_schema_spec() -> None:
    """LP-441 (replaces the == 18 count): extraction coverage is a DELIBERATE property, not drift — a
    catalog type is Tier-1 (deserves full extraction) IF AND ONLY IF it has a schema spec. This replaces
    ``test_eighteen_tier_1_types``: the tier merge (Geet) moved every spec'd type to Tier-1, so a raw count
    is meaningless; the bijection with the spec corpus is the property that must hold. A count assertion
    would pass no matter what drifted; this fails both ways (a Tier-1 with no spec, or a spec'd type left
    at Tier-2)."""
    missing, tier2_with_spec = _tier1_spec_drift(CATALOG, _spec_document_types())
    assert missing == set(), f"Tier-1 types with NO schema spec (undeliberate coverage): {missing}"
    assert tier2_with_spec == set(), (
        f"spec'd catalog types left at Tier-2 (missed the merge): {tier2_with_spec}"
    )


def test_the_invariant_fails_on_a_drift_case() -> None:
    """The replacement invariant is a real guard, not a tautology: it flags both drift directions."""
    # A Tier-1 type with no spec.
    drift_a = {"made_up_type": (Tier.TIER_1, DocumentCategory.MISC)}
    assert _tier1_spec_drift(drift_a, set())[0] == {"made_up_type"}
    # A spec'd catalog type left at Tier-2.
    drift_b = {"has_a_spec": (Tier.TIER_2, DocumentCategory.MISC)}
    assert _tier1_spec_drift(drift_b, {"has_a_spec"})[1] == {"has_a_spec"}


def test_every_spec_document_type_resolves_to_a_catalog_entry() -> None:
    """LP-442 — THE MEASURE, and the whole point of the ticket: the schema and catalog vocabularies
    are reconciled, so EVERY spec ``document_type`` the extractors are keyed by is a catalog key the
    classifier can emit. An unreconciled type routes to classified-only forever with no error — the
    silent-routing failure. Was 36/108 before this ticket; now every spec resolves.
    """
    spec_types = _spec_document_types()
    unresolved = spec_types - set(CATALOG)
    assert unresolved == set(), (
        f"spec types the classifier can never emit (silent routing): {unresolved}"
    )
    # 114 + LP-467 (cert_of_liability_insurance, service_invoice) + LP-472 (passport, 121)
    # + LP-642 step 2 (comparable_rent_schedule 122, small_residential_income_appraisal 123) — the
    # Form 1007 / 1025 rent schedules, which B3-3.8-02 makes mandatory where rental income qualifies
    # the loan and which had no spec, no extractor and no catalog type until LP-642.
    assert len(spec_types) == 123


def test_the_four_merges_and_the_split_resolve() -> None:
    """LP-442 decisions 1-3: the merged spec types now live under their catalog keys, and the split
    produced two distinct catalog keys (both promoted to Tier-1 by the LP-441 invariant)."""
    spec_types = _spec_document_types()
    # The 4 merges: the OLD spec names are gone; the catalog TARGETS carry the spec (→ Tier-1).
    for old in (
        "aba",
        "consent_to_use_electronic_records_and_signatures",
        "k_1_schedule_1065_1120s",
        "mortgage_payoff",
    ):
        assert old not in spec_types, f"{old} should have been merged/renamed away"
    for target in (
        "affiliated_business_disclosure",
        "e_consent_disclosure",
        "k1_statement",
        "payoff_statement",
    ):
        assert target in spec_types, f"{target} should now carry a spec"
        assert get_tier(target) is Tier.TIER_1
    # payoff_statement (PROPERTY), not debt_payoff_statement (CREDIT) — the verified mortgage-payoff target.
    assert get_category("payoff_statement") is DocumentCategory.PROPERTY
    # The split: one spec became two, both distinct catalog keys, both Tier-1.
    assert "alimony_income_verification" not in spec_types
    for split in ("alimony_income", "child_support_income"):
        assert split in spec_types and get_tier(split) is Tier.TIER_1
    # Decision 2: the generic borrower_authorization is retired.
    assert "borrower_authorization" not in CATALOG


def test_all_seven_categories_represented() -> None:
    present = {category for _, category in CATALOG.values()}
    assert present == {
        DocumentCategory.INCOME_EMPLOYMENT,
        DocumentCategory.ASSETS,
        DocumentCategory.PROPERTY,
        DocumentCategory.CREDIT,
        DocumentCategory.DISCLOSURES,
        DocumentCategory.BORROWER_INFO,
        DocumentCategory.MISC,
    }


@pytest.mark.parametrize(
    ("document_type", "tier", "category"),
    [
        # A spread across categories + both tiers (LP-59 additions).
        ("tax_transcript", Tier.TIER_2, DocumentCategory.INCOME_EMPLOYMENT),
        # LP-442: k1_statement was promoted to Tier-1 (the k_1_schedule spec merged into it);
        # unemployment_income_letter is a spec-less INCOME type that stays Tier-2.
        ("unemployment_income_letter", Tier.TIER_2, DocumentCategory.INCOME_EMPLOYMENT),
        ("brokerage_statement", Tier.TIER_2, DocumentCategory.ASSETS),
        ("certificate_of_deposit", Tier.TIER_2, DocumentCategory.ASSETS),
        # LP-441: appraisal / bankruptcy_discharge / permanent_resident_card / URLA were promoted to
        # Tier-1 by the merge (they have specs) — swapped for spec-less types that stay Tier-2.
        ("home_inspection_report", Tier.TIER_2, DocumentCategory.PROPERTY),
        ("warranty_deed", Tier.TIER_2, DocumentCategory.PROPERTY),
        ("credit_supplement", Tier.TIER_2, DocumentCategory.CREDIT),
        ("student_loan_statement", Tier.TIER_2, DocumentCategory.CREDIT),
        ("notice_of_right_to_cancel", Tier.TIER_2, DocumentCategory.DISCLOSURES),
        ("intent_to_proceed", Tier.TIER_2, DocumentCategory.DISCLOSURES),
        ("military_id", Tier.TIER_2, DocumentCategory.BORROWER_INFO),
        ("power_of_attorney", Tier.TIER_2, DocumentCategory.BORROWER_INFO),
        ("underwriting_approval", Tier.TIER_2, DocumentCategory.MISC),
        ("rate_lock_agreement", Tier.TIER_2, DocumentCategory.MISC),
    ],
)
def test_spread_of_new_types(document_type: str, tier: Tier, category: DocumentCategory) -> None:
    assert get_tier(document_type) is tier
    assert get_category(document_type) == category


# --------------------------------------------------------------------------- #
# LP-636 defect 5 — matching a free-text document name to a catalog type
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("document_name", "expected"),
    [
        # The four Tier-1 types LF-ZE9N lost to a confident `unknown`.
        ("a driver's license", "drivers_license"),
        ("Closing Disclosure", "closing_disclosure"),
        ("a credit report", "credit_report"),
        ("Earnest Money / EMD Receipt image", "earnest_money_receipt"),
        # An apostrophe is DELETED, not spaced — "driver s license" matched nothing and that
        # silently lost one of the four.
        # The curly apostrophe is BUILT rather than typed: a literal one trips the
        # ambiguous-character lint, while being exactly what a model emits.
        ("A Driver" + "\u2019" + "s License", "drivers_license"),
    ],
)
def test_a_name_that_says_a_catalog_type_is_matched(document_name: str, expected: str) -> None:
    assert match_catalog_type(document_name) == expected


@pytest.mark.parametrize(
    "document_name",
    [
        # LP-463's own evidence: these were CORRECT declines. There is no catalog type for any of
        # them, and declining is the right answer, not a failure. If these start matching, the
        # matcher has gone fuzzy and `misc` has stopped being reachable.
        "wiring instructions from a law firm",
        "HOA 2026 annual budget",
        "year-end compensation summary",
        "A Declaration of Condominium",
        # Order is load-bearing: the words are all present, but the name does not say the thing.
        "a receipt for the earnest money",
        # One-word slugs are ignored entirely — they appear inside ordinary prose.
        "the appraisal is attached",
        "a survey",
        "",
        None,
    ],
)
def test_a_name_that_does_not_say_a_catalog_type_is_not_matched(document_name: str | None) -> None:
    assert match_catalog_type(document_name) is None


@pytest.mark.parametrize(
    "document_name",
    [
        # CLASS A — the slug's words are present in order but SCATTERED across unrelated phrases.
        # This class was created by loosening a contiguous match to catch "Earnest Money / EMD
        # Receipt"; the bounded gap catches that case (one intervening token) while declining
        # these (two to four).
        "a closing statement with a separate disclosure page",
        "a credit memo and a separate report on fees",
        "a tax summary and a return envelope",
        "pay history and a stub of the check",
    ],
)
def test_scattered_words_are_not_a_name(document_name: str) -> None:
    assert match_catalog_type(document_name) is None


@pytest.mark.parametrize(
    "document_name",
    [
        # CLASS B — names that MENTION a document type without BEING one. These match under a
        # contiguous rule too, so ordering cannot separate them; only coverage can.
        #
        # This is the class that matters most in practice: a confident `unknown` is very often a
        # cover letter, a transmittal, a fax sheet or an email printout — exactly the documents
        # whose names reference other documents.
        "a letter from the lender about the missing closing disclosure",
        "an email asking the borrower to send a bank statement",
        "a cover page listing the credit report and the pay stub",
        "a fax cover sheet for the purchase agreement",
        "a note explaining why the tax return is late",
    ],
)
def test_a_name_that_mentions_a_type_without_being_one_is_not_matched(document_name: str) -> None:
    assert match_catalog_type(document_name) is None


def test_the_longest_match_wins() -> None:
    """A name carrying both a specific type and a general one gets the specific one."""
    assert (
        match_catalog_type("prior closing disclosure final cd from purchase")
        == "prior_closing_disclosure_final_cd_from_purchase"
    )


def test_every_matched_slug_is_actually_in_the_catalog() -> None:
    """The matcher builds its answers from CATALOG, so a hit must be routable.

    Cheap, and it is what stops a returned slug that ``get_tier``/``get_category`` cannot resolve.
    """
    for name in ("a driver's license", "Closing Disclosure", "a credit report"):
        slug = match_catalog_type(name)
        assert slug is not None
        assert is_cataloged(slug)

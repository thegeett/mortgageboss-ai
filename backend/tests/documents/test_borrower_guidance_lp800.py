"""LP-800 — the borrower instruction catalog: who holds a document, and how to ask for it.

The catalog answered "what IS this document". Phase 4 has to send the ask, and that needs two
things it could not answer: whose document it is, and what to say to the person who has it.

The tests are shaped by what fails silently. A missing party does not raise — it would fall to a
default and address the request to somebody. Prose that names a catalog slug does not raise — it
reaches a borrower reading "please provide a comparable_rent_schedule". Instructions written for a
document the borrower cannot obtain do not raise either; they just waste a round trip and the
borrower's confidence.
"""

from __future__ import annotations

import pytest
from app.documents.catalog import (
    _BORROWER_INSTRUCTIONS,
    _RESPONSIBLE_PARTY,
    CATALOG,
    GUIDANCE,
    BorrowerGuidance,
    ResponsibleParty,
    get_guidance,
)

#: The plan scopes full authoring to "roughly 25" borrower-facing types. Pinned as a floor, not an
#: equality: adding a full entry is the improvement this file exists to encourage, and a test that
#: broke on the 29th would punish it.
_MIN_FULL_ENTRIES = 25


# --------------------------------------------------------------------------------------------- #
# Sync with the catalog — the same guarantee the classification prompt has
# --------------------------------------------------------------------------------------------- #
def test_guidance_exactly_covers_the_catalog() -> None:
    """Every catalog type has guidance, and no guidance entry lacks a catalog type.

    Exactly the shape of `test_indicators_exactly_cover_the_catalog`, for the same reason: a type
    the classifier can return must be a type the drafting engine can address.
    """
    missing = set(CATALOG) - set(GUIDANCE)
    orphan = set(GUIDANCE) - set(CATALOG)
    assert not missing, f"catalog types with no guidance: {sorted(missing)}"
    assert not orphan, f"guidance with no catalog type: {sorted(orphan)}"


def test_every_entry_carries_a_party() -> None:
    """The one field that is never optional. A type with no party is a type Phase 4 cannot address,
    and the failure mode is not an exception — it is a request sent to the wrong person."""
    for slug, guidance in GUIDANCE.items():
        assert isinstance(guidance.responsible_party, ResponsibleParty), slug


# --------------------------------------------------------------------------------------------- #
# The instructions themselves
# --------------------------------------------------------------------------------------------- #
def _full_entries() -> dict[str, BorrowerGuidance]:
    return {slug: g for slug, g in GUIDANCE.items() if g.borrower_label is not None}


def test_enough_types_have_full_instructions() -> None:
    """The plan's scoping decision, kept honest. Party-only for all 166 satisfies every other test
    in this file, and would ship a catalog that tells a drafter nothing it did not already know."""
    assert len(_full_entries()) >= _MIN_FULL_ENTRIES


def test_a_full_entry_is_actually_full() -> None:
    """A label with no obtaining instructions and no completeness rule is the shape that looks done
    on a checklist and reads as an empty ask in an email."""
    for slug, g in _full_entries().items():
        assert g.how_to_obtain, f"{slug}: labelled but no how_to_obtain"
        assert g.completeness_rule, f"{slug}: labelled but no completeness_rule"
        assert g.common_rejects, f"{slug}: labelled but no common_rejects"
        assert all(reject.strip() for reject in g.common_rejects), slug


def test_instructions_exist_only_where_the_borrower_can_act() -> None:
    """Instructions on a lender-ordered appraisal or a title commitment would tell a borrower how to
    do something they cannot do. The party field is what stops a drafter offering them the attempt."""
    for slug, g in _full_entries().items():
        assert g.responsible_party is ResponsibleParty.BORROWER, (
            f"{slug} carries borrower instructions but is held by {g.responsible_party}"
        )


def test_no_borrower_text_leaks_a_catalog_slug() -> None:
    """The slug is an internal identifier. "please provide a comparable_rent_schedule" is the exact
    sentence this catalog exists to prevent, and nothing downstream would flag it — it is a valid
    string that renders fine and reads as a system leak only to the person receiving it."""
    for slug, g in GUIDANCE.items():
        text = " ".join(
            part
            for part in (
                g.borrower_label,
                g.how_to_obtain,
                g.completeness_rule,
                *g.common_rejects,
            )
            if part
        )
        assert "_" not in text, f"{slug}: borrower-facing text contains an underscore: {text!r}"


# --------------------------------------------------------------------------------------------- #
# The lookup — the catalog's never-raise discipline
# --------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("unknown", [None, "", "not_a_real_type", "Bank Statement"])
def test_unknown_types_fall_back_to_the_processor(unknown: str | None) -> None:
    """Failing towards "someone on our side deals with this" is the safe direction. The other
    default would generate a borrower-facing ask for a document nobody has classified.

    "Bank Statement" is in the list deliberately: `get_guidance` does not normalise, so the
    capitalised form is an unknown type, and a future normalisation must change this test on purpose."""
    guidance = get_guidance(unknown)
    assert guidance.responsible_party is ResponsibleParty.PROCESSOR
    assert guidance.borrower_label is None


def test_a_known_borrower_type_returns_its_instructions() -> None:
    """The positive control for every fallback assertion above — without it, a `get_guidance` that
    returned the default for everything would pass the whole parametrised test."""
    guidance = get_guidance("bank_statement")
    assert guidance.responsible_party is ResponsibleParty.BORROWER
    assert guidance.borrower_label == "Bank statements — the two most recent months"
    assert "page 1 of 5" in guidance.common_rejects


def test_a_known_non_borrower_type_returns_a_party_and_no_prose() -> None:
    """The other half of the control. An appraisal is cataloged, so it is not the unknown case, and
    it is lender-ordered, so it is not the instructed case — the third state has to be reachable."""
    guidance = get_guidance("appraisal")
    assert guidance.responsible_party is ResponsibleParty.LENDER
    assert guidance.borrower_label is None
    assert guidance.common_rejects == ()


def test_template_urls_are_all_absent_for_now() -> None:
    """Pins the deliberate omission rather than leaving it as an untested intention. LP-817 owns the
    template library; a link that resolves to nothing is worse in an email than no link, so the
    first entry to set one should have to change this test and say why."""
    assert all(g.template_url is None for g in GUIDANCE.values())


# --------------------------------------------------------------------------------------------- #
# The instruction set cannot silently shrink (review finding)
# --------------------------------------------------------------------------------------------- #
def test_every_instruction_is_keyed_on_a_REAL_catalog_type() -> None:
    """A misspelled instruction key is dropped in silence, and nothing else here notices.

    ``GUIDANCE`` is built by walking ``_RESPONSIBLE_PARTY``, so an instruction keyed on a slug that
    map does not carry never enters it. The coverage test then sees no orphan (the key is not in
    GUIDANCE to be orphaned), and the floor test is a `>=`, so 28 entries quietly becoming 27 still
    passes. Measured before this test existed: renaming `pay_stub` to `pay_stubs` — the single most
    requested document in a file — left the whole suite green while its borrower instructions
    stopped reaching anyone.
    """
    unknown = set(_BORROWER_INSTRUCTIONS) - set(_RESPONSIBLE_PARTY)
    assert not unknown, f"instructions keyed on types no catalog slug matches: {sorted(unknown)}"


def test_the_types_the_plan_names_all_have_full_instructions() -> None:
    """The floor is a `>=`, which cannot tell WHICH types are covered — 25 entries for the rarest
    types in the catalog would satisfy it. These are the ones the build plan names as the ones a
    borrower is actually asked for, so they are pinned by name rather than by count."""
    named = {
        "pay_stub",
        "w2",
        "bank_statement",
        "tax_return",
        "drivers_license",
        "homeowners_insurance",
        "gift_letter",
        "letter_of_explanation",
        "divorce_decree",
        "lease_agreement",
        "emd_withdrawal_proof",
    }
    missing = {slug for slug in named if slug not in _full_entries()}
    assert not missing, f"plan-named borrower types with no full entry: {sorted(missing)}"

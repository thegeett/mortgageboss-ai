"""Tests for the catalog-driven classification prompt (LP-59).

The prompt's type list is DERIVED from the catalog, so the two cannot drift. These
tests pin that contract: every catalog type has a recognition indicator (and vice
versa), the rendered prompt lists every catalog type grouped by category, and the
template placeholder is fully resolved. This is the "catalog/prompt sync — one
taxonomy" guarantee.
"""

import pytest
from app.ai.classification_prompt import (
    DOCUMENT_TYPE_INDICATORS,
    render_classification_prompt,
)
from app.documents.catalog import CATALOG


def test_indicators_exactly_cover_the_catalog() -> None:
    """Every catalog type has an indicator, and no indicator lacks a catalog type."""
    catalog_types = set(CATALOG)
    indicator_types = set(DOCUMENT_TYPE_INDICATORS)
    missing_indicator = catalog_types - indicator_types
    orphan_indicator = indicator_types - catalog_types
    assert not missing_indicator, f"catalog types with no indicator: {missing_indicator}"
    assert not orphan_indicator, f"indicators with no catalog type: {orphan_indicator}"


def test_every_indicator_is_nonempty() -> None:
    for slug, text in DOCUMENT_TYPE_INDICATORS.items():
        assert text.strip(), f"empty indicator for {slug}"


def test_rendered_prompt_lists_every_catalog_type() -> None:
    """The single source of truth for the type list is the catalog — all appear."""
    prompt = render_classification_prompt()
    for slug in CATALOG:
        assert slug in prompt, f"{slug} missing from the rendered prompt"


def test_rendered_prompt_placeholder_is_resolved() -> None:
    prompt = render_classification_prompt()
    assert "{document_type_catalog}" not in prompt  # fully injected
    # Spot-check the framing survived and the JSON contract is present.
    assert "KNOWN DOCUMENT TYPES" in prompt
    assert '"document_type"' in prompt
    assert '"confidence"' in prompt


def test_rendered_prompt_groups_by_category() -> None:
    prompt = render_classification_prompt()
    for header in ("INCOME / EMPLOYMENT", "ASSETS", "PROPERTY", "CREDIT", "DISCLOSURES"):
        assert header in prompt


def test_prompt_is_cached_same_object() -> None:
    """render_classification_prompt is @cache'd — repeated calls are identical."""
    assert render_classification_prompt() is render_classification_prompt()


@pytest.mark.parametrize(
    "slug",
    ["pay_stub", "w2", "bank_statement", "closing_disclosure", "loan_estimate"],
)
def test_distinguishable_lookalikes_have_indicators(slug: str) -> None:
    """Types that are easy to confuse must carry distinguishing cues."""
    assert slug in DOCUMENT_TYPE_INDICATORS
    assert len(DOCUMENT_TYPE_INDICATORS[slug]) > 20

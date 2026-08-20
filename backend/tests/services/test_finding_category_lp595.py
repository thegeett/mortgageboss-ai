"""LP-595 — every active rule's findings are filed under a category that fits.

THE BUG. ``_RULE_CATEGORY`` had nine entries and ``reconcile_run`` took
``default_category=FindingCategory.ASSETS``, so the other sixty-nine active rules were all filed as
ASSETS: PR-4 (appraisal completeness), every IN-* income rule, CL-1 (rate lock), MI-1 (PMI). On
LF-3CVT that was twenty-eight of thirty findings in one category, which makes grouping or filtering
by category worse than useless — it looks authoritative and is wrong.

Nothing failed, because a misfiled finding is silent. That is what this file fixes: an unclassified
rule is now a test failure rather than a quiet inheritance of someone else's category.
"""

from __future__ import annotations

from app.models.finding import FindingCategory
from app.services.verification_run import (
    _FAMILY_CATEGORY,
    _RULE_CATEGORY,
    category_for_rule,
)
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS


def test_every_active_rule_has_a_category() -> None:
    """THE POINT OF THE TICKET. A new rule whose family is not in the table fails here rather than
    landing in ASSETS on a processor's screen."""
    unclassified = sorted(r for r in ACTIVE_RULE_IDS if category_for_rule(r) is None)

    assert not unclassified, (
        "these active rules resolve to no category and would be filed under the fallback: "
        f"{unclassified}. Add the family to _FAMILY_CATEGORY, or the rule to _RULE_CATEGORY."
    )


def test_the_assets_category_is_no_longer_a_dumping_ground() -> None:
    """The regression in one assertion. Before this ticket 69 of 78 active rules resolved to ASSETS;
    ASSETS is now only what the AS family (and anything explicitly mapped) actually is."""
    assets = sorted(r for r in ACTIVE_RULE_IDS if category_for_rule(r) is FindingCategory.ASSETS)

    assert all(r.startswith("AS-") for r in assets), (
        f"a non-AS rule is filed under assets: {[r for r in assets if not r.startswith('AS-')]}"
    )
    # A handful, not most of the engine.
    assert len(assets) < len(ACTIVE_RULE_IDS) / 4, (
        f"{len(assets)} of {len(ACTIVE_RULE_IDS)} rules are ASSETS — the dumping ground is back"
    )


def test_a_per_rule_entry_beats_its_family() -> None:
    """The ID family splits — 1/2/3/4 compare a fact ACROSS sources, 6/7/9 are about a document — so
    the override has to win or the split silently collapses back to the family answer."""
    assert _FAMILY_CATEGORY["ID"] is FindingCategory.CROSS_SOURCE
    assert category_for_rule("ID-1") is FindingCategory.CROSS_SOURCE  # family
    assert category_for_rule("ID-6") is FindingCategory.DOCUMENTATION  # override wins
    assert category_for_rule("DT-7") is FindingCategory.REGULATORY  # ATR is regulatory, not credit
    assert category_for_rule("DT-8") is FindingCategory.CREDIT  # ...but its family is not


def test_overrides_are_not_restating_their_family() -> None:
    """An override that agrees with its family is dead weight that reads as a decision. Catches a
    future edit that changes a family and leaves a now-redundant override behind."""
    redundant = {
        rule_id: category.value
        for rule_id, category in _RULE_CATEGORY.items()
        if _FAMILY_CATEGORY.get(rule_id.split("-")[0]) is category
    }

    assert not redundant, f"these overrides just repeat their family: {redundant}"


def test_income_rules_are_filed_as_income() -> None:
    """The headline misfiling, named directly: sixteen income rules were reaching processors as
    'assets'."""
    income = [r for r in ACTIVE_RULE_IDS if r.startswith("IN-")]
    assert income, "no IN-* rules are active — this test has stopped testing anything"
    assert all(category_for_rule(r) is FindingCategory.INCOME for r in income)

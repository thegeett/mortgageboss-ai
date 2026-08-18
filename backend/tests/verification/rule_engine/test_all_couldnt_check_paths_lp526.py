"""LP-526 — three defects found by reading the FIRST REAL RUN of LP-524/525.

Everything here was invisible to the tests that shipped those tickets, and visible within seconds of
querying the findings a processor would actually see.

1. **TWO OF THREE couldn't-check PATHS HAD NO FIX.** `couldnt_check` is produced by the fail-closed
   gate, by the applicability resolver, AND by the confidently-absent-document check. LP-524 wired the
   gate — the common case — and I did not check whether it was the only case. On the real file that
   left 6 of 15 abstentions with no action while 9 had one: CR-6 x4 through applicability, ID-7 and
   IN-8 through absent-document.

2. **"the whether this account carries a derogatory mark could not be determined."** Message builders
   wrote ``f"the {fact_label(...)}"``, which is right for a noun phrase and broken for the 8+ labels
   phrased as questions. CR-6 shipped that sentence four times.

3. **"no voe is in the file."** ``document_label`` lowercases an acronym, so the request named the
   document as a typo.

The lesson is the pattern, not the bugs: each was cheap to find by looking at output and impossible to
find by reasoning about the code that produced it.
"""

from __future__ import annotations

import pytest
from app.verification.rule_engine.reasons import document_label, fact_label, fact_phrase
from app.verification.rules.specs import load_rule_spec


# --------------------------------------------------------------------------------------------- #
# 1. EVERY couldn't-check PATH CARRIES THE FIX
# --------------------------------------------------------------------------------------------- #
def test_every_path_that_can_abstain_routes_through_one_helper() -> None:
    """⚠️ THE STRUCTURAL GUARD. Three call sites, one helper — so a fourth path is a compile-time
    thought rather than a silent omission. Asserted on the SOURCE because the alternative is
    reconstructing three evaluator paths in fixtures, and what actually went wrong was a missing call,
    not a wrong one."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[3] / "app/verification/rule_engine/deterministic.py"
    ).read_text()

    call_sites = [
        line
        for line in source.splitlines()
        if "_fix_for(det" in line and not line.lstrip().startswith("def ")
    ]

    assert len(call_sites) == 3, (
        "a couldn't-check path is not passing the rule's fix — LP-524 wired only the gate and left "
        f"6 of 15 real abstentions with no action (found {len(call_sites)})"
    )


def test_the_rules_that_abstain_via_the_other_two_paths_have_fixes() -> None:
    """CR-6 abstains through applicability; ID-7 and IN-8 through absent-document. All three had text
    written and none of it reached a finding."""
    for rule_id in ("CR-6", "ID-7", "IN-8"):
        spec = load_rule_spec(rule_id)
        assert spec.deterministic is not None
        assert spec.deterministic.couldnt_check_fix, rule_id


# --------------------------------------------------------------------------------------------- #
# 2. A QUESTION LABEL IS NOT A NOUN
# --------------------------------------------------------------------------------------------- #
def test_a_question_label_does_not_get_an_article() -> None:
    """The exact string a processor saw four times on LF-WCHG."""
    assert fact_label("liab.is_derogatory") == "whether this account carries a derogatory mark"
    assert fact_phrase("liab.is_derogatory") == "whether this account carries a derogatory mark"
    assert not fact_phrase("liab.is_derogatory").startswith("the whether")


def test_a_noun_label_still_gets_its_article() -> None:
    """The fix must not strip the article from the labels that need one — most of them."""
    assert fact_phrase("credit.report_age_months_at_closing").startswith("the ")


def test_no_curated_label_can_produce_the_double_article() -> None:
    """⚠️ THE CLASS, not the instance. Over 8 labels are phrased as questions; CR-6 was simply the one
    that reached a real file first. This sweeps every curated label so the next one cannot ship."""
    from app.verification.rule_engine.reasons import _FACT_LABELS

    for tag_id in _FACT_LABELS:
        phrase = fact_phrase(tag_id)
        assert not phrase.startswith("the whether"), tag_id
        assert not phrase.startswith("the is "), tag_id
        assert not phrase.startswith("the does "), tag_id


# --------------------------------------------------------------------------------------------- #
# 3. AN ACRONYM IS NOT A WORD
# --------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("slug", "expected"),
    [("voe", "VOE"), ("vom", "VOM"), ("w2", "W-2"), ("hoa", "HOA")],
)
def test_an_acronym_document_reads_as_an_acronym(slug: str, expected: str) -> None:
    """ "no voe is in the file" reads as a typo to the person being asked to produce one."""
    assert document_label(slug) == expected


@pytest.mark.parametrize("slug", ["title_commitment", "appraisal", "bank_statement"])
def test_an_ordinary_document_is_untouched(slug: str) -> None:
    """The acronym map must stay small and explicit — uppercasing a real word would be worse than the
    bug it fixes."""
    assert document_label(slug) == slug.replace("_", " ")

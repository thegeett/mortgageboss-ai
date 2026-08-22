"""bug-001 — `txn.counterparty`: the structured layer had no name for who a payment went to.

FR-5 asks a processor to "obtain the account details and add it" to the 1003, and the liability they
then create needs a `holder_name`. The tag was in `fact_tags.csv` from the start — `produced_by: AI`,
listing FR-5 among its consumers — and NO group produced it. On a real file all four Chase card
payments carried an amount, a category and an empty counterparty, so the finding's text named Chase
only because the COMPOSER read the raw description, while nothing structured held the name.

It is a FREE STRING, so it cannot take `_ai_tag`'s path: that coerces anything outside a value set to
unknown, which is right for an enum and impossible for a creditor's name.
"""

from __future__ import annotations

from app.ai.tag_production import TagJudgment
from app.services.tag_production import _ai_string_tag


def _j(value: str, conf: float | None = 0.9) -> TagJudgment:
    return TagJudgment(value=value, confidence=conf, reasoning="from the description")


def test_a_name_is_kept_as_written() -> None:
    tag = _ai_string_tag(_j("Chase"), "txn1", "absent")
    assert tag.value == "Chase"
    assert tag.confidence == 0.9


def test_surrounding_whitespace_is_trimmed_but_the_name_is_not_restyled() -> None:
    """Beyond whitespace the name is left alone. The prompt asks the model to strip the bank's
    reference numbers; second-guessing what remains would be this layer deciding what a creditor is
    called."""
    assert _ai_string_tag(_j("  Lake Michigan Credit Union  "), "t", "x").value == (
        "Lake Michigan Credit Union"
    )


def test_a_missing_judgment_is_unknown_with_the_absent_reason() -> None:
    tag = _ai_string_tag(None, "txn1", "not returned by structuring pass")
    assert tag.value == "unknown"
    assert tag.reasoning == "not returned by structuring pass"
    assert tag.confidence is None  # never a fabricated confidence on a fallback


def test_a_blank_name_is_unknown_not_an_empty_creditor() -> None:
    """An empty string would write a liability holder nobody can read."""
    assert _ai_string_tag(_j("   "), "txn1", "absent").value == "unknown"


def test_the_words_for_nothing_are_unknown_rather_than_a_creditor_called_null() -> None:
    """A model asked for `<name|null>` sometimes answers with the word. Left alone, "null" would
    become a holder_name and reach the application's liability list."""
    for spelling in ("null", "None", "UNKNOWN", "n/a"):
        assert _ai_string_tag(_j(spelling), "txn1", "absent").value == "unknown"


def test_no_counterparty_is_a_FACT_and_must_not_degrade_the_run() -> None:
    """The most consequential property here, and a test caught it.

    `_scan_tag_degradations` marks a run degraded on the STRUCTURAL signature
    `value=="unknown"` + produced_by AI + `confidence is None` — and a degraded run MUST NOT RETIRE
    findings (LP-322). A bank fee, a cash withdrawal and an interest credit legitimately name nobody,
    so a confidence-less fallback here would have made almost every real file degrade itself over a
    transaction that is simply not a payment to anyone."""
    tag = _ai_string_tag(_j("null", conf=0.95), "txn1", "absent")

    assert tag.value == "unknown"
    assert tag.confidence == 0.95  # the model's own judgment, kept — so NOT the degradation shape
    assert not (tag.value == "unknown" and tag.confidence is None)


def test_an_omitted_field_DOES_carry_the_fallback_shape() -> None:
    """The other half: the model returning nothing at all IS a production failure, and must still be
    visible as one."""
    tag = _ai_string_tag(None, "txn1", "not returned by structuring pass")
    assert tag.value == "unknown" and tag.confidence is None


def test_an_honest_unknown_keeps_the_models_reasoning() -> None:
    """Why there is no counterparty is more useful than the bare word."""
    assert _ai_string_tag(_j("null"), "txn1", "absent").reasoning == "from the description"


def test_a_judged_absence_with_no_reasoning_still_says_something() -> None:
    tag = _ai_string_tag(TagJudgment(value="null", confidence=0.8, reasoning=None), "t", "x")
    assert tag.reasoning == "the description names no other party"

"""The same amounts in a different order are not the same email (LP-922 follow-up review).

WHY THIS EXISTS. The product owner's rule is that a polish which changes or drops a fact is SHOWN WITH
A WARNING rather than refused, so the warnings are the only thing standing between a model's rewrite
and a borrower. Every other comparison in `email_facts` is by SET — the amounts present, the dates
present, the digit runs present — which answers "is this figure still here?" and not "does it still
say the same thing". A polish that keeps both figures and swaps what each one MEANS passes all of
them.

The case is not hypothetical: 7086's email says "closing needs $38,210.40 and $11,062.18 is verified
so far". Reversed, it holds exactly the same two amounts and tells the borrower the opposite of the
truth about their own shortfall.

The check is deliberately cheap — the ORDER the amounts appear in, not the sentence they sit in —
because parsing the roles would need the model this module exists to second-guess.
"""

from __future__ import annotations

from app.conditions.email_facts import fact_warnings

_BEFORE = (
    "<p>Why: closing needs <strong>$38,210.40</strong> and <strong>$11,062.18</strong> is verified "
    "so far.</p><ol><li>Your Capital One statements ending 9912 — all pages.</li></ol>"
)


def _sentences(before: str, after: str) -> list[str]:
    return [warning.sentence for warning in fact_warnings(before, after)]


def test_swapping_two_amounts_is_warned_about() -> None:
    """The motivating case: both figures survive, and what each one means is reversed."""
    after = _BEFORE.replace(
        "$38,210.40</strong> and <strong>$11,062.18",
        "$11,062.18</strong> and <strong>$38,210.40",
    )

    sentences = _sentences(_BEFORE, after)

    assert sentences, "a swap that keeps both amounts must still be shown to her"
    assert any("different order" in sentence for sentence in sentences), sentences
    # The sentence names BOTH orders, because "something moved" is not actionable on its own.
    assert any(
        "$38,210.40 then $11,062.18" in sentence and "$11,062.18 then $38,210.40" in sentence
        for sentence in sentences
    ), sentences


def test_an_untouched_body_warns_about_nothing() -> None:
    """The positive control. A check that fires on every polish would be ignored within a day."""
    assert _sentences(_BEFORE, _BEFORE) == []


def test_rewording_around_the_amounts_is_not_an_order_change() -> None:
    """Polishing is the point: the prose may move as long as the figures keep their order."""
    after = _BEFORE.replace(
        "Why: closing needs <strong>$38,210.40</strong> and <strong>$11,062.18</strong> is verified "
        "so far.",
        "Why: your closing needs <strong>$38,210.40</strong>, and so far <strong>$11,062.18</strong> "
        "has been verified.",
    )

    assert _sentences(_BEFORE, after) == []


def test_a_changed_amount_is_not_reported_twice() -> None:
    """A real change already warns; an order line beside it would bury the one that matters."""
    after = _BEFORE.replace("$38,210.40", "$38,410.40")

    sentences = _sentences(_BEFORE, after)

    assert sentences == ["Dropped: $38,210.40", "Added: $38,410.40"], sentences
    assert not any("different order" in sentence for sentence in sentences), sentences

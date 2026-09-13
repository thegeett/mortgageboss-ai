"""LP-856 — ✦ polish may change how a message reads and not what it says.

THE PROMPT ASKS; THESE ENFORCE. A model that ignores an instruction is the ordinary case rather than
the exceptional one, so every constraint the ticket names is a guard as well as a sentence in the
system prompt. Acceptance 6 says it outright: "Checked, not assumed."
"""

from __future__ import annotations

import pytest
from app.ai.polish import invented_date_words, polish, refusal_for
from app.core.config import settings


# --------------------------------------------------------------------------------------------- #
# Acceptance 6 — it may not invent a date
# --------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "rewritten",
    [
        "Please send them by Friday.",
        "Please send them by friday.",
        "We will need these before Monday.",
        "Could you send them in September?",
        "Please send them by Sept 30.",
        "These are due Tue.",
    ],
)
def test_a_body_with_no_dates_may_not_gain_one(rewritten: str) -> None:
    """THE TICKET'S OWN EXAMPLE. "A polish that invents 'by Friday' is a commitment the file did not
    make" — and it has no digits in it, so the number guard cannot see it."""
    assert refusal_for("Please send the bank statements.", rewritten) is not None


@pytest.mark.parametrize(
    "rewritten",
    [
        "Please send the March statement.",
        "Could you send us the March statement when you have a moment?",
        "We still need the March statement — thank you.",
    ],
)
def test_a_date_the_processor_wrote_may_be_kept(rewritten: str) -> None:
    """THE CONTROL, and it is the one that matters: a guard that refused every date would make the
    button useless on exactly the messages processors write. The ORIGINAL licenses its own content."""
    assert refusal_for("Send the March statement.", rewritten) is None


def test_the_date_vocabulary_is_derived_rather_than_typed() -> None:
    """A list typed by hand is one that misses `Sept` the day somebody writes it. Both the full
    names and the abbreviations come from `calendar`, so the two cannot disagree about which
    months exist."""
    before = "Please send the statements."
    for word in ("Monday", "Mon", "January", "Jan", "December", "Dec", "Sunday", "Sun"):
        assert invented_date_words(before, f"Please send them in {word}.") == {word.lower()}


def test_a_word_that_merely_contains_a_day_is_not_a_date() -> None:
    """WORD BOUNDARIES. "Sunday" inside "Sundays" is a date; inside "sundries" it is not — and a
    substring match would refuse an ordinary rewrite for a reason nobody could work out."""
    assert invented_date_words("Please send it.", "Please send the sundries schedule.") == set()
    assert invented_date_words("Please send it.", "Please send the marching orders.") == set()


# --------------------------------------------------------------------------------------------- #
# It may not invent anything else either
# --------------------------------------------------------------------------------------------- #
def test_it_may_not_invent_a_number() -> None:
    assert refusal_for("Please send the statements.", "Please send the last 24 statements.") == (
        "unsupported_numbers:1"
    )


def test_a_number_the_processor_wrote_survives() -> None:
    """THE CONTROL, AND IT FOUND A REAL DEFECT.

    "Proof of the $10,000 gift deposit" is an ordinary thing to ask a borrower for. The first
    version applied `regulatory_refusal` flat to the rewrite, and that function was written for a
    MODEL-COMPOSED framing where any money amount is invented by definition — so polishing this
    message was refused as `money_amount`. The button would have done nothing on exactly the
    messages that most need tidying, for a reason nobody could work out.

    The rule is "INTRODUCED", which is what the ticket says: facts may not be ADDED. A ground the
    original already trips is the processor's own, and theirs to keep.
    """
    before = "We need proof of the $10,000 gift deposit."
    assert refusal_for(before, "Could you send proof of the $10,000 gift deposit?") is None


def test_but_an_amount_the_model_added_is_still_refused() -> None:
    """THE OTHER HALF of the case above — without this, "only a ground the original did not trip"
    could be implemented as "never refuse" and pass."""
    assert refusal_for("Please send the statements.", "Please send the $500 fee.") == "money_amount"


def test_a_message_that_already_mentions_an_amount_may_not_gain_a_DIFFERENT_ground() -> None:
    """The comparison is on the GROUND, not on "did the original trip anything". A message that
    already mentions an amount must still not acquire a commitment."""
    before = "We need proof of the $10,000 gift deposit."
    assert refusal_for(before, "Send the $10,000 proof and you are approved.") == "commitment"


@pytest.mark.parametrize(
    ("rewritten", "expected"),
    [
        ("Once we have these you are approved.", "commitment"),
        ("Your rate is 6.5%.", "rate"),
        ("We recommend using a title company for your closing.", "settlement_service"),
        ("Our routing number is on the invoice.", "payment_routing"),
    ],
)
def test_the_regulatory_floor_applies_to_a_rewrite_too(rewritten: str, expected: str) -> None:
    """IMPORTED, NOT RESTATED. `regulatory_refusal` is the same list a composed framing is held to.

    A model that turns "we need your statements" into "we can close by Friday" has made a commitment
    the file did not make, and it does not matter which button produced it. A second copy of these
    checks would drift silently, because each copy's tests would pass over its own.
    """
    assert refusal_for("Please send the bank statements.", rewritten) == expected


def test_an_empty_rewrite_is_refused() -> None:
    """A model that returned nothing would otherwise replace the message with a blank one."""
    assert refusal_for("Please send the statements.", "") == "empty"
    assert refusal_for("Please send the statements.", "   \n  ") == "empty"


def test_an_ordinary_tidy_up_passes() -> None:
    """THE POSITIVE CONTROL FOR THE WHOLE FILE. Every case above is a refusal, and a `refusal_for`
    that returned a reason for everything would satisfy all of them and make the button do nothing.
    """
    before = "hi - need the bank statements and the pay stub. thanks"
    after = (
        "Hello,\n\nCould you please send us your bank statements and your pay stub?\n\n"
        "Thank you,\nPriya"
    )
    assert refusal_for(before, after) is None


# --------------------------------------------------------------------------------------------- #
# Acceptance 2 — it fails visibly, not silently
# --------------------------------------------------------------------------------------------- #
async def test_with_the_flag_off_it_refuses_and_changes_nothing() -> None:
    """ACCEPTANCE 2. `email_draft_enabled` is off in every environment, so this is the outcome a
    processor actually gets today.

    IT MUST NOT RETURN THE TEXT UNCHANGED. That would look like a polish that decided nothing needed
    changing, and the processor could not tell the two apart — which is the silent degradation the
    ticket says is worse than an error.
    """
    assert settings.email_draft_enabled is False, "the default changed; this test's premise is gone"

    outcome = await polish("hi - need the statements. thanks")

    assert outcome.ok is False
    assert outcome.text is None
    assert outcome.refusal == "unavailable"


async def test_an_empty_body_is_refused_before_the_model_is_called() -> None:
    outcome = await polish("   ")
    assert outcome.ok is False
    assert outcome.refusal in {"unavailable", "empty"}

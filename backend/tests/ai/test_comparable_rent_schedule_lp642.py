"""LP-642 — the rent-schedule prompt, and the figures on the real forms that would pass for the one
we want.

NOTHING HERE CALLS A MODEL. The prompt is the only defence for a field a qualifying ratio rests on,
and no test can measure whether a model obeys it — so what is asserted is that the instruction still
NAMES each confusable neighbour that is really printed on the two forms. A prompt edit that quietly
drops one leaves a fabricated rent reachable, and this is the closest thing to a guard there is.

The field names were checked against the real blank forms: Freddie Mac Form 1000 / Fannie Mae Form
1007 (8/88), and Fannie Mae Form 1025 / Freddie Mac Form 72 (03/2005).
"""

from __future__ import annotations

from app.ai.prompt_loader import load_prompt

#: NEWLINES COLLAPSED. The prompt is hard-wrapped at ~100 columns, so a phrase this file asserts can
#: be split across two lines — "Final Reconciliation of Market\nRent" is, today. Matching against the
#: raw text would fail on correct content and pass only by accident of where the wrap fell.
_PROMPT = " ".join(load_prompt("extraction/comparable_rent_schedule.txt").split())


def test_the_prompt_names_where_each_form_actually_states_the_rent() -> None:
    """NEITHER FORM PRINTS "Opinion of Monthly Market Rent" AS A LINE LABEL, which the first version
    of this prompt asked for. The 1007 states it in a foot-of-page sentence; the 1025 has no
    property-level opinion at all — that column heading is per unit, and the property figure is the
    printed total."""
    assert "ESTIMATE THE MONTHLY MARKET RENT OF THE SUBJECT" in _PROMPT, "the 1007's sentence"
    assert "Total Gross Monthly Rent" in _PROMPT, "the 1025's property-level figure"
    assert "Final Reconciliation of Market Rent" in _PROMPT, "the 1007 line that is NOT the number"


def test_every_confusable_neighbour_is_named() -> None:
    """EACH OF THESE IS PRINTED ON A REAL FORM, sits near the figure we want, and passes every
    prohibition the first version wrote (not an average, not a comparable's rent, not the subject's
    actual rent). Naming them is the only lever there is.

    The worst is the per-unit one: on a four-unit 1025 it reports a quarter of the property's rent as
    the whole, and the ratio computes cleanly on it.
    """
    # ASSERTED INSIDE A PROHIBITION, NOT ANYWHERE IN THE FILE. Several of these labels also appear in
    # the DESCRIPTIVE half — the 1025's per-unit column is named there to explain where the form
    # states its rent — so "is the phrase present" cannot tell a rule from a mention. Verified: with
    # the per-unit prohibition deleted, a presence check still passed, which is a guard that would
    # survive the removal of the thing it guards.
    prohibitions = " ".join(part for part in _PROMPT.split("* ") if part.startswith("NEVER"))
    assert prohibitions, (
        "the prompt has no NEVER clauses at all — the parse is wrong, not the prompt"
    )

    for label, why in (
        ("Opinion Of Market Rent", "the 1025's PER-UNIT column — a quarter of a four-unit subject"),
        ("Total Estimated Monthly Income", "rent PLUS parking/laundry — larger, and not rent"),
        ("Total Actual Monthly Rent", "what tenants pay now, not the market opinion"),
        ("Indicated Monthly Market Rent", "the 1007 grid, per COMPARABLE — a different property"),
        ("Adjusted Monthly Rent", "a comparable's rent after adjustment"),
        ("Monthly Rental If Currently Rented", "the subject's ACTUAL rent when tenanted"),
    ):
        assert label in prohibitions, f"the prompt no longer RULES OUT {label!r} — {why}"


def test_the_prompt_refuses_a_computed_or_annual_figure() -> None:
    """A stated number and a derived one are different things, and only the first is evidence. An
    annual figure divided by twelve is arithmetic nobody signed."""
    assert "ANNUAL" in _PROMPT and "return null rather than dividing" in _PROMPT
    assert "NEVER average the comparable rentals" in _PROMPT


def test_the_joint_branding_is_mapped() -> None:
    """Both forms carry the Freddie number beside the Fannie one. A model reading "Freddie Mac Form
    1000" off the header has no way to know it is holding a 1007 unless told."""
    assert "Freddie Mac Form 1000" in _PROMPT and "Freddie Mac Form 72" in _PROMPT


def test_a_null_is_preferred_to_a_plausible_guess() -> None:
    """The whole posture, and the reason the prohibitions are worth their length: a wrong rent is
    invisible in a qualifying ratio, and a null is a question a processor can answer."""
    assert "A plausible guess is worse than a null" in _PROMPT

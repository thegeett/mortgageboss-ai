"""LP-622 — the amount OC-3's finding could not name.

OC-3 told a processor their investment property's rental income was undocumented without ever saying
HOW MUCH, because the figure lives in the MISMO real-estate-owned schedule and a guidance template can
only interpolate a TAG. "$3,000.00 a month is claimed and nothing supports it" is the sentence that
tells a processor what is riding on the document they are being asked to chase.
"""

from __future__ import annotations

import pytest
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.tag_materialization.derived import _RECIPES

_RECIPE = _RECIPES["subject_rental_income_monthly"]


class _Mismo:
    def __init__(self, facts: dict[str, Field], absent: bool = False) -> None:
        self.facts, self.absent = facts, absent


class _Snap:
    def __init__(self, facts: dict[str, Field], absent: bool = False) -> None:
        self.mismo = _Mismo(facts, absent)


def _f(value: str) -> Field:
    return Field(value=value, source=FieldSource.PARSED)


def _run(facts: dict[str, Field], *, absent: bool = False) -> tuple[object, str]:
    return _RECIPE(_Snap(facts, absent), "loan", None)


def test_the_subject_rows_rent_is_what_is_read() -> None:
    """A borrower with three rentals has three rows and only ONE is this loan's. `is_subject` picks it;
    taking the first row would report another property's rent in a finding about this one."""
    value, reason = _run(
        {
            "owned_property.1.is_subject": _f("False"),
            "owned_property.1.rental_income_net": _f("9999.00"),
            "owned_property.2.is_subject": _f("True"),
            "owned_property.2.rental_income_net": _f("1250.50"),
        }
    )

    assert (value, reason) == ("1250.50", "")


def test_gross_is_preferred_over_net() -> None:
    """Fannie qualifies on 75% OF GROSS (IN-14's cited primary), so the two are not interchangeable —
    running a net figure through the factor would apply the vacancy haircut to an already-hair-cut
    number."""
    value, _ = _run(
        {
            "owned_property.1.is_subject": _f("True"),
            "owned_property.1.rental_income_gross": _f("3600.00"),
            "owned_property.1.rental_income_net": _f("3000.00"),
        }
    )

    assert value == "3600.00"


def test_net_is_used_when_no_gross_is_stated() -> None:
    """LF-ABRS's actual shape: `rental_income_net` 3000.00 with gross NULL. Reporting nothing would lose
    the only figure the file has, and it is the one the application is asking to be believed."""
    value, reason = _run(
        {
            "owned_property.1.is_subject": _f("True"),
            "owned_property.1.rental_income_net": _f("3000.00"),
        }
    )

    assert (value, reason) == ("3000.00", "")


@pytest.mark.parametrize(
    ("facts", "expected_reason"),
    [
        (
            {"owned_property.1.is_subject": _f("False")},
            "the real-estate-owned schedule names no subject property",
        ),
        (
            {
                "owned_property.1.is_subject": _f("True"),
                "owned_property.2.is_subject": _f("True"),
                "owned_property.1.rental_income_net": _f("3000.00"),
            },
            "2 owned properties are marked as the subject",
        ),
        (
            {"owned_property.1.is_subject": _f("True")},
            "the application states no rental income for the subject property",
        ),
        (
            {
                "owned_property.1.is_subject": _f("True"),
                "owned_property.1.rental_income_net": _f("0"),
            },
            "the application states no rental income for the subject property",
        ),
    ],
    ids=["no-subject-row", "two-subject-rows", "no-rent-stated", "zero-rent"],
)
def test_it_abstains_rather_than_picking(facts: dict[str, Field], expected_reason: str) -> None:
    """ABSTAIN, NEVER GUESS. Every one of these could be resolved by choosing a row or reading 0 as a
    fact, and each would put a number into a finding the file does not state. Zero rent in particular is
    the fail-closed case the housing inputs already settled (LP-375): absent is not $0."""
    value, reason = _run(facts)

    assert value == "unknown"
    assert reason == expected_reason


def test_an_absent_mismo_section_abstains() -> None:
    """`MismoSection.absent` is set on ANY exception building the section, so this is a degraded run, not
    a file without rentals — LP-495b's lesson, where an empty context was read as an answer."""
    value, reason = _run({}, absent=True)

    assert (value, reason) == ("unknown", "the file carries no MISMO section")


# --------------------------------------------------------------------------------------------- #
# LP-622 — the template has to hold whichever way the tag lands
# --------------------------------------------------------------------------------------------- #
def _oc3_message(support: str, verdict: str, amount: str | None) -> str:
    from app.verification.rule_engine.judgment import _compose
    from app.verification.rules.specs import load_rule_spec
    from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage

    def _tag(value: str) -> Tag:
        return Tag(
            value=value,
            confidence=0.85,
            produced_by=TagProducedBy.AI,
            tag_role=TagRole.STRUCTURAL_FACT,
            stage=TagStage.B,
        )

    judgment = load_rule_spec("OC-3").judgment
    assert judgment is not None and judgment.guidance is not None
    tags = {"occupancy.rental_support": _tag(support), "occupancy.stated": _tag("investment")}
    if amount is not None:
        tags["property.subject_rental_income_monthly"] = _tag(amount)
    message, _fix = _compose(judgment.guidance, verdict, tags, judgment.reasoned_over, None, None)
    return message


def test_the_amount_is_stated_as_money_not_as_a_raw_value() -> None:
    """The whole point of the tag. "3000.00" in a sentence asking a processor to go and document it is
    not the same as "$3,000.00" — `_guidance_fields` money-formats only the tags declared in
    `_MONEY_TAGS`, and this is what holds that declaration."""
    message = _oc3_message("inadequate", "no", "3000.00")

    assert "$3,000.00 in monthly rent" in message
    assert "3000.00 in monthly" not in message


@pytest.mark.parametrize("amount", ["unknown", None], ids=["tag-unknown", "tag-absent"])
@pytest.mark.parametrize(
    ("support", "verdict"),
    [("inadequate", "no"), ("unknown", "unknown"), ("adequate", "yes")],
)
def test_oc3_reads_correctly_however_the_amount_lands(
    support: str, verdict: str, amount: str | None
) -> None:
    """THE BUG THIS PINS, caught in review before it shipped. The generic placeholder loop renders an
    unresolved tag as its raw value or "not established", which is fine on a chip and wrong inside prose:
    every one of these six combinations read "The application claims unknown a month in rent" or
    "...claims not established a month...".

    Reachable, not theoretical — an investment file that states occupancy but no rent, or any file with
    no MISMO real-estate-owned schedule at all. Every case an amount can land in has to produce a
    sentence, which is why this is a matrix and not one example."""
    message = _oc3_message(support, verdict, amount)

    assert "an unstated amount in monthly rent" in message
    for leak in ("unknown in monthly", "not established", "claims unknown"):
        assert leak not in message, f"the raw placeholder {leak!r} reached the sentence"

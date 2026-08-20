"""LP-597 — AS-4's other-financed-properties overlay (B3-4.1-01).

THE BUG. On a borrower carrying five retained first liens totalling $2,190,383, AS-4 returned
`satisfied` with the reasoning "Fannie Mae guidelines require no minimum reserves for a one-unit
principal residence". That sentence is true of the matrix cell and badly wrong about the file: the
same guideline page requires additional reserves of 2% of aggregate UPB at 1-4 financed properties,
4% at 5-6, and 6% at 7-10. Four investment properties at $1,879,121 x 4% is roughly $75,000 of
reserves the file was cleared without.

AS-4's own docstring had said for two tickets that it does not model this, because "neither the
financed-property count nor the aggregate UPB reaches the snapshot". LP-596 put the 1003's
real-estate-owned schedule there, which is what makes this evaluable at all.

WHY needs_review AND NOT fired: the overlay is a DOLLAR requirement and the reserves calculator
reports MONTHS of PITIA. Converting needs the housing payment, which is gated on exactly the files
where taxes and insurance have not yet arrived. So the rule reports that the overlay applies and hands
the comparison to a human, rather than passing a file it has not cleared.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from app.verification.rule_engine.deterministic import evaluate_deterministic_rule
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    CalculationEntry,
    CalculationsSection,
    MismoSection,
    Snapshot,
    TagsSection,
)
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.tag_materialization.derived import (
    _reserves_has_other_financed_properties,
    _reserves_other_financed_aggregate_upb,
    _reserves_other_financed_count,
    _reserves_other_financed_required_amount,
)

_AS4 = load_rule_spec("AS-4")


def _tag(value: str) -> Tag:
    return Tag(
        value=value,
        confidence=None,
        reasoning="fixture",
        source_facts=("raw",),
        produced_by=TagProducedBy.DERIVED,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def _snapshot(
    owned: list[dict[str, str]],
    *,
    loan_tags: dict[str, Tag] | None = None,
    months_available: str = "6",
) -> Snapshot:
    """A snapshot carrying the flat `owned_property.<n>.<field>` keys LP-596 projects."""
    facts: dict[str, Field] = {}
    for index, row in enumerate(owned, start=1):
        for field, value in row.items():
            facts[f"owned_property.{index}.{field}"] = Field.present(
                value, source=FieldSource.PARSED
            )
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 8, 20, tzinfo=UTC),
        mismo=MismoSection.present(facts),
        tags=TagsSection.present({"loan": loan_tags or {}}),
        calculations=CalculationsSection.present(
            reserves=CalculationEntry(value={"months_available": months_available}, gated=False)
        ),
    )


def _row(upb: str, usage: str = "Investment", disposition: str = "Retain") -> dict[str, str]:
    return {
        "is_subject": "False",
        "disposition_status": disposition,
        "lien_upb": upb,
        "current_usage_type": usage,
    }


# The real export, exactly: five retained liens, one of them the borrower's principal residence.
_REAL_FILE = [
    _row("311262.00", usage="PrimaryResidence"),
    _row("582417.00"),
    _row("351804.00"),
    _row("405282.00"),
    _row("539618.00"),
]


def test_the_real_file_no_longer_passes_silently() -> None:
    """THE HEADLINE. Same inputs that produced a green "no minimum reserves are required"."""
    snapshot = _snapshot(
        _REAL_FILE,
        loan_tags={
            "reserves.required_months": _tag("0"),
            "reserves.has_other_financed_properties": _tag("yes"),
        },
    )

    evaluation = evaluate_deterministic_rule(_AS4, snapshot)[0]

    assert evaluation.verdict is Verdict.NEEDS_REVIEW
    assert "retains financed property besides the subject" in evaluation.reasoning


def test_a_genuine_shortfall_still_fires_rather_than_being_intercepted() -> None:
    """Branch ORDER. The overlay branch sits after `fired`, so a file that fails the occupancy matrix
    is still reported as failing it — the overlay must not downgrade a real shortfall to a review."""
    snapshot = _snapshot(
        _REAL_FILE,
        months_available="1",  # against 6 required — a real shortfall
        loan_tags={
            "reserves.required_months": _tag("6"),
            "reserves.has_other_financed_properties": _tag("yes"),
        },
    )

    assert evaluate_deterministic_rule(_AS4, snapshot)[0].verdict is Verdict.FIRED


def test_a_file_with_no_other_financed_property_still_passes() -> None:
    """The overlay must not fire on the ordinary single-property borrower — that would trade a narrow
    false pass for a broad false alarm."""
    snapshot = _snapshot(
        [],
        loan_tags={
            "reserves.required_months": _tag("0"),
            "reserves.has_other_financed_properties": _tag("no"),
        },
    )

    assert evaluate_deterministic_rule(_AS4, snapshot)[0].verdict is Verdict.SATISFIED


def test_an_absent_overlay_tag_leaves_as4_exactly_where_it_was() -> None:
    """CONTAINMENT, and the reason the overlay tags are neither operands nor load-bearing.

    `deterministic.py` couldnt_checks on ANY unresolvable declared operand, whichever outcome would
    have matched — so declaring them would mean one REO property missing a lien balance takes out
    AS-4's occupancy check too. An absent guard tag must simply not match.
    """
    snapshot = _snapshot([], loan_tags={"reserves.required_months": _tag("0")})

    assert evaluate_deterministic_rule(_AS4, snapshot)[0].verdict is Verdict.SATISFIED


# --------------------------------------------------------------------------- #
# The producers — the arithmetic, against the real file's numbers
# --------------------------------------------------------------------------- #


def test_the_aggregate_excludes_the_principal_residence() -> None:
    """B3-4.1-01: "the aggregate UPB calculation does not include the mortgages ... on the subject
    property, the borrower's principal residence, properties that are sold or pending sale". So the
    borrower's own home counts toward the TIER and is excluded from the BALANCE — the one asymmetry
    in this rule most likely to be got wrong."""
    snapshot = _snapshot(_REAL_FILE)

    value, reason = _reserves_other_financed_aggregate_upb(snapshot, "loan", None)

    # 582,417 + 351,804 + 405,282 + 539,618 — the 311,262 principal residence is out.
    assert Decimal(str(value)) == Decimal("1879121.00")
    assert "excluding 1 principal residence" in reason


def test_the_tier_counts_the_subject_property() -> None:
    """B2-2-03 counts the subject among the borrower's financed properties, and B3-4.1-01's "five to
    six" boundary is read against that count. Five other properties is SIX financed — the 4% tier, not
    2%. Getting this off by one halves the requirement."""
    snapshot = _snapshot(_REAL_FILE)

    assert _reserves_other_financed_count(snapshot, "loan", None)[0] == "6"


def test_the_required_amount_on_the_real_file() -> None:
    """The number a processor would act on: 4% of $1,879,121."""
    snapshot = _snapshot(_REAL_FILE)

    value, reason = _reserves_other_financed_required_amount(snapshot, "loan", None)

    assert Decimal(str(value)) == Decimal("75164.84")
    assert "4% of" in reason


def test_properties_being_sold_are_excluded_entirely() -> None:
    """The guide excludes anything "sold or pending sale" — that lien does not survive closing."""
    snapshot = _snapshot([_row("400000.00", disposition="Sell"), _row("100000.00")])

    assert _reserves_other_financed_count(snapshot, "loan", None)[0] == "2"  # 1 retained + subject
    assert Decimal(str(_reserves_other_financed_aggregate_upb(snapshot, "loan", None)[0])) == (
        Decimal("100000.00")
    )


def test_a_property_marked_subject_is_not_an_other_financed_property() -> None:
    """Only a TRUE marks the subject (LP-596): the real export writes false on every block."""
    row = _row("400000.00")
    row["is_subject"] = "True"
    snapshot = _snapshot([row, _row("100000.00")])

    assert _reserves_other_financed_count(snapshot, "loan", None)[0] == "2"


def test_a_free_and_clear_property_is_owned_but_not_financed() -> None:
    """No lien means no unpaid balance to reserve against, and it must not inflate the tier."""
    snapshot = _snapshot([_row("0"), _row("100000.00")])

    assert _reserves_other_financed_count(snapshot, "loan", None)[0] == "2"


def test_an_absent_schedule_reads_no_rather_than_unknown() -> None:
    """Deliberate, and the weakest link in this rule — recorded rather than hidden. Abstaining on an
    absent REO section would turn AS-4 into a couldnt_check on essentially every file that has none,
    trading a narrow false pass for a broad abstention. The overlay can only ADD a review, so a wrong
    "no" leaves AS-4 exactly where it was before this ticket."""
    snapshot = _snapshot([])

    assert _reserves_has_other_financed_properties(snapshot, "loan", None)[0] == "no"


def test_above_ten_financed_properties_abstains_rather_than_guessing() -> None:
    """B3-4.1-01 tiers stop at ten (and B2-2-03 caps deliverability there). There is no percentage to
    apply, so this is an eligibility question, not a reserves figure to extrapolate."""
    snapshot = _snapshot([_row("100000.00") for _ in range(11)])

    value, reason = _reserves_other_financed_required_amount(snapshot, "loan", None)

    assert value == "unknown"
    assert "outside the 1-10 tiers" in reason


# --------------------------------------------------------------------------- #
# LP-600 — the schedule must say which property this loan is against
# --------------------------------------------------------------------------- #


def test_a_schedule_that_never_marks_a_subject_abstains_rather_than_counting_the_subject() -> None:
    """THE FALSE POSITIVE THIS CLOSES. `_REAL_FILE` is an export that writes `false` on every block.
    Treating "not true" as "another property" made the subject property its own other-financed
    property — pushing AS-4 from satisfied to needs_review on an ordinary refinance and inflating both
    the count and the aggregate.

    §8: unknown, not a guessed "yes" and not a confident "no". `unknown` does not match AS-4's
    `eq "yes"` guard, so the rule lands exactly where it was rather than on a false alarm.
    """
    snapshot = _snapshot(_REAL_FILE)

    value, reason = _reserves_has_other_financed_properties(snapshot, "loan", None)

    assert value == "unknown"
    assert "does not identify which property this loan is against" in reason


def test_a_schedule_that_does_mark_a_subject_is_trusted() -> None:
    """The flag is meaningful on an export that uses it — which the real staging files do."""
    rows = [
        {"is_subject": "True", "disposition_status": "Retain", "lien_upb": "451829.00"},
        _row("582417.00"),
    ]
    snapshot = _snapshot(rows)

    assert _reserves_has_other_financed_properties(snapshot, "loan", None)[0] == "yes"
    # The subject's own row is excluded from both the tier and the balance.
    assert _reserves_other_financed_count(snapshot, "loan", None)[0] == "2"


def test_a_schedule_listing_only_the_subject_reports_no_other_property() -> None:
    """The real staging shape: one row, marked subject. AS-4 must stay satisfied."""
    snapshot = _snapshot(
        [{"is_subject": "True", "disposition_status": "Retain", "lien_upb": "451829.00"}]
    )

    assert _reserves_has_other_financed_properties(snapshot, "loan", None)[0] == "no"


def test_a_retained_property_with_no_stated_lien_balance_still_counts() -> None:
    """LP-600 — it used to be filtered out with free-and-clear property, which made the aggregate's
    own abstention DEAD CODE and let AS-4 assert "the application lists no other retained financed
    property" about data it never saw. Absent and zero are different answers."""
    rows = [
        {"is_subject": "True", "disposition_status": "Retain", "lien_upb": "451829.00"},
        {"is_subject": "False", "disposition_status": "Retain"},  # no lien_upb stated
    ]
    snapshot = _snapshot(rows)

    assert _reserves_has_other_financed_properties(snapshot, "loan", None)[0] == "yes"
    value, reason = _reserves_other_financed_aggregate_upb(snapshot, "loan", None)
    assert value == "unknown"
    assert "states no lien balance" in reason


def test_a_free_and_clear_property_is_still_excluded() -> None:
    """A ZERO balance is a real answer — owned, not financed — and must not become an abstention."""
    rows = [
        {"is_subject": "True", "disposition_status": "Retain", "lien_upb": "451829.00"},
        {"is_subject": "False", "disposition_status": "Retain", "lien_upb": "0"},
    ]

    assert _reserves_has_other_financed_properties(_snapshot(rows), "loan", None)[0] == "no"

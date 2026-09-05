"""LP-621 review — the rental treatment through `build_dti_calculation`, not in isolation.

`test_rental_treatment_lp621.py` exercises `subject_rental_treatment` directly and passes, because the
UNIT is right. What was wrong was the WIRING: the treatment reached the calculator through exactly one
of the three seams it needs.

  * income  — the net figure was added.               (this seam worked)
  * housing — the full subject PITIA STAYED, and `borrower_present_housing` had no caller anywhere in
              `app/`, so the borrower's own cost never replaced it. Both directions of the defect
              LP-621 was written to fix were still present, and the PITIA was now counted TWICE:
              once in housing, once inside the net that was subtracted from income.
  * items   — the line reached `income_lines` but never `income_items`, so the breakdown a processor
              reads no longer summed to the headline, the snapshot's breakdown omitted it entirely,
              and the line could not be overridden.

Three unit-passing, integration-failing defects behind one missing test. So this test exists at the
seam, and asserts the ARITHMETIC rather than the presence of a line.
"""

from __future__ import annotations

from decimal import Decimal

from app.models import Borrower, Company, LoanProgram, StatedIncomeItem
from app.models.property import OccupancyType, Property
from app.models.stated_financials import StatedHousingExpense, StatedOwnedProperty
from app.services.dti import HOUSING_PRESENT, RENTAL_NET, build_dti_calculation
from app.services.loan_files import create_loan_file
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration import factories
from tests.services.test_dti import _seed_housing


async def _investment_file(
    db: AsyncSession,
    slug: str,
    *,
    gross_rent: str | None = "8000",
    present_housing: str | None = "2500",
    occupancy: OccupancyType | None = OccupancyType.INVESTMENT,
    properties: int = 1,
):
    """$24,333.33 of other income; P&I 277.78 + 300 taxes + 100 insurance = $677.78 subject PITIA."""
    company = Company(name=slug.title(), slug=slug)
    db.add(company)
    await db.flush()
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    loan_file.note_amount = Decimal("100000")
    loan_file.note_rate_percent = Decimal("0")
    loan_file.amortization_months = 360
    borrower = Borrower(loan_file_id=loan_file.id, first_name="Pat", last_name="B", is_primary=True)
    db.add(borrower)
    await db.flush()
    db.add(
        StatedIncomeItem(
            borrower_id=borrower.id,
            monthly_amount=Decimal("24333.33"),
            income_type="Base",
            employment_income=True,
        )
    )
    for _ in range(properties):
        prop = Property(loan_file_id=loan_file.id, address_line="1 Rental Way", city="Springfield")
        prop.occupancy_type = occupancy
        db.add(prop)
    if gross_rent is not None:
        db.add(
            StatedOwnedProperty(
                loan_file_id=loan_file.id,
                is_subject=True,
                rental_income_gross=Decimal(gross_rent),
            )
        )
    if present_housing is not None:
        db.add(
            StatedHousingExpense(
                loan_file_id=loan_file.id,
                expense_type="Rent",
                timing="Present",
                payment_amount=Decimal(present_housing),
            )
        )
    await db.flush()
    await _seed_housing(db, loan_file)
    return loan_file


async def test_the_borrowers_own_housing_replaces_the_subject_pitia(db_session) -> None:
    """THE DOUBLE COUNT. The net already has the PITIA subtracted from it; leaving the same PITIA in
    housing charges the borrower for it twice, on a property they do not occupy.

    Subject PITIA $677.78. 75% of $8,000 gross rent is $6,000, so the net is +$5,322.22 to income.
    Housing must become the borrower's OWN $2,500 — not $677.78, and not $3,177.78.
    """
    loan_file = await _investment_file(db_session, "double-count")

    calc = await build_dti_calculation(db_session, loan_file=loan_file)

    assert calc.housing_payment == Decimal("2500.00")
    # bug-012 — the $5,322.22 net NO LONGER reaches income. SEL-2026-08 conditions that on 12 months
    # of property-management experience, which no file can establish yet, so the rent may only offset
    # the subject's PITIA — and that offset is the exclusion this test is about. The housing
    # substitution, which is what LP-621 wrote this for, is unchanged.
    assert calc.gross_monthly_income == Decimal("24333.33")
    assert calc.front_end_dti == Decimal("10.27")  # 2,500 / 24,333.33


async def test_the_subject_pitia_lines_are_shown_excluded_not_dropped(db_session) -> None:
    """A housing line that silently vanishes is worse than one counted wrongly — the LP-568 principle,
    which applies here for the same reason: the processor must see the PITIA was considered, and why
    it is not in the total."""
    loan_file = await _investment_file(db_session, "excluded-lines")

    calc = await build_dti_calculation(db_session, loan_file=loan_file)

    subject_lines = [i for i in calc.housing_items if i.key != HOUSING_PRESENT]
    assert subject_lines, "the subject's PITIA components are still rendered"
    assert all(i.excluded for i in subject_lines)
    assert all("does not occupy" in (i.excluded_reason or "") for i in subject_lines)
    # And the borrower's own cost is a line in its own right, with a source a reader can judge.
    present = next(i for i in calc.housing_items if i.key == HOUSING_PRESENT)
    assert present.amount == Decimal("2500.00")


async def test_the_rental_line_is_in_the_breakdown_and_sums_to_the_headline(db_session) -> None:
    """The transparency guarantee the module docstring calls "the feature": the itemized lines a
    processor reads must add up to the number beside them.

    bug-012 — AND AN EXCLUDED LINE IS PART OF THAT GUARANTEE, not an exception to it. The positive
    net is shown with its arithmetic and marked excluded, so the visible lines still reconcile with
    the headline; a figure this large that simply disappeared could not be argued with.
    """
    loan_file = await _investment_file(db_session, "breakdown")

    calc = await build_dti_calculation(db_session, loan_file=loan_file)

    rental = next(i for i in calc.income_items if i.key == RENTAL_NET)
    assert rental.amount == Decimal("5322.22"), (
        "the arithmetic is unchanged — its TREATMENT changed"
    )
    # The arithmetic behind it travels WITH it (LP-621 promised this and computed it into a local).
    assert "75% of $8,000.00" in (rental.derivation or "")
    assert rental.excluded and "SEL-2026-08" in (rental.excluded_reason or "")
    assert (
        sum(i.amount for i in calc.income_items if not i.excluded) == calc.gross_monthly_income
    ), "what is COUNTED still sums to the headline"


async def test_an_override_corrects_the_figure_but_cannot_restore_it_to_income(db_session) -> None:
    """bug-012 — THE OVERRIDE STILL WORKS, AND IT NO LONGER RE-INCLUDES.

    `_to_items` treats an override as DISPUTING an exclusion and re-includes the line (LP-569), which
    is right where the exclusion is a claim about the file a processor can correct. The SEL-2026-08
    restriction is not that kind of claim: an override changes an AMOUNT, and no amount establishes 12
    months of property-management experience. So the exclusion is applied structurally, after
    `_to_items` — the same treatment the occupancy exclusion gets, for the same reason. Without it a
    processor correcting the rent would silently put the figure back into qualifying income.

    A processor who HAS verified the experience needs a way to say so. That is bug-012 step 2, and it
    is a different assertion from correcting a number.
    """
    from app.schemas.dti import DtiOverrideInput
    from app.services.dti import set_dti_override

    loan_file = await _investment_file(db_session, "overridable")
    company = await db_session.get(Company, loan_file.company_id)
    assert company is not None
    user = await factories.make_user(db_session, company=company)

    calc = await set_dti_override(
        db_session,
        loan_file=loan_file,
        field_key=RENTAL_NET,
        data=DtiOverrideInput(amount=Decimal("4000.00")),
        actor_user_id=user.id,
    )

    rental = next(i for i in calc.income_items if i.key == RENTAL_NET)
    assert rental.overridden and rental.amount == Decimal("4000.00"), "the correction is honoured"
    assert rental.excluded, "and it still cannot reach qualifying income"
    assert calc.gross_monthly_income == Decimal("24333.33"), "the override did not re-include it"


async def test_a_shortfall_becomes_an_obligation_and_still_replaces_housing(db_session) -> None:
    """The negative branch. 75% of $400 is $300 against a $677.78 PITIA — a $377.78 shortfall, carried
    as a debt. The housing substitution is unchanged: it does not depend on the sign."""
    loan_file = await _investment_file(db_session, "shortfall", gross_rent="400")

    calc = await build_dti_calculation(db_session, loan_file=loan_file)

    shortfall = next(i for i in calc.debt_items if i.key == RENTAL_NET)
    assert shortfall.amount == Decimal("377.78")
    assert calc.housing_payment == Decimal("2500.00")
    assert calc.monthly_debts == Decimal("377.78")


async def test_a_gated_treatment_leaves_the_housing_side_alone(db_session) -> None:
    """A gate is not a treatment. With no gross rent stated there is no net to add and no basis for
    substituting housing, so the calculator must not half-apply it — it gates and leaves the subject's
    PITIA where it was."""
    loan_file = await _investment_file(db_session, "gated", gross_rent=None)

    calc = await build_dti_calculation(db_session, loan_file=loan_file)

    assert calc.gated and "Form 1007" in (calc.gate_reason or "")
    assert calc.housing_payment == Decimal("677.78")
    assert not any(i.key == RENTAL_NET for i in (*calc.income_items, *calc.debt_items))


async def test_the_gate_reaches_the_snapshot_the_rules_read(db_session) -> None:
    """`map_dti` re-derives its own gate from the breakdown lines and knew nothing about `dti.gated`.

    That check looks for a REQUIRED tag that is absent or unknown, and LP-621's gate is not that shape
    — the taxes and insurance are both present; what is missing is the basis for the method the loan
    actually needs. So the /dti card gated while the snapshot went on publishing a confident ratio to
    the calibrated rules, which is the only consumer that acts on it automatically.
    """
    from app.verification.snapshot.calculations_section import map_dti

    loan_file = await _investment_file(db_session, "snapshot-gate", gross_rent=None)
    calc = await build_dti_calculation(db_session, loan_file=loan_file)

    entry = map_dti(calc)

    assert entry is not None
    assert entry.gated, "the rules must not receive a ratio the calculator gated"
    assert "Form 1007" in (entry.gate_reason or "")
    assert entry.value["back_end_dti"] is None


async def test_an_unstated_occupancy_gates_rather_than_reverting(db_session) -> None:
    """`_subject_occupancy` returning None meant "not an investment subject", so a file whose occupancy
    is simply unstated silently got the pre-LP-621 treatment with nothing on screen to say a judgement
    had been skipped.

    The review also named "two property rows" as a case. It is not one: `uq_properties_loan_file_id` is
    a plain UNIQUE on `loan_file_id`, so a second row cannot be inserted (this test tried, and got the
    IntegrityError). That branch is kept in the code as a guard against the constraint being relaxed,
    and is deliberately not tested — an unreachable path with a passing test reads as a covered one.
    """
    loan_file = await _investment_file(db_session, "unstated", occupancy=None)

    calc = await build_dti_calculation(db_session, loan_file=loan_file)

    assert calc.gated, "an unstated occupancy is a gate, not a silent fallback"
    assert "occupancy is not stated" in (calc.gate_reason or "")


async def test_a_file_with_no_property_row_is_simply_not_applicable(db_session) -> None:
    """The one case where the old bare `None` was right, so it must survive the change: no subject
    property means there is nothing to apply a rental treatment to — not a gap in the file."""
    loan_file = await _investment_file(db_session, "no-property", properties=0)

    calc = await build_dti_calculation(db_session, loan_file=loan_file)

    assert not calc.gated
    assert calc.housing_payment == Decimal("677.78")


async def test_a_primary_residence_is_untouched(db_session) -> None:
    """The treatment applies to an investment subject only. A borrower who lives in the subject has
    its PITIA as their housing expense, which is what the calculator already did."""
    loan_file = await _investment_file(
        db_session, "primary", occupancy=OccupancyType.PRIMARY_RESIDENCE
    )

    calc = await build_dti_calculation(db_session, loan_file=loan_file)

    assert calc.housing_payment == Decimal("677.78")
    assert not calc.gated
    assert not any(i.key == HOUSING_PRESENT for i in calc.housing_items)


# --------------------------------------------------------------------------- #
# bug-012 — SEL-2026-08: positive rental income needs 12 months of experience
# --------------------------------------------------------------------------- #


async def test_a_positive_net_does_not_inflate_qualifying_income(db_session) -> None:
    """THE DEFECT, IN THE DIRECTION THAT MATTERS. Before this, a positive net went straight into
    qualifying income for every borrower:

        positive = rental.net_monthly > 0
        if positive:
            income_items = [*income_items, *rental_items]

    SEL-2026-08 (02 September 2026) permits that only where the borrower has 12 months of
    property-management experience; without it the rent may only OFFSET the subject's PITIA. So a
    first-time landlord had their income inflated and their DTI understated — we over-qualified,
    which is the one direction this codebase refuses everywhere else.
    """
    loan_file = await _investment_file(db_session, "no-experience")

    calc = await build_dti_calculation(db_session, loan_file=loan_file)

    rental = next(i for i in calc.income_items if i.key == RENTAL_NET)
    assert rental.amount == Decimal("5322.22"), "computed, and shown"
    assert rental.excluded, "but not counted"
    assert calc.gross_monthly_income == Decimal("24333.33"), "income is the stated income alone"


async def test_the_offset_is_real_even_though_the_income_line_is_not(db_session) -> None:
    """ "Offset the PITIA" is not a thing this code does separately — it is what the housing exclusion
    ALREADY achieves. The subject's PITIA is out of the housing total whether or not the net reaches
    income, so a capped positive net still gets the borrower the full benefit the guide allows. This
    pins that the cap did not silently take the offset away with it."""
    loan_file = await _investment_file(db_session, "offset-still-applies")

    calc = await build_dti_calculation(db_session, loan_file=loan_file)

    subject_lines = [i for i in calc.housing_items if i.key != HOUSING_PRESENT]
    assert subject_lines and all(i.excluded for i in subject_lines), "the PITIA is still offset"
    assert calc.housing_payment == Decimal("2500.00"), "housing is the borrower's OWN cost"


async def test_a_shortfall_is_untouched_by_the_experience_rule(db_session) -> None:
    """The restriction is on ADDING income. A shortfall is an obligation under both regimes, and
    capping it would understate the ratio — the same over-qualifying direction, arrived at from the
    other side."""
    loan_file = await _investment_file(db_session, "shortfall-unaffected", gross_rent="400.00")

    calc = await build_dti_calculation(db_session, loan_file=loan_file)

    shortfall = next(i for i in calc.debt_items if i.key == RENTAL_NET)
    assert not shortfall.excluded, "an obligation is still counted"
    assert shortfall.amount > 0


async def test_the_derivation_says_which_treatment_was_applied(db_session) -> None:
    """A capped figure and a genuinely small one look identical on the line. The derivation is the
    only thing that tells a processor which they are reading, and it must name the rule rather than
    assert a fact about the borrower — we did not establish that they LACK experience, only that the
    file does not establish they have it."""
    loan_file = await _investment_file(db_session, "derivation-says-why")

    calc = await build_dti_calculation(db_session, loan_file=loan_file)

    rental = next(i for i in calc.income_items if i.key == RENTAL_NET)
    derivation = rental.derivation or ""
    assert "not established" in derivation, "not established — never 'the borrower has none'"
    assert "SEL-2026-08" in derivation
    assert "offsets the subject's PITIA" in derivation


# --------------------------------------------------------------------------- #
# bug-012 review — the exclusion reason a processor reads
# --------------------------------------------------------------------------- #
def test_the_rental_exclusion_reason_does_not_point_anywhere() -> None:
    """A DIRECTION WORD IN THIS SENTENCE IS A CLAIM ABOUT THE SCREEN, and the screen disagreed.

    An earlier draft ended "— and that offset is the PITIA exclusion above". True of `dti.py`, where
    the housing exclusion is a few lines up. False where it is read: `dti-calculator.tsx` renders
    "Gross monthly income" FIRST and "Housing payment" SECOND, so an exclusion reason sitting on an
    income line and pointing "above" sends a processor away from the thing it describes.

    Pinned as a property rather than a wording check. The reason has to name what it means, because
    this file cannot know where the frontend will put either section — and the next person to reorder
    those two sections should not silently falsify a sentence in the backend.
    """
    import inspect

    from app.services import dti

    source = inspect.getsource(dti)
    start = source.index("not added to qualifying income: 12 months")
    reason = source[start : start + 600]
    for direction in (" above", " below", " to the right", " to the left"):
        assert direction not in reason.split('")')[0], (
            f"the rental exclusion reason says{direction!r}, which is a claim about layout that this "
            "module cannot make"
        )
    assert "housing payment" in reason, "it should name the section it means instead"


# --------------------------------------------------------------------------- #
# bug-012 step 2 — experience established from Schedule E's Fair Rental Days
# --------------------------------------------------------------------------- #


async def _tax_return_with(db_session, loan_file, *, days, tax_year=2025):
    """A current tax-return extraction whose Schedule E reports `days` fair rental days."""
    from app.models.document import DocumentStatus

    company = await db_session.get(Company, loan_file.company_id)
    assert company is not None
    document = await factories.make_document(
        db_session,
        loan_file=loan_file,
        company=company,
        document_type="tax_return",
        status=DocumentStatus.COMPLETED,
    )
    await factories.make_extraction(
        db_session,
        document=document,
        data={
            "tax_year": {"value": tax_year},
            "schedule_e": {
                "properties": [
                    {
                        "address": {"value": "9 Rental Way"},
                        "rents_received": {"value": "24000"},
                        "fair_rental_days": {"value": days},
                    }
                ]
            },
        },
    )
    await db_session.flush()


async def test_a_full_year_of_fair_rental_days_puts_the_rental_into_income(db_session) -> None:
    """THE POINT OF STEP 2. Step 1 capped EVERY positive net out of income, because nothing could
    establish experience for anyone — safe, but a blanket under-qualification of a whole loan
    category, and 12 months of landlord experience is common rather than exceptional.

    Fannie B3-3.8-01: a borrower whose most recent Schedule E shows Fair Rental Days of 365 HAS the
    experience, and their positive rental income is qualifying income again.
    """
    loan_file = await _investment_file(db_session, "experienced")
    await _tax_return_with(db_session, loan_file, days=365)

    calc = await build_dti_calculation(db_session, loan_file=loan_file)

    rental = next(i for i in calc.income_items if i.key == RENTAL_NET)
    assert not rental.excluded, "365 fair rental days establishes the 12 months"
    assert calc.gross_monthly_income == Decimal("29655.55"), "24,333.33 + the 5,322.22 net"


async def test_a_partial_year_leaves_the_rental_out_of_income(db_session) -> None:
    """The negative control the test above needs. A property rented for part of the year does not
    establish 12 months, so the offset-only treatment stands — and this is what proves the test
    above is measuring the days rather than the presence of a return."""
    loan_file = await _investment_file(db_session, "partial-year")
    await _tax_return_with(db_session, loan_file, days=200)

    calc = await build_dti_calculation(db_session, loan_file=loan_file)

    rental = next(i for i in calc.income_items if i.key == RENTAL_NET)
    assert rental.excluded and "not established" in (rental.excluded_reason or "")
    assert calc.gross_monthly_income == Decimal("24333.33")


async def test_a_leap_year_366_still_counts(db_session) -> None:
    """`>= 365`, not `== 365`. A property rented through a leap year reports 366, and an equality
    test would read that as failing the bar it exceeds. The guide states the number, not the
    comparison."""
    loan_file = await _investment_file(db_session, "leap-year")
    await _tax_return_with(db_session, loan_file, days=366, tax_year=2024)

    calc = await build_dti_calculation(db_session, loan_file=loan_file)

    assert not next(i for i in calc.income_items if i.key == RENTAL_NET).excluded


async def test_the_MOST_RECENT_return_decides_not_the_last_uploaded(db_session) -> None:
    """The guide says the MOST RECENT return. A borrower who uploads an older return afterwards has
    not made it their most recent one, so the check keys on the TAX YEAR rather than upload order —
    otherwise a 2024 return uploaded today would override the 2025 one that supersedes it."""
    loan_file = await _investment_file(db_session, "upload-order")
    await _tax_return_with(db_session, loan_file, days=200, tax_year=2025)  # the current picture
    await _tax_return_with(db_session, loan_file, days=365, tax_year=2023)  # uploaded LATER, older

    calc = await build_dti_calculation(db_session, loan_file=loan_file)

    rental = next(i for i in calc.income_items if i.key == RENTAL_NET)
    assert rental.excluded, "2025 is the most recent return and it shows a partial year"


async def test_no_tax_return_is_not_established_rather_than_denied(db_session) -> None:
    """A file with no return cannot answer the question, and the treatment is the same as a failed
    test — but the WORDING is not, because we did not determine that the borrower lacks experience.
    That distinction is what lets a processor tell a missing document from a real shortfall."""
    loan_file = await _investment_file(db_session, "no-return")

    calc = await build_dti_calculation(db_session, loan_file=loan_file)

    rental = next(i for i in calc.income_items if i.key == RENTAL_NET)
    assert rental.excluded
    assert "not established" in (rental.derivation or "")


async def test_a_return_whose_year_cannot_be_read_is_not_superseded_by_an_older_one(
    db_session,
) -> None:
    """bug-012 step 2 review — the undateable return sorts NEWEST, and the first version had it
    backwards.

    Keying "most recent" on the tax year is right: a 2023 return uploaded today has not become the
    borrower's current picture. But an unparseable year was ranked -1, which does not mean "unknown",
    it means OLDEST — so the newest return lost to every dateable return behind it. Measured on this
    exact fixture, that returned experience ESTABLISHED from a stale 2023 return showing a full year,
    while the borrower's own most recent return showed 200 days.

    That is the OVER-qualifying direction. Every other unbuilt route in this check under-qualifies on
    purpose, which is safe and visible; this one silently qualified a file its own newest document
    contradicts, which is neither.

    Both directions asserted, because the first version passed the second half.
    """
    from app.services.rental_treatment import _management_experience_established

    company = await factories.make_company(db_session, slug="undateable")
    loan_file = await factories.make_loan_file(db_session, company=company)
    await _tax_return_with(db_session, loan_file, days=365, tax_year=2023)
    # Uploaded after, and the year will not parse — the current picture, undateable.
    await _tax_return_with(db_session, loan_file, days=200, tax_year="20?5")

    assert not await _management_experience_established(db_session, loan_file.id), (
        "an undateable newest return was superseded by an older one, and the file qualified on a "
        "picture its own most recent return contradicts"
    )

    # THE OTHER DIRECTION: sorting it newest must not turn into ignoring it. An undateable return
    # that DOES show a full year still establishes experience on its own evidence.
    company2 = await factories.make_company(db_session, slug="undateable-ok")
    loan_file2 = await factories.make_loan_file(db_session, company=company2)
    await _tax_return_with(db_session, loan_file2, days=200, tax_year=2023)
    await _tax_return_with(db_session, loan_file2, days=365, tax_year="20?5")

    assert await _management_experience_established(db_session, loan_file2.id), (
        "an undateable return showing a full rented year established nothing — sorting it newest "
        "must consult it, not skip it"
    )

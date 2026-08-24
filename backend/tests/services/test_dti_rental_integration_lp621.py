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
    assert calc.gross_monthly_income == Decimal("29655.55")  # 24,333.33 + 5,322.22
    # Front-end = 2,500 / 29,655.55. With the subject PITIA left in it read 677.78/29,655.55.
    assert calc.front_end_dti == Decimal("8.43")


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
    processor reads must add up to the number beside them."""
    loan_file = await _investment_file(db_session, "breakdown")

    calc = await build_dti_calculation(db_session, loan_file=loan_file)

    rental = next(i for i in calc.income_items if i.key == RENTAL_NET)
    assert rental.amount == Decimal("5322.22")
    # The arithmetic behind it travels WITH it (LP-621 promised this and computed it into a local).
    assert "75% of $8,000.00" in (rental.derivation or "")
    assert sum(i.amount for i in calc.income_items) == calc.gross_monthly_income


async def test_the_rental_line_can_be_overridden(db_session) -> None:
    """A figure this large that a processor cannot correct is worse than no figure. It routes through
    the same `_to_items` override path as every other line, so it gets this for free — which is the
    argument for putting it there rather than appending a bare engine line."""
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
    assert rental.overridden and rental.amount == Decimal("4000.00")
    assert calc.gross_monthly_income == Decimal("28333.33")  # 24,333.33 + 4,000


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

    assert calc.gated and "GROSS monthly rent" in (calc.gate_reason or "")
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
    assert "GROSS monthly rent" in (entry.gate_reason or "")
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

"""LP-621 — Fannie's rental treatment for a subject investment property.

`services/dti.py` never mentioned rental income. Income came only from `StatedIncomeItem`; the housing
payment was the subject's PITI regardless of who lives there. On LF-ABRS — a rate-and-term refinance of
a $650,000 investment property the borrower does not occupy, stating $3,000/month of rent — that is
wrong in BOTH directions:

  * TOO HIGH: the full $5,067.13 PITI in the numerator, no credit for rent tenants pay.
  * TOO LOW:  the borrower lives somewhere and that cost is nowhere in the file.

The ratio read 44.8% against a 45% limit, computed by a method that does not apply to the loan.
"""

from __future__ import annotations

from decimal import Decimal

from app.models.property import OccupancyType
from app.models.stated_financials import StatedHousingExpense, StatedOwnedProperty
from app.services.rental_treatment import (
    QUALIFYING_FACTOR,
    borrower_present_housing,
    subject_rental_treatment,
)
from tests.integration import factories


async def _file(db, *, occupancy: OccupancyType | None = OccupancyType.INVESTMENT):
    company = await factories.make_company(db, slug="acme")
    loan_file = await factories.make_loan_file(db, company=company)
    prop = await factories.make_property(db, loan_file=loan_file)
    prop.occupancy_type = occupancy
    await db.flush()
    return loan_file


async def _owned(db, loan_file, *, gross=None, net=None, is_subject=True):
    row = StatedOwnedProperty(
        loan_file_id=loan_file.id,
        is_subject=is_subject,
        rental_income_gross=Decimal(gross) if gross is not None else None,
        rental_income_net=Decimal(net) if net is not None else None,
    )
    db.add(row)
    await db.flush()
    return row


async def _present_housing(db, loan_file, amount, *, expense_type="Rent"):
    db.add(
        StatedHousingExpense(
            loan_file_id=loan_file.id,
            expense_type=expense_type,
            timing="Present",
            payment_amount=Decimal(amount),
        )
    )
    await db.flush()


def test_the_qualifying_factor_is_the_cited_one() -> None:
    """ADR-361 — never invent a threshold. B3-3.8-01, verbatim: "multiplying the gross monthly rent(s)
    by 75%"; the remaining 25% is absorbed by vacancy and ongoing maintenance."""
    assert Decimal("0.75") == QUALIFYING_FACTOR


async def test_a_primary_residence_is_untouched(db_session) -> None:
    """The borrower occupies it, so its PITIA IS their housing expense — which is what the calculator
    already does. This must not reach into an ordinary file."""
    loan_file = await _file(db_session, occupancy=OccupancyType.PRIMARY_RESIDENCE)

    treatment = await subject_rental_treatment(
        db_session, loan_file=loan_file, subject_pitia=Decimal("5067.13")
    )

    assert treatment.applies is False
    assert treatment.gate_reason is None


async def test_a_second_home_is_untouched(db_session) -> None:
    """Also borrower-occupied. Only an INVESTMENT subject changes the shape of the ratio."""
    loan_file = await _file(db_session, occupancy=OccupancyType.SECOND_HOME)

    assert (
        await subject_rental_treatment(
            db_session, loan_file=loan_file, subject_pitia=Decimal("5067.13")
        )
    ).applies is False


async def test_the_full_computation(db_session) -> None:
    """B3-3.1-08: (gross x 75%) - full PITIA. Positive is income."""
    loan_file = await _file(db_session)
    await _owned(db_session, loan_file, gross="8000.00")
    await _present_housing(db_session, loan_file, "2500.00")

    treatment = await subject_rental_treatment(
        db_session, loan_file=loan_file, subject_pitia=Decimal("5067.13")
    )

    # 8000 * 0.75 = 6000.00; 6000.00 - 5067.13 = 932.87
    assert treatment.net_monthly == Decimal("932.87")
    assert treatment.gate_reason is None
    assert "75% of $8,000.00" in (treatment.derivation or "")


async def test_a_shortfall_is_an_obligation_not_a_negative_income(db_session) -> None:
    """When the rent does not cover the payment, the difference is a monthly OBLIGATION — the sign is
    the whole treatment, and dropping it would credit the borrower for a shortfall."""
    loan_file = await _file(db_session)
    await _owned(db_session, loan_file, gross="4000.00")
    await _present_housing(db_session, loan_file, "2500.00")

    treatment = await subject_rental_treatment(
        db_session, loan_file=loan_file, subject_pitia=Decimal("5067.13")
    )

    # 4000 * 0.75 = 3000.00; 3000.00 - 5067.13 = -2067.13
    assert treatment.net_monthly == Decimal("-2067.13")
    assert "carried as a monthly obligation" in (treatment.derivation or "")


async def test_net_rent_is_never_substituted_for_gross(db_session) -> None:
    """LF-ABRS's actual shape: `rental_income_net` $3,000 and NO gross. The factor applies to GROSS, so
    running the net figure through it haircuts an already-haircut number and UNDERSTATES the
    obligation — the direction that ships a bad loan. It gates instead."""
    loan_file = await _file(db_session)
    await _owned(db_session, loan_file, net="3000.00")
    await _present_housing(db_session, loan_file, "2500.00")

    treatment = await subject_rental_treatment(
        db_session, loan_file=loan_file, subject_pitia=Decimal("5067.13")
    )

    assert treatment.net_monthly is None
    # LP-642 — the gate NAMES THE DOCUMENT rather than the empty field. "the application states no
    # GROSS monthly rent" pointed at the 1003, where MISMO never puts the subject's rent.
    reason = treatment.gate_reason or ""
    assert "Form 1007" in reason and "lease" in reason, "it says what to go and get"
    assert "net figure cannot substitute for gross" in reason, "and why a net figure will not do"


async def test_a_missing_own_housing_cost_gates(db_session) -> None:
    """The borrower does not occupy the subject, so their own housing cost belongs on the housing side.
    Absent, the ratio cannot be assembled — and assuming zero understates it."""
    loan_file = await _file(db_session)
    await _owned(db_session, loan_file, gross="8000.00")

    treatment = await subject_rental_treatment(
        db_session, loan_file=loan_file, subject_pitia=Decimal("5067.13")
    )

    assert treatment.net_monthly is None
    assert "OWN monthly housing cost" in (treatment.gate_reason or "")


async def test_lf_abrs_gates_on_both_counts(db_session) -> None:
    """THE REAL FILE. Neither gross rent nor a present housing cost is stated, so the honest output
    names both — a change from reporting 44.8% by a method that does not apply."""
    loan_file = await _file(db_session)
    await _owned(db_session, loan_file, net="3000.00")

    treatment = await subject_rental_treatment(
        db_session, loan_file=loan_file, subject_pitia=Decimal("5067.13")
    )

    assert treatment.applies is True
    assert treatment.net_monthly is None
    reason = treatment.gate_reason or ""
    assert "Form 1007" in reason and "OWN monthly housing cost" in reason


async def test_no_subject_row_states_no_rent(db_session) -> None:
    """A schedule with no subject row states no rent for the subject; picking another property's rent
    would credit this loan with income from a different one."""
    loan_file = await _file(db_session)
    await _owned(db_session, loan_file, gross="8000.00", is_subject=False)
    await _present_housing(db_session, loan_file, "2500.00")

    assert (
        await subject_rental_treatment(
            db_session, loan_file=loan_file, subject_pitia=Decimal("5067.13")
        )
    ).net_monthly is None


async def test_present_housing_sums_across_types(db_session) -> None:
    """ "Present housing" is the whole cost — a borrower owning their residence states P&I, taxes and
    insurance separately, and only the total is their housing expense."""
    loan_file = await _file(db_session)
    await _present_housing(
        db_session, loan_file, "2000.00", expense_type="FirstMortgagePrincipalAndInterest"
    )
    await _present_housing(db_session, loan_file, "300.00", expense_type="RealEstateTax")

    assert await borrower_present_housing(db_session, loan_file.id) == Decimal("2300.00")


async def test_no_present_expense_is_none_not_zero(db_session) -> None:
    """A borrower with no housing cost is possible — living with family — but that is a FACT someone
    states, not a default. Assuming zero understates every ratio it touches."""
    loan_file = await _file(db_session)

    assert await borrower_present_housing(db_session, loan_file.id) is None

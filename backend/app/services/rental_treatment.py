"""Fannie's rental treatment for a SUBJECT investment property (LP-621).

WHY THIS EXISTS. `services/dti.py` never mentioned rental income. Income came only from
`StatedIncomeItem`; the housing payment was the subject's PITI regardless of who lives there. On an
investment refinance that is wrong in BOTH directions at once:

  * TOO HIGH — the full subject PITI sits in the numerator with no credit for rent that genuinely
    arrives. LF-ABRS charges the borrower $5,067.13 for a property tenants pay for.
  * TOO LOW  — the borrower lives somewhere, and that housing cost appears nowhere in the file.

Fannie B3-3.1-08 / B3-6-06 compute it as ``(gross monthly rent x 75%) - full PITIA``: a positive result
is added to gross monthly income, a negative one is carried as a monthly obligation. The 25% absorbs
vacancy and maintenance. The borrower's OWN housing expense is what belongs on the housing side,
because they do not occupy the subject.

WHAT THIS MODULE DOES, AND DELIBERATELY DOES NOT DO. It computes that treatment when the inputs exist
and GATES when they do not. It does not estimate, annualise a partial figure, or substitute net rent
for gross. On LF-ABRS both inputs are missing, so the honest output is a gate naming them — which is a
change from reporting 44.8% computed by a method that does not apply to the loan.

⚠️ NET IS NOT GROSS. The application states `rental_income_net` of $3,000 and no gross. The 75% factor
applies to GROSS (IN-14's cited primary, verbatim: "multiplying the gross monthly rent(s) by 75%"), so
running the net figure through it would haircut an already-haircut number and understate the obligation
— the failure mode that ships a bad loan. Absent gross gates; it never falls back.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.models.property import OccupancyType, Property
from app.models.stated_financials import StatedHousingExpense, StatedOwnedProperty

_CENTS = Decimal("0.01")

#: Fannie B3-3.8-01, verbatim: "the lender must calculate the rental income by multiplying the gross
#: monthly rent(s) by 75%". The remaining 25% is absorbed by vacancy and ongoing maintenance. Cited
#: rather than chosen — ADR-361 forbids inventing a threshold, and this one has a primary.
QUALIFYING_FACTOR = Decimal("0.75")


@dataclass(frozen=True)
class RentalTreatment:
    """What the subject's rental income does to the ratio, or why it cannot be determined.

    ``net_monthly`` is positive when the rent more than covers the subject's PITIA (an income line) and
    negative when it does not (an obligation). ``gate_reason`` is set INSTEAD, never alongside: a
    treatment is either computable or it is not, and a half-answer beside a reason is how a processor
    ends up trusting a number the file does not support.
    """

    applies: bool
    net_monthly: Decimal | None = None
    gate_reason: str | None = None
    derivation: str | None = None


_NOT_APPLICABLE = RentalTreatment(applies=False)


async def subject_rental_treatment(
    db: AsyncSession, *, loan_file: LoanFile, subject_pitia: Decimal | None
) -> RentalTreatment:
    """Fannie's net-rental figure for the subject, or the reason it cannot be computed.

    Returns ``applies=False`` for anything that is not an investment subject — a primary residence and
    a second home are occupied by the borrower and their PITIA IS the housing expense, which is what
    the calculator already does.
    """
    occupancy = await _subject_occupancy(db, loan_file.id)
    if occupancy is not OccupancyType.INVESTMENT:
        return _NOT_APPLICABLE

    missing: list[str] = []
    gross = await _subject_gross_rent(db, loan_file.id)
    if gross is None or gross <= 0:
        missing.append(
            "the application states no GROSS monthly rent for the subject (a net figure cannot be "
            "run through the 75% vacancy factor)"
        )
    own_housing = await borrower_present_housing(db, loan_file.id)
    if own_housing is None:
        missing.append(
            "the borrower does not occupy the subject and their OWN monthly housing cost is not "
            "stated"
        )
    if subject_pitia is None:
        missing.append("the subject's full PITIA is not established")

    if missing:
        return RentalTreatment(
            applies=True,
            gate_reason=(
                "This is an investment property the borrower does not occupy, so the ratio is not the "
                "subject's payment against their income: " + "; ".join(missing) + "."
            ),
        )

    assert gross is not None and subject_pitia is not None  # guarded above
    qualifying = (gross * QUALIFYING_FACTOR).quantize(_CENTS, rounding=ROUND_HALF_UP)
    net = (qualifying - subject_pitia).quantize(_CENTS, rounding=ROUND_HALF_UP)
    return RentalTreatment(
        applies=True,
        net_monthly=net,
        derivation=(
            f"75% of ${gross:,.2f} gross rent is ${qualifying:,.2f}, less the subject's "
            f"${subject_pitia:,.2f} PITIA — "
            + (
                f"${net:,.2f} added to income."
                if net > 0
                else f"${abs(net):,.2f} carried as a monthly obligation."
            )
        ),
    )


async def _subject_occupancy(db: AsyncSession, loan_file_id: UUID) -> OccupancyType | None:
    """The subject property's stated occupancy.

    More than one property row on a file is a data error, not a choice to make: returning None gates
    rather than picking one, because the whole treatment turns on this answer.
    """
    rows = (
        await db.scalars(
            only_active(select(Property).where(Property.loan_file_id == loan_file_id), Property)
        )
    ).all()
    return rows[0].occupancy_type if len(rows) == 1 else None


async def _subject_gross_rent(db: AsyncSession, loan_file_id: UUID) -> Decimal | None:
    """GROSS monthly rent for the SUBJECT row of the real-estate-owned schedule.

    Gross only. `rental_income_net` is deliberately not consulted — see the module note: the factor
    applies to gross, and substituting net understates the obligation.
    """
    rows = (
        await db.scalars(
            only_active(
                select(StatedOwnedProperty).where(
                    StatedOwnedProperty.loan_file_id == loan_file_id,
                    StatedOwnedProperty.is_subject.is_(True),
                ),
                StatedOwnedProperty,
            )
        )
    ).all()
    if len(rows) != 1:
        return None  # no subject row, or a contradictory schedule — neither states a rent
    return rows[0].rental_income_gross


async def borrower_present_housing(db: AsyncSession, loan_file_id: UUID) -> Decimal | None:
    """What the borrower pays for housing TODAY, from the 1003's PRESENT expenses (LP-627).

    The input a non-occupant borrower's ratio needs and which had nowhere to come from until
    HOUSING_EXPENSES was lifted out of `catch_all`. Summed across types, because "present housing" is
    the whole cost — rent, or a primary residence's own PITI components.

    None when the export states no present expense at all. NOT zero: a borrower with no housing cost is
    possible (living with family) but is a FACT someone must state, not a default to assume, and
    assuming it understates the ratio.
    """
    rows = (
        await db.scalars(
            only_active(
                select(StatedHousingExpense).where(
                    StatedHousingExpense.loan_file_id == loan_file_id,
                    StatedHousingExpense.timing == "Present",
                ),
                StatedHousingExpense,
            )
        )
    ).all()
    amounts = [row.payment_amount for row in rows if row.payment_amount is not None]
    if not amounts:
        return None
    return sum(amounts, Decimal(0)).quantize(_CENTS, rounding=ROUND_HALF_UP)

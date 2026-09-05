"""Fannie's rental treatment for a SUBJECT investment property (LP-621).

WHY THIS EXISTS. `services/dti.py` never mentioned rental income. Income came only from
`StatedIncomeItem`; the housing payment was the subject's PITI regardless of who lives there. On an
investment refinance that is wrong in BOTH directions at once:

  * TOO HIGH — the full subject PITI sits in the numerator with no credit for rent that genuinely
    arrives. LF-ABRS charges the borrower $5,067.13 for a property tenants pay for.
  * TOO LOW  — the borrower lives somewhere, and that housing cost appears nowhere in the file.

Fannie B3-3.8-02 / B3-6-06 compute it as ``(gross monthly rent x 75%) - full PITIA``: the guide calls
the result ADJUSTED NET RENTAL INCOME. A positive result was added to gross monthly income and a
negative one carried as a monthly obligation — bug-012 conditions the positive half on 12 months of
property-management experience. The borrower's OWN housing expense is what belongs on the housing side,
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

#: Fannie Mae Selling Guide **B3-3.8-02**, Rental Income from the Subject Property (page dated
#: 09/02/2026), verbatim: "the lender must multiply monthly gross rent by 75% for the net rental
#: income amount, then subtract the PITIA of the subject property from the net rental income."
#: Cited rather than chosen — ADR-361 forbids inventing a threshold, and this one has a primary.
#:
#: LP-641 — RE-VERIFIED, NOT RENUMBERED. SEL-2026-08 moved this material out of B3-3.8-01 (which now
#: holds general rental-income information) and the wording changed with it, so the quotation above is
#: read from the new topic rather than carried across with the number swapped.
#:
#: TWO THINGS THAT CHANGED, AND ARE NOT SILENTLY CARRIED FORWARD:
#:
#:   * The old page explained the factor — "the remaining 25% … absorbed by vacancy losses and ongoing
#:     maintenance expenses". That sentence could not be located in the restructured topic. The FACTOR
#:     is still cited; the EXPLANATION is no longer claimed as verbatim. Stated as "could not locate"
#:     rather than "the guide dropped it": one read of a page is weaker evidence of absence than of
#:     presence.
#:   * The factor is PATH-SPECIFIC. It applies to a gross rent documented by a lease (and to the gross
#:     a Form 1007 / 1025 supports). It does NOT apply to the Schedule E path, which the guide computes
#:     as a cash-flow analysis — adding back depreciation, interest, HOA dues, taxes and insurance.
#:     `_subject_gross_rent` reads only the MISMO owned-property schedule today, so no Schedule E figure
#:     can reach this constant; LP-642 proposes widening exactly that lookup, and 75% applied to a
#:     Schedule E figure would be wrong arithmetic. Written down before the lookup widens, not after.
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
    #: bug-012 — whether the borrower has the 12 months of property-management experience that
    #: SEL-2026-08 (02 September 2026) makes the condition for ADDING positive rental income to
    #: qualifying income. Without it the guide permits the income only to OFFSET the subject's PITIA:
    #:
    #:   "Lenders may only use positive rental income for qualifying income if the borrower(s) has at
    #:    least 12 months of property management experience. The lender may only use qualifying rental
    #:    income to offset the PITIA when the borrower(s) has no prior property management experience,
    #:    or less than 12 months of experience."
    #:
    #: ALWAYS FALSE TODAY, and false means NOT ESTABLISHED — not "the borrower has none". The four
    #: permitted routes are unreachable: Fair Rental Days is not on `ScheduleEProperty`, Form 8825 has
    #: no extractor, and the lease-supplementing-a-1040 and two-years-of-returns compositions do not
    #: exist. So the honest state for every borrower is "we cannot tell", and the guide's treatment for
    #: a borrower we cannot tell about is the same as for one with no experience: offset only.
    #:
    #: Kept as a field rather than decided at the call site so the wiring is in place for the real
    #: test (bug-012 step 2), and so the derivation can say WHICH treatment was applied.
    experience_established: bool = False
    #: The borrower's OWN monthly housing cost — what belongs on the housing side, because they do not
    #: occupy the subject. Set only alongside `net_monthly`: the caller substitutes the two together or
    #: neither, since adding the net to income while leaving the subject's PITIA in housing counts that
    #: PITIA twice (it is already subtracted inside the net). Returning it here rather than making the
    #: caller re-query is deliberate — this module already fetched it to decide whether to gate, and a
    #: second read is a second chance for the two to disagree.
    present_housing: Decimal | None = None


_NOT_APPLICABLE = RentalTreatment(applies=False)


async def subject_rental_treatment(
    db: AsyncSession, *, loan_file: LoanFile, subject_pitia: Decimal | None
) -> RentalTreatment:
    """Fannie's net-rental figure for the subject, or the reason it cannot be computed.

    Returns ``applies=False`` for anything that is not an investment subject — a primary residence and
    a second home are occupied by the borrower and their PITIA IS the housing expense, which is what
    the calculator already does.
    """
    occupancy, undetermined = await _subject_occupancy(db, loan_file.id)
    if undetermined is not None:
        # GATE, as `_subject_occupancy`'s contract has always said — not `applies=False`. Mapping an
        # undetermined occupancy to not-applicable silently reverted the file to the pre-LP-621
        # treatment: the wrong ratio, with nothing on screen to say a judgement had been skipped. That
        # is the §8 distinction the rule engine is built on, arriving in the calculator: "this is not
        # an investment subject" and "we cannot tell what this subject is" are different answers.
        return RentalTreatment(applies=True, gate_reason=undetermined)
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
    assert own_housing is not None  # guarded above (a missing figure lands in `missing`)
    qualifying = (gross * QUALIFYING_FACTOR).quantize(_CENTS, rounding=ROUND_HALF_UP)
    net = (qualifying - subject_pitia).quantize(_CENTS, rounding=ROUND_HALF_UP)
    # bug-012 — see `experience_established`. No route to establishing it exists yet, so this is the
    # constant the field documents rather than a check that can pass.
    experience_established = False
    if net > 0 and not experience_established:
        outcome = (
            f"${net:,.2f}, which offsets the subject's PITIA but is NOT added to qualifying "
            "income: 12 months of property-management experience is not established on this file "
            "(Fannie Mae SEL-2026-08)."
        )
    elif net > 0:
        outcome = f"${net:,.2f} added to income."
    else:
        outcome = f"${abs(net):,.2f} carried as a monthly obligation."
    return RentalTreatment(
        applies=True,
        net_monthly=net,
        present_housing=own_housing,
        experience_established=experience_established,
        derivation=(
            f"75% of ${gross:,.2f} gross rent is ${qualifying:,.2f}, less the subject's "
            f"${subject_pitia:,.2f} PITIA — " + outcome
        ),
    )


async def _subject_occupancy(
    db: AsyncSession, loan_file_id: UUID
) -> tuple[OccupancyType | None, str | None]:
    """``(occupancy, undetermined_reason)`` — exactly one is ever set.

    THREE OUTCOMES, NOT TWO, and collapsing them is what the previous version did wrong. It returned a
    bare ``None`` for every non-single-row case and the caller read that as "not an investment
    subject", so an ambiguous file quietly got the old, wrong treatment with no gate and no signal:

      * NO property row      -> ``(None, None)``. There is no subject to treat. Genuinely
        not-applicable, and the only case where a bare None was right.
      * ONE row, occupancy NULL -> a reason. The whole treatment turns on this answer and the file
        does not give it. Distinct from "the borrower occupies it", which is what the old return
        collapsed it into.
      * MORE THAN ONE row    -> a reason. UNREACHABLE TODAY: ``uq_properties_loan_file_id`` is a plain
        UNIQUE on ``loan_file_id`` with no ``deleted_at`` predicate, so a file cannot hold two property
        rows even across soft deletes. Kept as a guard against that constraint being relaxed, not as a
        live path — and stated as such so nobody writes a test for it and finds it untriggerable.
    """
    rows = (
        await db.scalars(
            only_active(select(Property).where(Property.loan_file_id == loan_file_id), Property)
        )
    ).all()
    if not rows:
        return None, None
    if len(rows) > 1:
        return None, (
            f"the file carries {len(rows)} property records, so which one is the subject — and "
            "whether the borrower occupies it — cannot be determined"
        )
    occupancy = rows[0].occupancy_type
    if occupancy is None:
        return None, (
            "the subject property's occupancy is not stated, so whether the borrower lives there "
            "cannot be determined"
        )
    return occupancy, None


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

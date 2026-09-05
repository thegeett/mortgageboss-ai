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

from app.models.document import Document
from app.models.extraction import Extraction
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
    #: FALSE MEANS NOT ESTABLISHED — never "the borrower has none". One of the guide's four routes is
    #: implemented (the most recent 1040's Schedule E showing Fair Rental Days of 365); Form 8825 has
    #: no extractor, and the lease-supplementing-a-1040 and two-years-of-returns compositions are not
    #: built. A borrower who qualifies only through those reads as not-established and is treated as
    #: inexperienced — under-qualified, which is the safe direction, and visible because the derivation
    #: says "not established" rather than asserting a fact about them. See
    #: `_management_experience_established` for the routes and why the gap is stated rather than hidden.
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
        # LP-642/LP-643 — NAME THE DOCUMENT TO GET, NOT THE FIELD THAT CAME BACK EMPTY.
        #
        # This read "the application states no GROSS monthly rent for the subject", which sent a
        # processor to the 1003 to look for a number that was never going to be there: MISMO does not
        # repeat the subject in the owned-property schedule, which is the only place this looks. So the
        # sentence described OUR LOOKUP rather than the file's problem, and did it in a warning banner
        # that reads as authoritative.
        #
        # A gate reason is written by whichever code could not proceed, so it naturally describes the
        # lookup that failed. What a processor needs is the document to go and get. Those are different
        # sentences and the second is the useful one.
        missing.append(
            "no document on the file states what the subject will rent for — a comparable rent "
            "schedule (Form 1007 for one unit, Form 1025 for two-to-four) or a lease for the subject "
            "establishes it, and a net figure cannot substitute for gross"
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
    experience_established = await _management_experience_established(db, loan_file.id)
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


#: Fannie B3-3.8-01 (09/02/2026), verbatim: experience is evidenced by "the borrower's most recent
#: signed federal income tax return, including Schedules 1 and E … reflecting rental income received
#: for any property with Fair Rental Days of 365".
#:
#: `>=`, NOT `== 365`. A leap year is 366 days and a property rented throughout it reports 366, which
#: an equality test would read as failing the 365-day bar it exceeds. The guide states the number, not
#: the comparison; taking it as a floor is the reading that does not punish a borrower for the
#: calendar. Anything below it is a shortfall the guide answers with routes we do not implement (see
#: `_management_experience_established`).
_FULL_YEAR_RENTAL_DAYS = 365


async def _management_experience_established(db: AsyncSession, loan_file_id: UUID) -> bool:
    """Has the borrower 12 months of property-management experience? (bug-012)

    THE ONE ROUTE OF FOUR THAT IS BUILDABLE TODAY, and the gap is deliberate rather than hidden. The
    guide accepts any of:

      1. the most recent 1040 with Schedules 1 and E showing Fair Rental Days of 365   <- THIS ONE
      2. a business return with Form 8825                                              -- no extractor
      3. a 12-month lease supplementing a 1040 that shows fewer than 365 days          -- not composed
      4. two years of returns showing the property in service for the full year        -- not composed

    So a borrower who qualifies ONLY through 2-4 reads as not-established and is treated as
    inexperienced: their rental income offsets the PITIA and is not added to income. That
    UNDER-qualifies them, which is the safe direction and a visible one — the derivation says the
    experience is "not established", not that they lack it, so a processor reading the line can tell
    the difference between a borrower who failed the test and one the test could not see.

    ANY PROPERTY, NOT THE SUBJECT AND NOT ONE STILL OWNED. The guide's words are "for any property",
    so the experience attaches to the BORROWER — a rental since sold still counts, which is the
    sensible reading (selling a property does not un-acquire the skill of having managed one) and the
    one the wording supports. Recorded as resting on those two words rather than on an explicit rule
    about disposal, which the guide does not give.

    THE MOST RECENT RETURN, keyed on the TAX YEAR rather than on upload order: a borrower who uploads
    2024 after 2025 has not made 2024 their most recent return. A return whose year cannot be read
    among others makes the ordering undeterminable, so
    the check ABSTAINS rather than guessing — see the block above the ordering for the measurement.

    ONE RETURN, WHICHEVER IS MOST RECENT — so "a rental since sold still counts" holds only while the
    sale post-dates that return. A property sold during the most recent tax year appears there with
    partial days, or not at all, and reads as not-established. That is route 4 (two years of returns),
    which is not composed, so it is the same acknowledged gap rather than a separate defect.
    """
    rows = (
        await db.scalars(
            only_active(
                select(Extraction)
                .join(Document, Extraction.document_id == Document.id)
                .where(
                    Document.loan_file_id == loan_file_id,
                    Document.document_type == "tax_return",
                    Extraction.is_current.is_(True),
                ),
                Document,
            ).order_by(Document.created_at.desc())
        )
    ).all()
    if not rows:
        return False

    # A SENTINEL CANNOT BE RIGHT IN BOTH DIRECTIONS, so this abstains rather than picking one.
    #
    # The first version sorted an undateable return OLDEST (-1). Review measured that it then lost to
    # every dateable return behind it, so a 2023 return showing 365 days could qualify a file whose
    # own newest return shows 200 — over-qualifying, the one direction this check exists to prevent.
    #
    # The proposed fix sorted it NEWEST. That closes the measured case and opens its mirror: an
    # undateable return showing 365 then beats a genuinely newer 2025 return showing 200, and
    # over-qualifies from the other side. Measured, both sentinels, both shapes:
    #
    #     sentinel   undateable=200d, 2025=365d   undateable=365d, 2025=200d
    #     oldest     ESTABLISHED  (wrong)          not established
    #     newest     not established               ESTABLISHED  (wrong)
    #
    # Neither is safe, because both answer a question the FILE does not: which return is most recent.
    # The guide's test is specifically about the most recent return, so where we cannot identify it we
    # cannot run the test — and the honest outcome is the one every other unbuilt route already takes,
    # NOT ESTABLISHED. That under-qualifies, says so in the reason, and is the direction this whole
    # check is built to fail in.
    #
    # A SINGLE undateable return is not this case: it is trivially the most recent, so it is used.

    def _year(extraction: Extraction) -> int | None:
        """The return's tax year, or None when it cannot be read — NOT a sentinel year."""
        node = (extraction.extracted_data or {}).get("tax_year")
        raw = node.get("value") if isinstance(node, dict) else None
        try:
            return int(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None

    if len(rows) > 1 and any(_year(row) is None for row in rows):
        return False  # cannot order them, so cannot identify the return the guide asks about
    most_recent = rows[0] if len(rows) == 1 else max(rows, key=lambda r: _year(r) or 0)
    schedule_e = (most_recent.extracted_data or {}).get("schedule_e")
    if not isinstance(schedule_e, dict):
        return False
    for prop in schedule_e.get("properties") or ():
        if not isinstance(prop, dict):
            continue
        node = prop.get("fair_rental_days")
        raw = node.get("value") if isinstance(node, dict) else None
        try:
            days = int(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue  # unreadable is not zero — it is one property that cannot answer
        if days >= _FULL_YEAR_RENTAL_DAYS:
            return True
    return False


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

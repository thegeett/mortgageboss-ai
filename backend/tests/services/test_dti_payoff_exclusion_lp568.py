"""LP-568 — an obligation that does not survive closing must leave the DTI.

THE DEFECT. `_auto_debt_lines` counted every active liability unconditionally, and `StatedLiability`
had nowhere to say "this one is paid off at closing". On a refinance that charges the same house
twice: once as `housing_payment` (the new PITI) and once as the old mortgage's payment.

Staging, LF-WCHG: income 13,166.67, new PITI 4,418.785, liabilities 3,186.00 (the mortgage this
loan refinances) + 49 + 35 + 25. The engine reported a back-end DTI of 58.59%. The correct figure —
worked by hand with the resident domain expert — is 34.39%. 58.59% fails most conventional
overlays; 34.39% passes comfortably. The bug flips the verdict on the file.

NOT REFINANCE-ONLY. The mechanism is purpose-agnostic, because the underlying question is. A
purchase reaches it through a departing residence being sold, or a debt paid off at closing to
qualify. `test_a_purchase_excludes_a_departing_residence_the_same_way` is that case, and it is why
the flag lives on the liability rather than being derived from `loan_purpose`.
"""

from __future__ import annotations

from decimal import Decimal

from app.models import Borrower, Company, LoanProgram, StatedIncomeItem, StatedLiability
from app.services.dti import build_dti_calculation
from app.services.loan_files import create_loan_file
from sqlalchemy.ext.asyncio import AsyncSession
from tests.services.test_dti import _seed_housing


async def _file_with(db: AsyncSession, slug: str, liabilities: list[StatedLiability]):
    """$10,000 income, $100k @ 0% / 360mo (P&I 277.78) + $400/mo taxes & insurance."""
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
            monthly_amount=Decimal("10000"),
            income_type="Base",
            employment_income=True,
        )
    )
    for liability in liabilities:
        liability.loan_file_id = loan_file.id
        db.add(liability)
    await db.flush()
    await _seed_housing(db, loan_file)
    return loan_file


def _liability(payment: str, **kw) -> StatedLiability:
    return StatedLiability(liability_type="MortgageLoan", monthly_payment=Decimal(payment), **kw)


async def test_a_paid_off_mortgage_leaves_the_back_end_ratio(db_session: AsyncSession) -> None:
    """THE HEADLINE. Housing is 677.78 (277.78 P&I + 400 T&I); the 3,000 mortgage is paid off, so
    only the 100 card remains. Back-end = 777.78/10,000, not 3,777.78/10,000."""
    loan_file = await _file_with(
        db_session,
        "payoff",
        [
            _liability("3000", paid_off_at_closing=True, payoff_source="mismo"),
            StatedLiability(liability_type="Revolving", monthly_payment=Decimal("100")),
        ],
    )

    calc = await build_dti_calculation(db_session, loan_file=loan_file)

    assert calc.monthly_debts == Decimal("100.00")
    assert calc.total_monthly_obligations == Decimal("777.78")
    assert calc.back_end_dti == Decimal("7.78")


async def test_the_excluded_line_is_still_shown_with_its_reason(db_session: AsyncSession) -> None:
    """A debt that silently VANISHES is worse than one counted wrongly — the processor loses the
    ability to see it was considered at all. The line stays, carrying its real amount, flagged."""
    loan_file = await _file_with(
        db_session, "shown", [_liability("3000", paid_off_at_closing=True, payoff_source="mismo")]
    )

    calc = await build_dti_calculation(db_session, loan_file=loan_file)

    (item,) = calc.debt_items
    assert item.excluded is True
    assert item.excluded_reason == "paid off at closing"
    assert item.amount == Decimal("3000.00")  # the real figure, not zeroed
    assert calc.monthly_debts == Decimal("0.00")


async def test_a_purchase_excludes_a_departing_residence_the_same_way(
    db_session: AsyncSession,
) -> None:
    """The fix is deliberately purpose-agnostic. A purchase has no subject-property mortgage to pay
    off, but it has the same shape: the borrower sells the home they live in, or clears a debt at
    closing to qualify. Deriving the exclusion from `loan_purpose == refinance` would have missed
    every one of those, which is why the flag lives on the LIABILITY."""
    loan_file = await _file_with(
        db_session,
        "purchase",
        [
            _liability("3000", paid_off_at_closing=True, payoff_source="processor"),
            StatedLiability(liability_type="Installment", monthly_payment=Decimal("500")),
        ],
    )
    # Nothing about this file says "refinance" — the loan purpose is never consulted.
    calc = await build_dti_calculation(db_session, loan_file=loan_file)

    assert calc.monthly_debts == Decimal("500.00")


async def test_an_unset_flag_still_counts(db_session: AsyncSession) -> None:
    """FAIL-CLOSED, and the direction matters. None means "nobody established this", not
    "retained". Over-counting fails a good file visibly; under-counting passes a bad one quietly,
    so silence must keep the debt in."""
    loan_file = await _file_with(db_session, "unset", [_liability("3000")])

    calc = await build_dti_calculation(db_session, loan_file=loan_file)

    assert calc.monthly_debts == Decimal("3000.00")


async def test_an_explicit_false_counts_too(db_session: AsyncSession) -> None:
    """A MISMO `false` reaches the DB as None, but a processor may one day set False outright.
    Only True excludes — `is True`, never truthiness."""
    loan_file = await _file_with(
        db_session, "false", [_liability("3000", paid_off_at_closing=False)]
    )

    calc = await build_dti_calculation(db_session, loan_file=loan_file)

    assert calc.monthly_debts == Decimal("3000.00")


async def test_the_lf_wchg_numbers_reproduce(db_session: AsyncSession) -> None:
    """The real file, as an arithmetic check on the whole chain. Housing is seeded directly rather
    than computed, so this pins the RATIO the domain expert confirmed — 34.39%, not 58.59%."""
    loan_file = await _file_with(
        db_session,
        "wchg",
        [
            _liability("3186.00", paid_off_at_closing=True, payoff_source="processor"),
            StatedLiability(liability_type="Revolving", monthly_payment=Decimal("49")),
            StatedLiability(liability_type="Revolving", monthly_payment=Decimal("35")),
            StatedLiability(liability_type="Revolving", monthly_payment=Decimal("25")),
        ],
    )

    calc = await build_dti_calculation(db_session, loan_file=loan_file)

    assert calc.monthly_debts == Decimal("109.00")
    # 3,186.00 of debt removed; what remains is exactly the three cards.
    assert sum(i.amount for i in calc.debt_items if i.excluded) == Decimal("3186.00")

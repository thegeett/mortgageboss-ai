"""LP-627 — the application states the property tax, and nothing read it.

THE THIRD INSTANCE of the catch_all mechanism, and the one with a dollar consequence. LF-ABRS's DTI
card read "Property taxes / unknown — missing or unusable input (fail-closed, never assumed $0)" while
the MISMO stated `RealEstateTax` at $541.67 a month under HOUSING_EXPENSES. That file's ratio sits at
44.8% against a 45% limit.

STATED, NOT VERIFIED. The gate is right to refuse an application's own figure — `_extracted_monthly`
reads the tax BILL for exactly that reason. What was wrong is being told the number is missing, going
to look, and finding it stated on the 1003.
"""

from __future__ import annotations

from decimal import Decimal

from app.models.stated_financials import StatedHousingExpense
from app.services.dti import _stated_housing_expense
from tests.integration import factories


async def _file(db):
    company = await factories.make_company(db, slug="acme")
    return await factories.make_loan_file(db, company=company)


async def _expense(db, loan_file, *, expense_type, amount, timing="Proposed"):
    row = StatedHousingExpense(
        loan_file_id=loan_file.id,
        expense_type=expense_type,
        timing=timing,
        payment_amount=Decimal(amount) if amount is not None else None,
    )
    db.add(row)
    await db.flush()
    return row


async def test_the_stated_property_tax_is_found(db_session) -> None:
    """LF-ABRS's actual figure."""
    loan_file = await _file(db_session)
    await _expense(db_session, loan_file, expense_type="RealEstateTax", amount="541.67")

    assert await _stated_housing_expense(db_session, loan_file.id, "RealEstateTax") == Decimal(
        "541.67"
    )


async def test_the_present_figure_is_not_read_as_the_proposed_one(db_session) -> None:
    """MISMO carries BOTH what this loan will cost and what the borrower pays TODAY. Reading the
    present figure as the proposed one would put the borrower's current rent into the new loan's
    housing payment."""
    loan_file = await _file(db_session)
    await _expense(
        db_session, loan_file, expense_type="RealEstateTax", amount="200.00", timing="Present"
    )

    assert await _stated_housing_expense(db_session, loan_file.id, "RealEstateTax") is None


async def test_two_contradictory_proposed_figures_state_nothing(db_session) -> None:
    """More than one PROPOSED figure for one expense type is a contradictory export, not a total to
    sum — adding them would invent a payment the application never states."""
    loan_file = await _file(db_session)
    await _expense(db_session, loan_file, expense_type="RealEstateTax", amount="541.67")
    await _expense(db_session, loan_file, expense_type="RealEstateTax", amount="600.00")

    assert await _stated_housing_expense(db_session, loan_file.id, "RealEstateTax") is None


async def test_an_absent_expense_is_none_not_zero(db_session) -> None:
    """The fail-closed reason (LP-375): absent is not $0, and a $0 tax would silently qualify a loan."""
    loan_file = await _file(db_session)

    assert await _stated_housing_expense(db_session, loan_file.id, "RealEstateTax") is None


async def test_a_different_expense_type_is_not_returned(db_session) -> None:
    """Insurance is not tax. The lookup is by type, and a near-match would put the wrong number on the
    card under the right label."""
    loan_file = await _file(db_session)
    await _expense(db_session, loan_file, expense_type="HomeownersInsurance", amount="100.00")

    assert await _stated_housing_expense(db_session, loan_file.id, "RealEstateTax") is None

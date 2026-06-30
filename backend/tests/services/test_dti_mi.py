"""LP-91 — the DTI consumes the LP-87 MI calculator (MI no longer omitted from PITI).

The DTI's mortgage-insurance housing line was manual-only / default $0, so PITI silently
omitted mandatory MI (FHA MIP always; Conventional PMI when LTV > 80%) — understating the
front-end DTI in the qualifying (dangerous) direction. These tests prove the fix: the DTI's
MI line now CONSUMES the shared MI computation (program-aware, single source of truth,
overrideable), the upfront MIP stays financed (not a monthly DTI item), and the DTI
recomputes when the MI changes (an LTV change, an MI-rate override).
"""

from decimal import Decimal

from app.models import (
    Borrower,
    Company,
    LoanProgram,
    StatedIncomeItem,
    User,
    UserRole,
)
from app.models.property import Property
from app.schemas.calculators import CalcOverrideInput
from app.schemas.dti import DtiOverrideInput
from app.services.calculators import set_calculator_override
from app.services.dti import (
    HOUSING_MORTGAGE_INSURANCE,
    HOUSING_PRINCIPAL_INTEREST,
    build_dti_calculation,
    set_dti_override,
)
from app.services.loan_files import create_loan_file
from app.services.mi import compute_loan_mi
from sqlalchemy.ext.asyncio import AsyncSession


async def _company(db: AsyncSession, slug: str = "acme") -> Company:
    company = Company(name=slug.title(), slug=slug)
    db.add(company)
    await db.flush()
    return company


async def _user(db: AsyncSession, company: Company) -> User:
    user = User(
        company_id=company.id,
        email=f"u@{company.slug}.test",
        hashed_password="h",  # pragma: allowlist secret
        first_name="Pro",
        last_name="Cessor",
        role=UserRole.PROCESSOR,
    )
    db.add(user)
    await db.flush()
    return user


async def _file(
    db: AsyncSession,
    company: Company,
    *,
    program: LoanProgram,
    loan: Decimal = Decimal("300000"),
    value: Decimal = Decimal("320000"),
    income: Decimal = Decimal("10000"),
):
    """A file with an LTV-driving property. loan 300k / value 320k → LTV 93.75% (PMI applies).

    P&I is 300k / 360 @ 0% = 833.33 (a clean base to read the MI contribution off PITI).
    """
    loan_file = await create_loan_file(db, company_id=company.id, loan_program=program)
    loan_file.note_amount = loan
    loan_file.loan_amount = loan
    loan_file.note_rate_percent = Decimal("0")
    loan_file.amortization_months = 360
    borrower = Borrower(
        loan_file_id=loan_file.id, first_name="Mahesh", last_name="C", is_primary=True
    )
    db.add(borrower)
    db.add(Property(loan_file_id=loan_file.id, purchase_price=value, valuation_amount=value))
    await db.flush()
    db.add(
        StatedIncomeItem(
            borrower_id=borrower.id,
            monthly_amount=income,
            income_type="Base",
            employment_income=True,
        )
    )
    await db.flush()
    return loan_file


def _mi_line(calc):
    return next(i for i in calc.housing_items if i.key == HOUSING_MORTGAGE_INSURANCE)


def _pi_line(calc):
    return next(i for i in calc.housing_items if i.key == HOUSING_PRINCIPAL_INTEREST)


# --- The core fix: MI is in PITI, consumed from the MI calculator --------------


async def test_fha_dti_includes_monthly_mip_no_longer_omitted(db_session: AsyncSession) -> None:
    """LP-91 correctness: an FHA file's PITI now includes the monthly MIP (was omitted/$0)."""
    company = await _company(db_session)
    fha = await _file(db_session, company, program=LoanProgram.FHA)

    calc = await build_dti_calculation(db_session, loan_file=fha)
    mi = _mi_line(calc)

    # The MI line is no longer the old manual/None placeholder — it has a computed auto value.
    assert mi.auto_amount is not None and mi.auto_amount > 0
    assert mi.source == "computed"
    # 300000 x 55bps / 12 = 137.50 (the FHA monthly annual-MIP starter).
    assert mi.auto_amount == Decimal("137.50")
    # It is actually in PITI: housing payment = P&I + MI (taxes/ins/hoa absent here).
    assert calc.housing_payment == _pi_line(calc).amount + Decimal("137.50")
    # The front-end DTI reflects MI (not the MI-omitted, understated value).
    assert calc.front_end_dti == Decimal("9.71")  # (833.33 + 137.50) / 10000


async def test_dti_mi_equals_mi_calculator_single_source_of_truth(db_session: AsyncSession) -> None:
    """The DTI's MI value EQUALS the MI calculator's monthly_premium — one source, no drift."""
    company = await _company(db_session)
    fha = await _file(db_session, company, program=LoanProgram.FHA)

    calc = await build_dti_calculation(db_session, loan_file=fha)
    mi_comp = await compute_loan_mi(db_session, loan_file=fha)

    assert _mi_line(calc).auto_amount == mi_comp.result.monthly_premium


async def test_conventional_pmi_program_aware_above_and_below_80(db_session: AsyncSession) -> None:
    """Conventional: PMI in PITI when LTV > 80%; $0 / not-required when LTV ≤ 80%."""
    company = await _company(db_session)

    # LTV 93.75% (loan 300k / value 320k) → PMI required.
    high = await _file(db_session, company, program=LoanProgram.CONVENTIONAL)
    high_calc = await build_dti_calculation(db_session, loan_file=high)
    assert _mi_line(high_calc).auto_amount == Decimal("137.50")  # 300k x 55bps / 12

    # LTV 75% (loan 300k / value 400k) → PMI NOT required → MI auto absent (0 in PITI).
    low = await _file(
        db_session, company, program=LoanProgram.CONVENTIONAL, value=Decimal("400000")
    )
    low_calc = await build_dti_calculation(db_session, loan_file=low)
    assert _mi_line(low_calc).auto_amount is None
    # PITI excludes MI when not required.
    assert low_calc.housing_payment == _pi_line(low_calc).amount


# --- Upfront MIP stays financed (not a monthly DTI item) ----------------------


async def test_upfront_mip_is_not_in_monthly_dti(db_session: AsyncSession) -> None:
    """Only the monthly MIP enters PITI; the financed UFMIP (1.75% = $5,250) does NOT."""
    company = await _company(db_session)
    fha = await _file(db_session, company, program=LoanProgram.FHA)

    calc = await build_dti_calculation(db_session, loan_file=fha)
    mi_comp = await compute_loan_mi(db_session, loan_file=fha)

    # The UFMIP is computed (financed) but must not appear in the monthly housing payment.
    assert mi_comp.result.upfront_premium == Decimal("5250.00")  # 300000 x 175bps
    assert calc.housing_payment == _pi_line(calc).amount + Decimal("137.50")
    assert calc.housing_payment < Decimal("5250")  # the upfront is nowhere in monthly DTI


# --- Overrideable: a DtiOverride still wins -----------------------------------


async def test_mi_override_wins_over_consumed_auto(db_session: AsyncSession) -> None:
    """The consumed MI is the AUTO value; a processor DtiOverride (the real quote) still wins."""
    company = await _company(db_session)
    user = await _user(db_session, company)
    fha = await _file(db_session, company, program=LoanProgram.FHA)

    calc = await set_dti_override(
        db_session,
        loan_file=fha,
        field_key=HOUSING_MORTGAGE_INSURANCE,
        data=DtiOverrideInput(amount=Decimal("250.00")),
        actor_user_id=user.id,
    )
    mi = _mi_line(calc)
    assert mi.overridden is True
    assert mi.amount == Decimal("250.00")  # the override
    assert mi.auto_amount == Decimal("137.50")  # the consumed auto is preserved underneath
    # PITI uses the override, not the auto.
    assert calc.housing_payment == _pi_line(calc).amount + Decimal("250.00")


# --- Recompute on MI change ---------------------------------------------------


async def test_dti_recomputes_when_ltv_drops_pmi_off(db_session: AsyncSession) -> None:
    """An LTV change (raise the value below 80%) recomputes the DTI's PMI → MI drops to $0."""
    company = await _company(db_session)
    conv = await _file(db_session, company, program=LoanProgram.CONVENTIONAL)

    before = await build_dti_calculation(db_session, loan_file=conv)
    assert _mi_line(before).auto_amount == Decimal("137.50")  # LTV 93.75% → PMI

    # Raise the property value so LTV ≤ 80% → PMI no longer required.
    prop = await db_session.get(Property, (await _only_property_id(db_session, conv.id)))
    assert prop is not None
    prop.valuation_amount = Decimal("400000")
    prop.purchase_price = Decimal("400000")
    await db_session.flush()

    after = await build_dti_calculation(db_session, loan_file=conv)
    assert _mi_line(after).auto_amount is None  # live recompute — PMI is off


async def test_dti_recomputes_when_mi_rate_overridden(db_session: AsyncSession) -> None:
    """An MI-calculator rate override flows into the DTI (single source — live consumption)."""
    company = await _company(db_session)
    user = await _user(db_session, company)
    conv = await _file(db_session, company, program=LoanProgram.CONVENTIONAL)

    before = await build_dti_calculation(db_session, loan_file=conv)
    assert _mi_line(before).auto_amount == Decimal("137.50")  # 55 bps starter

    # Override the PMI rate in the MI calculator (110 bps) → the DTI's MI doubles.
    await set_calculator_override(
        db_session,
        loan_file=conv,
        calculator="mortgage_insurance",
        field_key="mi.pmi_rate_bps",
        data=CalcOverrideInput(amount=Decimal("110")),
        actor_user_id=user.id,
    )
    after = await build_dti_calculation(db_session, loan_file=conv)
    assert _mi_line(after).auto_amount == Decimal("275.00")  # 300k x 110bps / 12


# --- Tenant scoping -----------------------------------------------------------


async def test_mi_consumption_is_tenant_scoped(db_session: AsyncSession) -> None:
    """The MI computation reads only the file's own data (no cross-tenant leakage)."""
    company_a = await _company(db_session, "company-a")
    company_b = await _company(db_session, "company-b")
    fha_a = await _file(db_session, company_a, program=LoanProgram.FHA)
    conv_b = await _file(
        db_session, company_b, program=LoanProgram.CONVENTIONAL, value=Decimal("400000")
    )

    calc_a = await build_dti_calculation(db_session, loan_file=fha_a)
    calc_b = await build_dti_calculation(db_session, loan_file=conv_b)

    assert _mi_line(calc_a).auto_amount == Decimal("137.50")  # FHA MIP
    assert _mi_line(calc_b).auto_amount is None  # B's LTV ≤ 80% → no PMI; unaffected by A


async def _only_property_id(db: AsyncSession, loan_file_id):
    from sqlalchemy import select

    return (
        await db.execute(select(Property.id).where(Property.loan_file_id == loan_file_id))
    ).scalar_one()

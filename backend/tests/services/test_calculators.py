"""The four LP-87 calculators — DB service (auto-populate, override→recompute, audit).

Covers: program-aware MI (Conventional PMI vs FHA MIP formulas/steps); the self-employed
override→recompute (qualifying income changes); reserves' 60% FHA retirement haircut step;
max-loan's three constraints; the shared override is persisted + audited
(CALCULATOR_OVERRIDDEN); and an unknown field is rejected.
"""

from decimal import Decimal

from app.models import (
    ActivityLog,
    Borrower,
    Company,
    LoanProgram,
    StatedAsset,
    StatedIncomeItem,
    User,
    UserRole,
)
from app.models.activity_log import ActivityType
from app.schemas.calculators import CalcOverrideInput
from app.services.calculators import (
    UnknownCalcFieldError,
    build_calculator,
    clear_calculator_override,
    set_calculator_override,
)
from app.services.loan_files import create_loan_file
from app.verification.mortgage_insurance import CONVENTIONAL_PMI_FORMULA, FHA_UFMIP_FORMULA
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _company(db: AsyncSession) -> Company:
    company = Company(name="Acme", slug="acme")
    db.add(company)
    await db.flush()
    return company


async def _user(db: AsyncSession, company: Company) -> User:
    user = User(
        company_id=company.id,
        email="u@acme.test",
        hashed_password="h",  # pragma: allowlist secret
        first_name="Pro",
        last_name="Cessor",
        role=UserRole.PROCESSOR,
    )
    db.add(user)
    await db.flush()
    return user


async def _file(db: AsyncSession, company: Company, *, program: LoanProgram):
    loan_file = await create_loan_file(db, company_id=company.id, loan_program=program)
    loan_file.note_amount = Decimal("300000")
    loan_file.note_rate_percent = Decimal("6.5")
    loan_file.amortization_months = 360
    borrower = Borrower(
        loan_file_id=loan_file.id, first_name="Mahesh", last_name="C", is_primary=True
    )
    db.add(borrower)
    await db.flush()
    db.add(
        StatedIncomeItem(
            borrower_id=borrower.id,
            monthly_amount=Decimal("12000"),
            income_type="Self-employment",
            employment_income=True,
        )
    )
    await db.flush()
    return loan_file


# --- Program-aware MI --------------------------------------------------------


async def test_mi_is_program_aware(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    fha = await _file(db_session, company, program=LoanProgram.FHA)
    conv = await _file(db_session, company, program=LoanProgram.CONVENTIONAL)

    fha_view = await build_calculator(db_session, loan_file=fha, calculator="mortgage_insurance")
    assert fha_view.program == "fha"
    assert FHA_UFMIP_FORMULA in fha_view.formulas
    # FHA always carries MIP — an upfront step + a monthly premium headline.
    assert any("Upfront MIP" in s.label for s in fha_view.steps)
    assert fha_view.methodology.starter is True

    conv_view = await build_calculator(db_session, loan_file=conv, calculator="mortgage_insurance")
    assert conv_view.program == "conventional"
    assert CONVENTIONAL_PMI_FORMULA in conv_view.formulas


async def test_mi_override_recomputes_and_audits(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    user = await _user(db_session, company)
    fha = await _file(db_session, company, program=LoanProgram.FHA)

    # Override the base loan amount → the upfront MIP (1.75%) recomputes.
    view = await set_calculator_override(
        db_session,
        loan_file=fha,
        calculator="mortgage_insurance",
        field_key="mi.base_loan_amount",
        data=CalcOverrideInput(amount=Decimal("400000")),
        actor_user_id=user.id,
    )
    upfront = next(s for s in view.steps if "Upfront MIP" in s.label)
    assert upfront.value == "$7,000.00"  # 1.75% of 400k
    base_line = next(line for line in view.inputs if line.key == "mi.base_loan_amount")
    assert base_line.overridden is True and base_line.amount == Decimal("400000")

    # The override is audited (CALCULATOR_OVERRIDDEN, with from→to values).
    logs = (
        (await db_session.execute(select(ActivityLog).where(ActivityLog.loan_file_id == fha.id)))
        .scalars()
        .all()
    )
    override_logs = [log for log in logs if log.activity_type is ActivityType.CALCULATOR_OVERRIDDEN]
    assert len(override_logs) == 1
    assert override_logs[0].detail["to"] == "400000"


# --- Self-employed feeds DTI (override → qualifying income) -------------------


async def test_self_employed_override_changes_qualifying_income(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    user = await _user(db_session, company)
    loan_file = await _file(db_session, company, program=LoanProgram.CONVENTIONAL)

    await set_calculator_override(
        db_session,
        loan_file=loan_file,
        calculator="self_employed",
        field_key="se.y2.net_profit",
        data=CalcOverrideInput(amount=Decimal("100000")),
        actor_user_id=user.id,
    )
    view = await set_calculator_override(
        db_session,
        loan_file=loan_file,
        calculator="self_employed",
        field_key="se.y1.net_profit",
        data=CalcOverrideInput(amount=Decimal("100000")),
        actor_user_id=user.id,
    )
    # avg 100000 → monthly 8333.33; the headline + the qualifying step reflect it.
    assert "8,333.33" in (view.headline or "")
    assert "feeds the dti" in view.methodology.text.lower()  # the feed-to-DTI seam is documented

    # Clearing reverts to the auto (None → 0) value.
    reverted = await clear_calculator_override(
        db_session,
        loan_file=loan_file,
        calculator="self_employed",
        field_key="se.y2.net_profit",
        actor_user_id=user.id,
    )
    line = next(line for line in reverted.inputs if line.key == "se.y2.net_profit")
    assert line.overridden is False


# --- Reserves (60% FHA haircut) ----------------------------------------------


async def test_reserves_apply_fha_retirement_haircut(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    fha = await _file(db_session, company, program=LoanProgram.FHA)
    db_session.add(
        StatedAsset(loan_file_id=fha.id, asset_type="401(k) Retirement", value=Decimal("100000"))
    )
    db_session.add(StatedAsset(loan_file_id=fha.id, asset_type="Checking", value=Decimal("30000")))
    await db_session.flush()

    view = await build_calculator(db_session, loan_file=fha, calculator="reserves")
    haircut = next(s for s in view.steps if "Retirement counted" in s.label)
    assert "60%" in haircut.label
    assert haircut.value == "$60,000.00"  # 60% of 100k


# --- Max loan (three constraints) --------------------------------------------


async def test_max_loan_shows_three_constraints(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    conv = await _file(db_session, company, program=LoanProgram.CONVENTIONAL)
    view = await build_calculator(db_session, loan_file=conv, calculator="max_loan")
    labels = " ".join(s.label for s in view.steps)
    assert "DTI ceiling" in labels and "LTV limit" in labels and "Program loan limit" in labels


# --- Unknown field rejected --------------------------------------------------


async def test_unknown_calculator_field_is_rejected(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    user = await _user(db_session, company)
    conv = await _file(db_session, company, program=LoanProgram.CONVENTIONAL)
    try:
        await set_calculator_override(
            db_session,
            loan_file=conv,
            calculator="reserves",
            field_key="reserves.not_a_field",
            data=CalcOverrideInput(amount=Decimal("1")),
            actor_user_id=user.id,
        )
        raise AssertionError("expected UnknownCalcFieldError")
    except UnknownCalcFieldError:
        pass

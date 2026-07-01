"""LP-98 — Undo for resolved findings (reverse Apply / Accept-risk / Override).

The hard part: UNDO-APPLIED must REVERSE the data change EXACTLY (restore the recorded pre-apply
state via ``applied_record``, not an approximation) and recompute the DTI back to its exact
pre-apply value; the finding returns to OPEN (so the un-applied issue re-detects — LP-94 compose).
Undo-Accept/Override just reopen (no data change).
"""

from decimal import Decimal
from uuid import UUID

from app.models import (
    ActivityLog,
    ActivityType,
    Borrower,
    Company,
    Finding,
    FindingCategory,
    FindingOrigin,
    FindingResolutionStatus,
    FindingStatus,
    LoanProgram,
    StatedIncomeItem,
    StatedLiability,
    User,
    UserRole,
)
from app.services.dti import build_dti_calculation
from app.services.finding_resolution import (
    CannotUndoError,
    accept_risk_finding,
    apply_finding,
    override_finding,
    undo_finding,
)
from app.services.loan_files import create_loan_file
from sqlalchemy import select
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


async def _file(db: AsyncSession, company: Company):
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    loan_file.note_amount = Decimal("300000")
    loan_file.note_rate_percent = Decimal("0")
    loan_file.amortization_months = 360
    borrower = Borrower(
        loan_file_id=loan_file.id, first_name="Mahesh", last_name="C", is_primary=True
    )
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
    db.add(
        StatedLiability(
            loan_file_id=loan_file.id, liability_type="Card", monthly_payment=Decimal("2000")
        )
    )
    await db.flush()
    return loan_file, borrower


async def _finding(
    db: AsyncSession, loan_file, *, apply_spec: dict | None = None, status=FindingStatus.RED
) -> Finding:
    details: dict = {"type": "liability_discrepancy"}
    if apply_spec is not None:
        details["apply"] = apply_spec
    finding = Finding(
        loan_file_id=loan_file.id,
        rule_id="xsrc.liability.undisclosed_debt",
        origin=FindingOrigin.DETERMINISTIC_RULE,
        status=status,
        category=FindingCategory.CREDIT,
        message="Undisclosed obligation in the documents.",
        confidence=1.0,
        resolution_status=FindingResolutionStatus.OPEN,
        details=details,
    )
    db.add(finding)
    await db.flush()
    return finding


async def _live_liabilities(db: AsyncSession, loan_file_id: UUID) -> list[StatedLiability]:
    rows = (
        (
            await db.execute(
                select(StatedLiability).where(
                    StatedLiability.loan_file_id == loan_file_id,
                    StatedLiability.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


# --- UNDO-APPLIED: reverse the data + recompute to the EXACT pre-apply value ---


async def test_undo_applied_reverses_data_and_recomputes_exactly(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    user = await _user(db_session, company)
    loan_file, _ = await _file(db_session, company)
    finding = await _finding(
        db_session,
        loan_file,
        apply_spec={
            "action": "add_liability",
            "liability_type": "Installment",
            "monthly_payment": "500",
            "holder_name": "Auto",
        },
    )

    dti_pre = await build_dti_calculation(db_session, loan_file=loan_file)
    libs_pre = len(await _live_liabilities(db_session, loan_file.id))

    # Apply → the liability is added, the DTI goes up.
    await apply_finding(db_session, finding=finding, loan_file=loan_file, actor_user_id=user.id)
    dti_applied = await build_dti_calculation(db_session, loan_file=loan_file)
    assert dti_applied.back_end_dti > dti_pre.back_end_dti
    assert len(await _live_liabilities(db_session, loan_file.id)) == libs_pre + 1

    # Undo → the added liability is removed, the DTI recomputes BACK to the EXACT pre-apply value.
    await undo_finding(db_session, finding=finding, loan_file=loan_file, actor_user_id=user.id)
    dti_undone = await build_dti_calculation(db_session, loan_file=loan_file)
    assert dti_undone.back_end_dti == dti_pre.back_end_dti  # exact reversal, not approximated
    assert dti_undone.monthly_debts == dti_pre.monthly_debts
    assert len(await _live_liabilities(db_session, loan_file.id)) == libs_pre  # the row is gone
    # The finding is OPEN again (un-applied → it will re-detect), the trail cleared.
    assert finding.resolution_status is FindingResolutionStatus.OPEN
    assert finding.applied_record is None
    assert finding.resolved_at is None


async def test_undo_applied_restores_the_exact_prior_income(db_session: AsyncSession) -> None:
    """correct_income undo restores the recorded prior value — not a guess."""
    company = await _company(db_session)
    user = await _user(db_session, company)
    loan_file, borrower = await _file(db_session, company)
    income = (
        (
            await db_session.execute(
                select(StatedIncomeItem).where(StatedIncomeItem.borrower_id == borrower.id)
            )
        )
        .scalars()
        .first()
    )
    assert income is not None and income.monthly_amount == Decimal("10000")

    finding = await _finding(
        db_session,
        loan_file,
        apply_spec={
            "action": "correct_income",
            "income_item_id": str(income.id),
            "monthly_amount": "8000",
        },
    )
    await apply_finding(db_session, finding=finding, loan_file=loan_file, actor_user_id=user.id)
    await db_session.refresh(income)
    assert income.monthly_amount == Decimal("8000")  # corrected down

    await undo_finding(db_session, finding=finding, loan_file=loan_file, actor_user_id=user.id)
    await db_session.refresh(income)
    assert income.monthly_amount == Decimal("10000")  # restored to the exact prior value


# --- UNDO-ACCEPT / OVERRIDE: reopen, no data change --------------------------


async def test_undo_accept_risk_reopens_without_a_data_change(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    user = await _user(db_session, company)
    loan_file, _ = await _file(db_session, company)
    finding = await _finding(db_session, loan_file)
    libs_pre = len(await _live_liabilities(db_session, loan_file.id))
    await accept_risk_finding(
        db_session, finding=finding, actor_user_id=user.id, reason="compensating reserves"
    )

    await undo_finding(db_session, finding=finding, loan_file=loan_file, actor_user_id=user.id)
    assert finding.resolution_status is FindingResolutionStatus.OPEN
    assert finding.resolution_note is None
    assert len(await _live_liabilities(db_session, loan_file.id)) == libs_pre  # no data touched


async def test_undo_overridden_reopens_without_a_data_change(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    user = await _user(db_session, company)
    loan_file, _ = await _file(db_session, company)
    finding = await _finding(db_session, loan_file)
    await override_finding(
        db_session, finding=finding, actor_user_id=user.id, reason="already disclosed"
    )

    await undo_finding(db_session, finding=finding, loan_file=loan_file, actor_user_id=user.id)
    assert finding.resolution_status is FindingResolutionStatus.OPEN
    assert finding.resolution_note is None


# --- Audit + guards -----------------------------------------------------------


async def test_undo_is_audited(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    user = await _user(db_session, company)
    loan_file, _ = await _file(db_session, company)
    finding = await _finding(
        db_session, loan_file, apply_spec={"action": "add_liability", "monthly_payment": "500"}
    )
    await apply_finding(db_session, finding=finding, loan_file=loan_file, actor_user_id=user.id)
    await undo_finding(db_session, finding=finding, loan_file=loan_file, actor_user_id=user.id)

    logs = (
        (
            await db_session.execute(
                select(ActivityLog).where(
                    ActivityLog.loan_file_id == loan_file.id,
                    ActivityLog.activity_type == ActivityType.FINDING_UNDONE,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(logs) == 1
    assert logs[0].actor_user_id == user.id
    assert logs[0].detail["undone_from"] == "applied"
    assert logs[0].detail["reversed_change"]["action"] == "remove_liability"


async def test_cannot_undo_an_open_finding(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    user = await _user(db_session, company)
    loan_file, _ = await _file(db_session, company)
    finding = await _finding(db_session, loan_file)  # OPEN
    try:
        await undo_finding(db_session, finding=finding, loan_file=loan_file, actor_user_id=user.id)
        raise AssertionError("expected CannotUndoError")
    except CannotUndoError:
        pass


async def test_undo_reversal_is_tenant_scoped(db_session: AsyncSession) -> None:
    """A finding's applied liability is only reversed for its own file (the tenant check)."""
    company_a = await _company(db_session, "company-a")
    company_b = await _company(db_session, "company-b")
    file_a, _ = await _file(db_session, company_a)
    file_b, _ = await _file(db_session, company_b)
    user_a = await _user(db_session, company_a)

    finding = await _finding(
        db_session, file_a, apply_spec={"action": "add_liability", "monthly_payment": "500"}
    )
    await apply_finding(db_session, finding=finding, loan_file=file_a, actor_user_id=user_a.id)
    b_libs = len(await _live_liabilities(db_session, file_b.id))

    await undo_finding(db_session, finding=finding, loan_file=file_a, actor_user_id=user_a.id)
    # File B is untouched by A's undo.
    assert len(await _live_liabilities(db_session, file_b.id)) == b_libs

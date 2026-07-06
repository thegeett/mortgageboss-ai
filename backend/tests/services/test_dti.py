"""The DTI calculator service (LP-76) — auto-populate, override, findings-couple.

Covers auto-population from the structured data, override (precedence + audit),
the effective-limit resolution (program default + overlay-tightened), the
unresolved-findings alert, and recompute-on-applied-finding (LP-76 is a recompute
consumer of LP-75's hook). Uses the transaction-rollback ``db_session`` fixture.
"""

from decimal import Decimal

from app.models import (
    ActivityLog,
    ActivityType,
    Borrower,
    Company,
    Finding,
    FindingCategory,
    FindingOrigin,
    FindingStatus,
    Lender,
    LoanProgram,
    StatedIncomeItem,
    StatedLiability,
    User,
    UserRole,
)
from app.schemas.dti import DtiOverrideInput
from app.services.dti import (
    HOUSING_MORTGAGE_INSURANCE,
    UnknownDtiFieldError,
    build_dti_calculation,
    clear_dti_override,
    set_dti_override,
)
from app.services.finding_resolution import apply_finding
from app.services.loan_files import create_loan_file
from app.verification.overlays.samples import SAMPLE_OVERLAY_LENDER_SLUG
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _company(db: AsyncSession, slug: str) -> Company:
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


async def _file_with_financials(
    db: AsyncSession,
    company: Company,
    *,
    lender_id=None,
    income: Decimal = Decimal("10000"),
    debt: Decimal = Decimal("2000"),
):
    """A Conventional file: $10k income, a $2k debt, $100k @ 0% / 360mo (P&I = 277.78)."""
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL, lender_id=lender_id
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
            monthly_amount=income,
            income_type="Base",
            employment_income=True,
        )
    )
    db.add(
        StatedLiability(
            loan_file_id=loan_file.id, liability_type="Installment", monthly_payment=debt
        )
    )
    await db.flush()
    return loan_file


async def test_auto_populates_from_structured_data(db_session: AsyncSession) -> None:
    """The calculator opens already filled from the file's stated data."""
    company = await _company(db_session, "acme")
    loan_file = await _file_with_financials(db_session, company)

    calc = await build_dti_calculation(db_session, loan_file=loan_file)

    assert calc.gross_monthly_income == Decimal("10000")
    # Income itemized (one stated item).
    assert len(calc.income_items) == 1
    assert calc.income_items[0].auto_amount == Decimal("10000")
    assert calc.income_items[0].source == "stated"
    # Housing itemized: P&I computed ($100k / 360 @ 0% = 277.78) + the 4 placeholders.
    pi = next(i for i in calc.housing_items if i.key == "housing.principal_interest")
    assert pi.auto_amount == Decimal("277.78")
    assert pi.source == "computed"
    # Debt itemized.
    assert len(calc.debt_items) == 1
    assert calc.debt_items[0].auto_amount == Decimal("2000")
    # Ratios: housing 277.78 / 10000 = 2.78; back (277.78 + 2000)/10000 = 22.78.
    assert calc.front_end_dti == Decimal("2.78")
    assert calc.back_end_dti == Decimal("22.78")
    # The explicit formula is present.
    assert "Back-end DTI" in calc.back_end_formula


async def test_effective_limit_program_default(db_session: AsyncSession) -> None:
    """A Conventional file shows the 50% investor default, pass/over computed."""
    company = await _company(db_session, "acme")
    loan_file = await _file_with_financials(db_session, company)

    calc = await build_dti_calculation(db_session, loan_file=loan_file)

    assert calc.limit.back_end_max == Decimal("50")
    assert calc.limit.source == "program_default"
    assert calc.limit.status == "pass"  # 22.78 <= 50


async def test_effective_limit_overlay_tightened(db_session: AsyncSession) -> None:
    """A lender overlay tightens the limit to 45 (LP-74's effective rule)."""
    company = await _company(db_session, "acme")
    lender = Lender(
        company_id=company.id,
        name="Sample Overlay Bank",
        slug=SAMPLE_OVERLAY_LENDER_SLUG,
        supported_programs=["conventional"],
    )
    db_session.add(lender)
    await db_session.flush()
    loan_file = await _file_with_financials(db_session, company, lender_id=lender.id)

    calc = await build_dti_calculation(db_session, loan_file=loan_file)

    assert calc.limit.back_end_max == Decimal("45")
    assert calc.limit.source == "overlay"
    assert calc.limit.lender_slug == SAMPLE_OVERLAY_LENDER_SLUG


async def test_override_takes_precedence_recomputes_and_is_audited(
    db_session: AsyncSession,
) -> None:
    """Overriding a debt changes the effective value, recomputes, and is logged."""
    company = await _company(db_session, "acme")
    user = await _user(db_session, company)
    loan_file = await _file_with_financials(db_session, company)
    debt_key = (await build_dti_calculation(db_session, loan_file=loan_file)).debt_items[0].key

    # Override the $2000 debt down to $0 (paid at closing).
    calc = await set_dti_override(
        db_session,
        loan_file=loan_file,
        field_key=debt_key,
        data=DtiOverrideInput(amount=Decimal("0"), note="Paid at closing"),
        actor_user_id=user.id,
    )

    debt = next(i for i in calc.debt_items if i.key == debt_key)
    assert debt.override_amount == Decimal("0")
    assert debt.amount == Decimal("0")
    assert debt.overridden is True
    assert debt.source == "override"
    # Back-end recomputed without the debt: 277.78 / 10000 = 2.78.
    assert calc.back_end_dti == Decimal("2.78")

    # Audited with the prior value (2000 → 0).
    logs = (
        (
            await db_session.execute(
                select(ActivityLog).where(
                    ActivityLog.loan_file_id == loan_file.id,
                    ActivityLog.activity_type == ActivityType.DTI_OVERRIDDEN,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(logs) == 1
    assert logs[0].detail["field_key"] == debt_key
    assert logs[0].detail["from"] == "2000.00"
    assert logs[0].detail["to"] == "0"
    assert logs[0].actor_user_id == user.id


async def test_override_persists_and_clears(db_session: AsyncSession) -> None:
    """An override persists across reads; clearing reverts to the auto value."""
    company = await _company(db_session, "acme")
    user = await _user(db_session, company)
    loan_file = await _file_with_financials(db_session, company)

    await set_dti_override(
        db_session,
        loan_file=loan_file,
        field_key=HOUSING_MORTGAGE_INSURANCE,
        data=DtiOverrideInput(amount=Decimal("150")),
        actor_user_id=user.id,
    )
    # Persists on a fresh read.
    reread = await build_dti_calculation(db_session, loan_file=loan_file)
    mi = next(i for i in reread.housing_items if i.key == HOUSING_MORTGAGE_INSURANCE)
    assert mi.amount == Decimal("150")
    assert mi.overridden is True

    # Clearing reverts to the auto value (None → 0).
    cleared = await clear_dti_override(
        db_session, loan_file=loan_file, field_key=HOUSING_MORTGAGE_INSURANCE, actor_user_id=user.id
    )
    mi2 = next(i for i in cleared.housing_items if i.key == HOUSING_MORTGAGE_INSURANCE)
    assert mi2.overridden is False
    assert mi2.amount == Decimal("0")


async def test_unknown_field_key_rejected(db_session: AsyncSession) -> None:
    """Overriding a non-existent input field is rejected."""
    company = await _company(db_session, "acme")
    user = await _user(db_session, company)
    loan_file = await _file_with_financials(db_session, company)

    try:
        await set_dti_override(
            db_session,
            loan_file=loan_file,
            field_key="debt.does-not-exist",
            data=DtiOverrideInput(amount=Decimal("1")),
            actor_user_id=user.id,
        )
    except UnknownDtiFieldError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected UnknownDtiFieldError")


async def test_unresolved_findings_alert(db_session: AsyncSession) -> None:
    """An open in-scope finding raises the unresolved-findings alert."""
    company = await _company(db_session, "acme")
    loan_file = await _file_with_financials(db_session, company)
    assert (
        await build_dti_calculation(db_session, loan_file=loan_file)
    ).findings.unresolved is False

    db_session.add(
        Finding(
            loan_file_id=loan_file.id,
            rule_id="cross_source.income.discrepancy",
            origin=FindingOrigin.AI_CROSS_SOURCE,
            confidence=0.9,
            status=FindingStatus.YELLOW,
            category=FindingCategory.INCOME,
            message="Possible undisclosed obligation.",
        )
    )
    await db_session.flush()

    calc = await build_dti_calculation(db_session, loan_file=loan_file)
    assert calc.findings.unresolved is True
    assert calc.findings.open_in_scope_count == 1


async def test_recompute_on_applied_finding(db_session: AsyncSession) -> None:
    """Applying an obligation finding adds a liability → the DTI recomputes higher.

    LP-76 is a recompute consumer of LP-75's apply hook: the structured-data
    change (a new liability) flows straight into the next calculation.
    """
    company = await _company(db_session, "acme")
    user = await _user(db_session, company)
    loan_file = await _file_with_financials(db_session, company)
    before = await build_dti_calculation(db_session, loan_file=loan_file)

    finding = Finding(
        loan_file_id=loan_file.id,
        rule_id="cross_source.liabilities.undisclosed",
        origin=FindingOrigin.AI_CROSS_SOURCE,
        confidence=0.8,
        status=FindingStatus.YELLOW,
        category=FindingCategory.CROSS_SOURCE,
        message="Undisclosed $800 obligation on the credit report.",
        details={"apply": {"action": "add_liability", "monthly_payment": "800"}},
    )
    db_session.add(finding)
    await db_session.flush()

    await apply_finding(db_session, finding=finding, loan_file=loan_file, actor_user_id=user.id)

    after = await build_dti_calculation(db_session, loan_file=loan_file)
    assert len(after.debt_items) == len(before.debt_items) + 1
    assert after.monthly_debts == before.monthly_debts + Decimal("800")
    assert after.back_end_dti is not None and before.back_end_dti is not None
    assert after.back_end_dti > before.back_end_dti  # the DTI rose


async def test_calculation_is_tenant_scoped(db_session: AsyncSession) -> None:
    """Auto-population reads only the file's own data (per-file)."""
    company = await _company(db_session, "acme")
    other = await _company(db_session, "other")
    mine = await _file_with_financials(db_session, company, income=Decimal("10000"))
    theirs = await _file_with_financials(db_session, other, income=Decimal("99999"))

    calc = await build_dti_calculation(db_session, loan_file=mine)
    assert calc.gross_monthly_income == Decimal("10000")  # not theirs
    assert theirs.id != mine.id

"""The LTV calculator service (LP-77) — auto-populate, override, refi-aware, coupled.

Covers auto-population (incl. the graceful appraised-value handling), the override
(precedence + audit), the purpose-varying effective limit, the unresolved-findings
alert, and recompute-on-structured-data-change (the recompute-consumer pattern).
"""

from decimal import Decimal

from app.models import (
    ActivityLog,
    ActivityType,
    Company,
    Finding,
    FindingCategory,
    FindingOrigin,
    FindingStatus,
    LoanProgram,
    LoanPurpose,
    Property,
    RefinanceType,
    User,
    UserRole,
)
from app.schemas.ltv import LtvOverrideInput
from app.services.loan_files import create_loan_file
from app.services.ltv import (
    LTV_APPRAISED_VALUE,
    LTV_HELOC_LIMIT,
    UnknownLtvFieldError,
    build_ltv_calculation,
    clear_ltv_override,
    set_ltv_override,
)
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


async def _purchase_file(
    db: AsyncSession,
    company: Company,
    *,
    loan_amount: Decimal = Decimal("180000"),
    purchase_price: Decimal | None = Decimal("190000"),
    valuation: Decimal | None = Decimal("200000"),
    lender_id=None,
):
    """A Conventional purchase: loan 180k, price 190k, appraised 200k → LTV on 190k."""
    loan_file = await create_loan_file(
        db,
        company_id=company.id,
        loan_program=LoanProgram.CONVENTIONAL,
        loan_purpose=LoanPurpose.PURCHASE,
        lender_id=lender_id,
    )
    loan_file.loan_amount = loan_amount
    db.add(
        Property(
            loan_file_id=loan_file.id,
            purchase_price=purchase_price,
            valuation_amount=valuation,
        )
    )
    await db.flush()
    return loan_file


async def test_auto_populates_and_uses_lesser_of(db_session: AsyncSession) -> None:
    """Opens filled; LTV uses the lesser of price (190k) and appraised (200k)."""
    company = await _company(db_session, "acme")
    loan_file = await _purchase_file(db_session, company)

    calc = await build_ltv_calculation(db_session, loan_file=loan_file)

    assert calc.purpose == "purchase"
    assert calc.value_basis == Decimal("190000")  # the lesser-of
    assert "lesser of" in calc.value_basis_label
    assert calc.ltv == Decimal("94.74")  # 180000 / 190000
    first = next(i for i in calc.loan_items if i.key == "ltv.first_loan")
    assert first.auto_amount == Decimal("180000")
    price = next(i for i in calc.value_items if i.key == "ltv.purchase_price")
    assert price.auto_amount == Decimal("190000")


async def test_appraised_value_graceful_when_absent(db_session: AsyncSession) -> None:
    """No valuation on file → the appraised line is manual/override-able (graceful)."""
    company = await _company(db_session, "acme")
    loan_file = await _purchase_file(db_session, company, valuation=None)

    calc = await build_ltv_calculation(db_session, loan_file=loan_file)
    appraised = next(i for i in calc.value_items if i.key == LTV_APPRAISED_VALUE)
    assert appraised.auto_amount is None
    assert appraised.source == "manual"
    # The basis falls back to the purchase price (the only positive value).
    assert calc.value_basis == Decimal("190000")


async def test_effective_limit_purchase_vs_cash_out(db_session: AsyncSession) -> None:
    """The limit varies by loan purpose: purchase 97 vs cash-out 80."""
    company = await _company(db_session, "acme")
    purchase = await _purchase_file(db_session, company)
    purchase_calc = await build_ltv_calculation(db_session, loan_file=purchase)
    assert purchase_calc.limit.ltv_max == Decimal("97")
    assert purchase_calc.limit.purpose_basis == "purchase"
    assert purchase_calc.limit.source == "program_default"

    # A cash-out refinance → the stricter 80 limit, against the appraised value.
    refi = await create_loan_file(
        db_session,
        company_id=company.id,
        loan_program=LoanProgram.CONVENTIONAL,
        loan_purpose=LoanPurpose.REFINANCE,
    )
    refi.loan_amount = Decimal("170000")
    refi.refinance_type = RefinanceType.CASH_OUT
    db_session.add(Property(loan_file_id=refi.id, valuation_amount=Decimal("200000")))
    await db_session.flush()

    refi_calc = await build_ltv_calculation(db_session, loan_file=refi)
    assert refi_calc.purpose == "cash_out_refinance"
    assert refi_calc.value_basis == Decimal("200000")  # appraised, not a price
    assert refi_calc.ltv == Decimal("85.00")  # 170000 / 200000
    assert refi_calc.limit.ltv_max == Decimal("80")
    assert refi_calc.limit.purpose_basis == "cash_out"
    assert refi_calc.limit.status == "over"  # 85 > 80


async def test_override_recomputes_and_is_audited(db_session: AsyncSession) -> None:
    """Overriding the appraised value recomputes the LTV and is audited."""
    company = await _company(db_session, "acme")
    user = await _user(db_session, company)
    loan_file = await _purchase_file(db_session, company, valuation=None)

    # Correct the appraised value to 200k → basis becomes lesser-of(190k, 200k)=190k
    # (unchanged here), but the override is recorded; then drop the price too.
    calc = await set_ltv_override(
        db_session,
        loan_file=loan_file,
        field_key=LTV_APPRAISED_VALUE,
        data=LtvOverrideInput(amount=Decimal("185000"), note="Per appraisal report"),
        actor_user_id=user.id,
    )
    appraised = next(i for i in calc.value_items if i.key == LTV_APPRAISED_VALUE)
    assert appraised.override_amount == Decimal("185000")
    assert appraised.overridden is True
    # basis now lesser-of(price 190k, appraised 185k) = 185k → LTV 180000/185000.
    assert calc.value_basis == Decimal("185000")
    assert calc.ltv == Decimal("97.30")

    logs = (
        (
            await db_session.execute(
                select(ActivityLog).where(
                    ActivityLog.loan_file_id == loan_file.id,
                    ActivityLog.activity_type == ActivityType.LTV_OVERRIDDEN,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(logs) == 1
    assert logs[0].detail["field_key"] == LTV_APPRAISED_VALUE
    assert logs[0].detail["to"] == "185000"


async def test_heloc_credit_limit_override_drives_hcltv(db_session: AsyncSession) -> None:
    """Overriding the HELOC credit limit lifts HCLTV above CLTV (the subtlety, end-to-end)."""
    company = await _company(db_session, "acme")
    user = await _user(db_session, company)
    loan_file = await _purchase_file(
        db_session, company, loan_amount=Decimal("160000"), purchase_price=Decimal("200000")
    )

    calc = await set_ltv_override(
        db_session,
        loan_file=loan_file,
        field_key=LTV_HELOC_LIMIT,
        data=LtvOverrideInput(amount=Decimal("40000")),
        actor_user_id=user.id,
    )
    assert calc.cltv == Decimal("80.00")  # HELOC drawn 0
    assert calc.hcltv == Decimal("100.00")  # full $40k line counts


async def test_override_clears_back_to_auto(db_session: AsyncSession) -> None:
    company = await _company(db_session, "acme")
    user = await _user(db_session, company)
    loan_file = await _purchase_file(db_session, company)

    await set_ltv_override(
        db_session,
        loan_file=loan_file,
        field_key=LTV_APPRAISED_VALUE,
        data=LtvOverrideInput(amount=Decimal("150000")),
        actor_user_id=user.id,
    )
    cleared = await clear_ltv_override(
        db_session, loan_file=loan_file, field_key=LTV_APPRAISED_VALUE, actor_user_id=user.id
    )
    appraised = next(i for i in cleared.value_items if i.key == LTV_APPRAISED_VALUE)
    assert appraised.overridden is False
    assert appraised.auto_amount == Decimal("200000")


async def test_unknown_field_rejected(db_session: AsyncSession) -> None:
    company = await _company(db_session, "acme")
    user = await _user(db_session, company)
    loan_file = await _purchase_file(db_session, company)
    try:
        await set_ltv_override(
            db_session,
            loan_file=loan_file,
            field_key="ltv.nonsense",
            data=LtvOverrideInput(amount=Decimal("1")),
            actor_user_id=user.id,
        )
    except UnknownLtvFieldError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected UnknownLtvFieldError")


async def test_unresolved_findings_alert(db_session: AsyncSession) -> None:
    """An open in-scope finding raises the unresolved-findings alert (LP-75 coupling)."""
    company = await _company(db_session, "acme")
    loan_file = await _purchase_file(db_session, company)
    assert (
        await build_ltv_calculation(db_session, loan_file=loan_file)
    ).findings.unresolved is False

    db_session.add(
        Finding(
            loan_file_id=loan_file.id,
            rule_id="cross_source.property.value_discrepancy",
            origin=FindingOrigin.AI_CROSS_SOURCE,
            confidence=0.9,
            status=FindingStatus.YELLOW,
            category=FindingCategory.PROPERTY,
            message="Appraised value differs from the sales contract.",
        )
    )
    await db_session.flush()

    calc = await build_ltv_calculation(db_session, loan_file=loan_file)
    assert calc.findings.unresolved is True
    assert calc.findings.open_in_scope_count == 1


async def test_recompute_on_structured_data_change(db_session: AsyncSession) -> None:
    """A corrected appraised value (a structured-data change) recomputes the LTV.

    LP-77 is a recompute consumer: the calculation reads the structured data live,
    so a change an applied finding makes (here, the property valuation) flows into
    the next calculation.
    """
    company = await _company(db_session, "acme")
    loan_file = await _purchase_file(db_session, company, purchase_price=None)
    before = await build_ltv_calculation(db_session, loan_file=loan_file)
    assert before.ltv == Decimal("90.00")  # 180000 / 200000 (appraised basis)

    # Simulate the structured-data change an applied finding produces.
    prop = (
        await db_session.execute(select(Property).where(Property.loan_file_id == loan_file.id))
    ).scalar_one()
    prop.valuation_amount = Decimal("180000")
    await db_session.flush()

    after = await build_ltv_calculation(db_session, loan_file=loan_file)
    assert after.value_basis == Decimal("180000")
    assert after.ltv == Decimal("100.00")  # 180000 / 180000 — recomputed
    assert after.ltv > before.ltv


async def test_tenant_scoped(db_session: AsyncSession) -> None:
    company = await _company(db_session, "acme")
    other = await _company(db_session, "other")
    mine = await _purchase_file(db_session, company, loan_amount=Decimal("180000"))
    theirs = await _purchase_file(db_session, other, loan_amount=Decimal("99999"))

    calc = await build_ltv_calculation(db_session, loan_file=mine)
    first = next(i for i in calc.loan_items if i.key == "ltv.first_loan")
    assert first.auto_amount == Decimal("180000")
    assert theirs.id != mine.id

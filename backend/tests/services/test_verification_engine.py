"""The verification-engine service (LP-74) — per-file run, persisted findings.

Exercises the DB-facing half end to end: build facts from a seeded file, resolve
the effective rule set (program + lender overlay), evaluate, and persist findings
into the **shared** model marked ``origin=deterministic_rule``. Covers the
overlay effect on a real run, per-file/tenant scoping, the two-generator shape
(the model is not engine-exclusive), and no regression to the Finding model.
"""

from decimal import Decimal

from app.models import (
    Borrower,
    Company,
    Finding,
    FindingCategory,
    FindingOrigin,
    FindingStatus,
    Lender,
    LoanProgram,
    StatedAsset,
    StatedIncomeItem,
    StatedLiability,
    VerificationStatus,
)
from app.services.loan_files import create_loan_file
from app.services.verification_engine import run_verification
from app.verification.overlays.samples import SAMPLE_OVERLAY_LENDER_SLUG
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _company(db: AsyncSession, slug: str) -> Company:
    company = Company(name=slug.title(), slug=slug)
    db.add(company)
    await db.flush()
    return company


async def _seed_file(
    db: AsyncSession,
    company: Company,
    *,
    lender_id=None,
    income: Decimal = Decimal("10000"),
    monthly_payment: Decimal = Decimal("4800"),
    asset_value: Decimal = Decimal("5000"),
):
    """A Conventional file whose seeded data yields a back-end DTI of 48%."""
    loan_file = await create_loan_file(
        db,
        company_id=company.id,
        loan_program=LoanProgram.CONVENTIONAL,
        lender_id=lender_id,
    )
    borrower = Borrower(
        loan_file_id=loan_file.id,
        first_name="Pat",
        last_name="Borrower",
        is_primary=True,
    )
    db.add(borrower)
    await db.flush()
    db.add(
        StatedIncomeItem(
            borrower_id=borrower.id,
            monthly_amount=income,
            employment_income=True,
        )
    )
    db.add(
        StatedLiability(
            loan_file_id=loan_file.id,
            liability_type="Installment",
            monthly_payment=monthly_payment,
        )
    )
    db.add(StatedAsset(loan_file_id=loan_file.id, asset_type="CheckingAccount", value=asset_value))
    await db.flush()
    return loan_file


async def _findings(db: AsyncSession, loan_file_id) -> dict[str, Finding]:
    rows = (
        (await db.execute(select(Finding).where(Finding.loan_file_id == loan_file_id)))
        .scalars()
        .all()
    )
    return {f.rule_id: f for f in rows}


async def test_run_without_overlay_passes_default_dti(db_session: AsyncSession) -> None:
    """48% DTI passes the investor default of 50 → a green finding."""
    company = await _company(db_session, "acme")
    loan_file = await _seed_file(db_session, company)

    run = await run_verification(db_session, loan_file=loan_file, company_id=company.id)

    assert run.status is VerificationStatus.COMPLETED
    assert run.completed_at is not None
    findings = await _findings(db_session, loan_file.id)
    assert findings["conv.dti.back_end_max"].status is FindingStatus.GREEN
    # FHA rule never evaluated for a Conventional file.
    assert "fha.dti.back_end_max" not in findings


async def test_findings_carry_deterministic_rule_origin_and_uniform_shape(
    db_session: AsyncSession,
) -> None:
    """Engine findings are marked deterministic_rule and emit the uniform shape."""
    company = await _company(db_session, "acme")
    loan_file = await _seed_file(db_session, company)

    await run_verification(db_session, loan_file=loan_file, company_id=company.id)

    dti = (await _findings(db_session, loan_file.id))["conv.dti.back_end_max"]
    assert dti.origin is FindingOrigin.DETERMINISTIC_RULE
    assert dti.category is FindingCategory.INCOME
    # Uniform shape: observed value, condition, source citation, reasoning.
    assert dti.details["observed"] == "48.00"
    assert dti.details["condition"] == {"op": "<=", "value": "50", "unit": "percent"}
    assert dti.details["reads"] == ["dti.back_end_pct"]
    assert dti.details["source"]["type"] == "investor_guide"
    assert "reasoning" in dti.details


async def test_overlay_run_fails_dti_and_adds_custom_rule(db_session: AsyncSession) -> None:
    """With the sample lender overlay: DTI fails at 45 and the custom rule runs."""
    company = await _company(db_session, "acme")
    lender = Lender(
        company_id=company.id,
        name="Sample Overlay Bank",
        slug=SAMPLE_OVERLAY_LENDER_SLUG,
        supported_programs=["conventional"],
    )
    db_session.add(lender)
    await db_session.flush()
    loan_file = await _seed_file(db_session, company, lender_id=lender.id)

    run = await run_verification(db_session, loan_file=loan_file, company_id=company.id)

    findings = await _findings(db_session, loan_file.id)
    # The overlay-patched DTI (45) now fails where the default (50) passed.
    dti = findings["conv.dti.back_end_max"]
    assert dti.status is FindingStatus.RED
    assert dti.details["condition"]["value"] == "45"
    assert dti.details["overlay_applied"] == SAMPLE_OVERLAY_LENDER_SLUG
    # The custom reserves rule was added and evaluated.
    custom_id = f"{SAMPLE_OVERLAY_LENDER_SLUG}.reserves.min_months"
    assert custom_id in findings
    assert findings[custom_id].status is FindingStatus.YELLOW
    assert run.red_count == 1
    assert run.yellow_count == 1


async def test_run_is_tenant_scoped(db_session: AsyncSession) -> None:
    """A run for a file outside the requesting company is rejected."""
    owner = await _company(db_session, "owner")
    other = await _company(db_session, "intruder")
    loan_file = await _seed_file(db_session, owner)

    try:
        await run_verification(db_session, loan_file=loan_file, company_id=other.id)
    except ValueError:
        pass
    else:  # pragma: no cover - the call must raise
        raise AssertionError("expected a tenant-scope ValueError")


async def test_shared_model_is_not_engine_exclusive(db_session: AsyncSession) -> None:
    """An AI-origin finding coexists in the same model (two-generator seam)."""
    company = await _company(db_session, "acme")
    loan_file = await _seed_file(db_session, company)
    await run_verification(db_session, loan_file=loan_file, company_id=company.id)

    # Simulate the LP-78 AI cross-source generator feeding the SAME model.
    ai_finding = Finding(
        loan_file_id=loan_file.id,
        rule_id="cross_source.income.stated_vs_verified",
        origin=FindingOrigin.AI_CROSS_SOURCE,
        status=FindingStatus.YELLOW,
        category=FindingCategory.CROSS_SOURCE,
        message="Stated income differs from verified income.",
    )
    db_session.add(ai_finding)
    await db_session.flush()

    rows = (
        (await db_session.execute(select(Finding).where(Finding.loan_file_id == loan_file.id)))
        .scalars()
        .all()
    )
    origins = {f.origin for f in rows}
    assert FindingOrigin.DETERMINISTIC_RULE in origins
    assert FindingOrigin.AI_CROSS_SOURCE in origins


async def test_run_links_findings_to_the_verification(db_session: AsyncSession) -> None:
    """The run groups the findings it produced (per-file run)."""
    company = await _company(db_session, "acme")
    loan_file = await _seed_file(db_session, company)

    run = await run_verification(db_session, loan_file=loan_file, company_id=company.id)

    linked = (
        (await db_session.execute(select(Finding).where(Finding.verification_id == run.id)))
        .scalars()
        .all()
    )
    assert linked
    assert all(f.origin is FindingOrigin.DETERMINISTIC_RULE for f in linked)
    # Counts on the run match the persisted greens (no overlay → all green here).
    assert run.green_count == len(linked)


async def test_default_finding_origin_is_deterministic_rule(db_session: AsyncSession) -> None:
    """No-regression: a plain Finding still constructs and defaults its origin."""
    company = await _company(db_session, "acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    finding = Finding(
        loan_file_id=loan_file.id,
        rule_id="income.paystub_recency",
        status=FindingStatus.YELLOW,
        category=FindingCategory.INCOME,
        message="Pay stub older than 30 days.",
    )
    db_session.add(finding)
    await db_session.flush()
    await db_session.refresh(finding)

    assert finding.origin is FindingOrigin.DETERMINISTIC_RULE

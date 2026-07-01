"""LP-97 — the "View fix" dry-run impact preview.

The core guardrails: the preview computes the FULL itemized before/after WITHOUT persisting, and
it MATCHES the real apply (it reuses the same apply→recompute in a rolled-back savepoint — one
source of truth, no parallel computation to diverge).
"""

from decimal import Decimal
from uuid import UUID

from app.models import (
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
from app.services.finding_impact import has_apply_spec, preview_finding_apply
from app.services.finding_resolution import apply_finding
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


async def _file_with_debt(db: AsyncSession, company: Company):
    """A file with income + one debt, so a DTI exists to move. $10k income, $2k debt, P&I 833.33."""
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
    return loan_file


async def _undisclosed_finding(db: AsyncSession, loan_file, *, amount: str = "500") -> Finding:
    finding = Finding(
        loan_file_id=loan_file.id,
        rule_id="xsrc.liability.undisclosed_debt",
        origin=FindingOrigin.DETERMINISTIC_RULE,
        status=FindingStatus.RED,
        category=FindingCategory.CREDIT,
        message="Undisclosed obligation in the documents.",
        confidence=1.0,
        resolution_status=FindingResolutionStatus.OPEN,
        details={
            "apply": {
                "action": "add_liability",
                "liability_type": "Installment",
                "monthly_payment": amount,
                "holder_name": "Auto loan",
            }
        },
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


# --- has_apply_spec: only apply-spec findings get View fix --------------------


async def test_has_apply_spec_gates_view_fix(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    loan_file = await _file_with_debt(db_session, company)
    with_spec = await _undisclosed_finding(db_session, loan_file)
    assert has_apply_spec(with_spec) is True

    without = Finding(
        loan_file_id=loan_file.id,
        rule_id="cross_source.identity_discrepancy",
        origin=FindingOrigin.AI_CROSS_SOURCE,
        status=FindingStatus.YELLOW,
        category=FindingCategory.CROSS_SOURCE,
        message="Name mismatch.",
        confidence=0.8,
        resolution_status=FindingResolutionStatus.OPEN,
        details={"reasoning": "…"},
    )
    assert has_apply_spec(without) is False


# --- The dry-run: itemized before/after, persists nothing --------------------


async def test_preview_is_itemized_before_after(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    user = await _user(db_session, company)
    loan_file = await _file_with_debt(db_session, company)
    finding = await _undisclosed_finding(db_session, loan_file, amount="500")

    preview = await preview_finding_apply(
        db_session, finding=finding, loan_file=loan_file, actor_user_id=user.id
    )

    assert "dti" in preview.affects
    assert preview.dti_before is not None and preview.dti_after is not None
    # Monthly debts move by the new $500 line; the back-end DTI recomputes up.
    assert preview.dti_after.monthly_debts - preview.dti_before.monthly_debts == Decimal("500")
    assert preview.dti_after.back_end_dti > preview.dti_before.back_end_dti
    # The after itemization carries a NEW debt line the before does not (the highlightable one).
    before_keys = {i.key for i in preview.dti_before.debt_items}
    after_keys = {i.key for i in preview.dti_after.debt_items}
    assert len(after_keys - before_keys) == 1
    # Income is unchanged (this apply only touches debts).
    assert preview.dti_after.gross_monthly_income == preview.dti_before.gross_monthly_income
    assert "$500" in preview.summary


async def test_preview_persists_nothing(db_session: AsyncSession) -> None:
    """A DRY-RUN: the file, its DTI, its liabilities, and the finding are unchanged after preview."""
    company = await _company(db_session)
    user = await _user(db_session, company)
    loan_file = await _file_with_debt(db_session, company)
    finding = await _undisclosed_finding(db_session, loan_file)

    dti_before = await build_dti_calculation(db_session, loan_file=loan_file)
    libs_before = len(await _live_liabilities(db_session, loan_file.id))

    await preview_finding_apply(
        db_session, finding=finding, loan_file=loan_file, actor_user_id=user.id
    )

    # Nothing persisted: no new liability, the DTI is unchanged, the finding is still OPEN.
    assert len(await _live_liabilities(db_session, loan_file.id)) == libs_before
    dti_after = await build_dti_calculation(db_session, loan_file=loan_file)
    assert dti_after.back_end_dti == dti_before.back_end_dti
    await db_session.refresh(finding)
    assert finding.resolution_status is FindingResolutionStatus.OPEN
    assert finding.applied_record is None


# --- The preview MATCHES the real apply (one source of truth) -----------------


async def test_preview_matches_the_real_apply(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    user = await _user(db_session, company)
    loan_file = await _file_with_debt(db_session, company)
    finding = await _undisclosed_finding(db_session, loan_file, amount="500")

    # What the dry-run PREDICTS.
    preview = await preview_finding_apply(
        db_session, finding=finding, loan_file=loan_file, actor_user_id=user.id
    )
    predicted_debts = preview.dti_after.monthly_debts
    predicted_dti = preview.dti_after.back_end_dti

    # Now REALLY apply + recompute — the result must equal the prediction (no divergence).
    await apply_finding(db_session, finding=finding, loan_file=loan_file, actor_user_id=user.id)
    actual = await build_dti_calculation(db_session, loan_file=loan_file)
    assert actual.monthly_debts == predicted_debts
    assert actual.back_end_dti == predicted_dti
    # The real apply recorded the reversible before-state for LP-98's Undo.
    assert finding.resolution_status is FindingResolutionStatus.APPLIED
    assert finding.applied_record is not None
    assert finding.applied_record.get("liability_id")  # enough to reverse (delete it)


async def test_preview_reflects_a_limit_crossing_status_change(db_session: AsyncSession) -> None:
    """A big enough new debt flips the back-end DTI over its limit — the consequential preview bit."""
    company = await _company(db_session)
    user = await _user(db_session, company)
    loan_file = await _file_with_debt(db_session, company)
    # $6000/mo new debt → (833.33 + 2000 + 6000) / 10000 = 88% → well over the cap.
    finding = await _undisclosed_finding(db_session, loan_file, amount="6000")

    preview = await preview_finding_apply(
        db_session, finding=finding, loan_file=loan_file, actor_user_id=user.id
    )
    assert preview.dti_before.limit.status == "pass"
    assert preview.dti_after.limit.status == "over"  # the highlighted status crossing

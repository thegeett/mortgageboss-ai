"""LP-578 — a preview a processor approved must be the one that gets applied.

THE WINDOW. The preview is computed at T; the processor reads it and confirms at T+30s. In between,
another processor can edit the target liability, add a second one from the same servicer (turning a
clean target into an ambiguous one the apply would refuse), soft-delete the row, or change an
override. Applying anyway writes something other than the before/after that was approved — and Apply
moves an underwriting number, so "close enough" is not good enough.

The guard is a FINGERPRINT of the state the preview was computed against, handed back on confirm.
Deliberately not a timestamp: a file edited and edited back is unchanged and must not be refused.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from app.models import Borrower, Company, LoanProgram, StatedIncomeItem, StatedLiability
from app.models.finding import Finding, FindingCategory, FindingResolutionStatus, FindingStatus
from app.services.dti import build_dti_calculation
from app.services.finding_impact import apply_fingerprint
from app.services.loan_files import create_loan_file
from app.services.ltv import build_ltv_calculation
from sqlalchemy.ext.asyncio import AsyncSession
from tests.services.test_dti import _seed_housing


async def _file(db: AsyncSession, slug: str):
    company = Company(name=slug.title(), slug=f"{slug}-{uuid4().hex[:6]}")
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
    db.add(
        StatedLiability(
            loan_file_id=loan_file.id,
            liability_type="MortgageLoan",
            monthly_payment=Decimal("3000"),
            holder_name="UNITED WHSLE MORT",
        )
    )
    await db.flush()
    await _seed_housing(db, loan_file)
    return loan_file


async def _finding(db: AsyncSession, loan_file) -> Finding:
    finding = Finding(
        loan_file_id=loan_file.id,
        rule_id="DT-8",
        message="a refinanced lien may still be counted",
        subject_key="lia1",
        load_bearing_tags=[],
        status=FindingStatus.YELLOW,
        category=FindingCategory.CREDIT,
        confidence=1.0,
        details={
            "apply": {
                "action": "exclude_liability_paid_off",
                "holder_name": "UNITED WHSLE MORT",
            }
        },
    )
    db.add(finding)
    await db.flush()
    return finding


async def _fingerprint(db: AsyncSession, finding: Finding, loan_file) -> str:
    return apply_fingerprint(
        finding,
        await build_dti_calculation(db, loan_file=loan_file),
        await build_ltv_calculation(db, loan_file=loan_file),
    )


async def test_an_unchanged_file_keeps_its_fingerprint(db_session: AsyncSession) -> None:
    """The common path. Nothing moved, so confirming applies exactly what was previewed."""
    loan_file = await _file(db_session, "stable")
    finding = await _finding(db_session, loan_file)

    first = await _fingerprint(db_session, finding, loan_file)
    second = await _fingerprint(db_session, finding, loan_file)

    assert first == second


async def test_editing_the_target_payment_changes_it(db_session: AsyncSession) -> None:
    """The figure the before/after was built from moved."""
    loan_file = await _file(db_session, "edited")
    finding = await _finding(db_session, loan_file)
    before = await _fingerprint(db_session, finding, loan_file)

    liability = (
        (await db_session.execute(__import__("sqlalchemy").select(StatedLiability)))
        .scalars()
        .first()
    )
    assert liability is not None
    liability.monthly_payment = Decimal("3100")
    await db_session.flush()

    assert await _fingerprint(db_session, finding, loan_file) != before


async def test_a_second_liability_from_the_same_holder_changes_it(
    db_session: AsyncSession,
) -> None:
    """THE CASE THAT MATTERS MOST. This turns a clean Apply target into an AMBIGUOUS one — the
    action would decline, so the approved before/after becomes unreachable. A guard that only
    watched the target row's own fields would miss this; watching the calculators' line items
    catches it, because a new debt line appears."""
    loan_file = await _file(db_session, "ambiguous")
    finding = await _finding(db_session, loan_file)
    before = await _fingerprint(db_session, finding, loan_file)

    db_session.add(
        StatedLiability(
            loan_file_id=loan_file.id,
            liability_type="MortgageLoan",
            monthly_payment=Decimal("310"),
            holder_name="UNITED WHSLE MORT",
        )
    )
    await db_session.flush()

    assert await _fingerprint(db_session, finding, loan_file) != before


async def test_renaming_the_holder_changes_it(db_session: AsyncSession) -> None:
    """A rename does NOT move any total, so a fingerprint over the ratios alone would miss it — and
    it is precisely what breaks a holder-targeted Apply. The line LABEL carries the holder, which is
    why the items are hashed rather than the headline figures."""
    loan_file = await _file(db_session, "renamed")
    finding = await _finding(db_session, loan_file)
    before = await _fingerprint(db_session, finding, loan_file)

    liability = (
        (await db_session.execute(__import__("sqlalchemy").select(StatedLiability)))
        .scalars()
        .first()
    )
    assert liability is not None
    liability.holder_name = "UWM LLC"
    await db_session.flush()

    assert await _fingerprint(db_session, finding, loan_file) != before


async def test_applying_the_finding_changes_it(db_session: AsyncSession) -> None:
    """Applying twice is the other way the outcome diverges from the preview, so the finding's own
    resolution state is part of the material."""
    loan_file = await _file(db_session, "applied")
    finding = await _finding(db_session, loan_file)
    before = await _fingerprint(db_session, finding, loan_file)

    finding.resolution_status = FindingResolutionStatus.APPLIED
    await db_session.flush()

    assert await _fingerprint(db_session, finding, loan_file) != before


async def test_an_edit_and_its_reversal_leave_it_unchanged(db_session: AsyncSession) -> None:
    """NOT A TIMESTAMP, and this is the test that pins the difference. A file edited and edited back
    describes the same apply, and refusing it would train processors to ignore the warning."""
    loan_file = await _file(db_session, "reverted")
    finding = await _finding(db_session, loan_file)
    before = await _fingerprint(db_session, finding, loan_file)

    liability = (
        (await db_session.execute(__import__("sqlalchemy").select(StatedLiability)))
        .scalars()
        .first()
    )
    assert liability is not None
    liability.monthly_payment = Decimal("3100")
    await db_session.flush()
    liability.monthly_payment = Decimal("3000")
    await db_session.flush()

    assert await _fingerprint(db_session, finding, loan_file) == before

"""LP-579 — a needs_review finding must actually APPLY, not just show a button.

WHAT SHIPPED BROKEN. LP-576 widened the ENGINE so a `needs_review` evaluation carries an apply block
— DT-6 and DT-8 can never fire by design, so without it the remediation those rules exist to offer
had no button at all. The write path, one layer down, still admitted only `OPEN`.

So the button appeared and refused itself: clicking Apply produced "Couldn't compute the impact
preview", because the preview runs the real `apply_finding` and got a `CannotApplyError`.

WHY THE LP-576 TESTS MISSED IT. Every one of them asserted `evaluation.apply` was populated — the
ENGINE's output. Not one applied a needs_review finding. The button appearing and the button working
are different claims, and I tested only the first. These tests apply for real.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from app.models import Borrower, Company, LoanProgram, StatedIncomeItem, StatedLiability
from app.models.finding import (
    EvaluationOutcome,
    Finding,
    FindingCategory,
    FindingResolutionStatus,
    FindingStatus,
)
from app.services.finding_impact import preview_finding_apply
from app.services.finding_resolution import CannotApplyError, apply_finding
from app.services.loan_files import create_loan_file
from sqlalchemy.ext.asyncio import AsyncSession
from tests.services.test_dti import _seed_housing


async def _file(db: AsyncSession, slug: str):
    company = Company(name=slug.title(), slug=f"{slug}-{uuid4().hex[:6]}")
    db.add(company)
    await db.flush()
    from app.core.security import hash_password
    from app.models import User, UserRole

    user = User(
        company_id=company.id,
        email=f"p-{uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("x"),
        first_name="Pat",
        last_name="P",
        role=UserRole.PROCESSOR,
    )
    db.add(user)
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
    return loan_file, user.id


async def _finding(db: AsyncSession, loan_file, outcome: EvaluationOutcome) -> Finding:
    finding = Finding(
        loan_file_id=loan_file.id,
        rule_id="DT-8",
        message="a refinanced lien may still be counted",
        subject_key="lia1",
        load_bearing_tags=[],
        status=FindingStatus.YELLOW,
        category=FindingCategory.CREDIT,
        confidence=1.0,
        evaluation_outcome=outcome,
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


async def test_a_needs_review_finding_applies(db_session: AsyncSession) -> None:
    """THE HEADLINE — DT-8's whole purpose. It can never fire, so if needs_review cannot apply, the
    rule's remediation is unreachable and the DTI never moves."""
    loan_file, actor = await _file(db_session, "needsreview")
    finding = await _finding(db_session, loan_file, EvaluationOutcome.NEEDS_REVIEW)

    await apply_finding(db_session, finding=finding, loan_file=loan_file, actor_user_id=actor)

    assert finding.resolution_status is FindingResolutionStatus.APPLIED


async def test_the_preview_of_a_needs_review_finding_computes(db_session: AsyncSession) -> None:
    """THE EXACT SYMPTOM REPORTED: "Couldn't compute the impact preview." The preview runs the real
    `apply_finding`, so the write-path guard refusing needs_review broke the preview too — the
    dialog whose job is to explain the change could not compute one."""
    loan_file, actor = await _file(db_session, "preview")
    finding = await _finding(db_session, loan_file, EvaluationOutcome.NEEDS_REVIEW)

    preview = await preview_finding_apply(
        db_session, finding=finding, loan_file=loan_file, actor_user_id=actor
    )

    assert preview.dti_before is not None and preview.dti_after is not None
    assert preview.dti_before.monthly_debts == Decimal("3000.00")
    assert preview.dti_after.monthly_debts == Decimal("0.00")
    assert "dti" in preview.affects


async def test_an_open_finding_still_applies(db_session: AsyncSession) -> None:
    """The original path is untouched — this is a widening, not a replacement."""
    loan_file, actor = await _file(db_session, "open")
    finding = await _finding(db_session, loan_file, EvaluationOutcome.OPEN)

    await apply_finding(db_session, finding=finding, loan_file=loan_file, actor_user_id=actor)

    assert finding.resolution_status is FindingResolutionStatus.APPLIED


@pytest.mark.parametrize("outcome", [EvaluationOutcome.SATISFIED, EvaluationOutcome.COULDNT_CHECK])
async def test_a_passing_or_abstaining_finding_is_still_refused(
    db_session: AsyncSession, outcome: EvaluationOutcome
) -> None:
    """LP-564'S FINDING MUST STAY FIXED. Widening to needs_review must not readmit the other two:
    SATISFIED has nothing to remediate, and COULDNT_CHECK is an ABSTENTION — applying off "I could
    not tell" is the CR-1 trap that inserted a duplicate liability and inflated a DTI."""
    loan_file, actor = await _file(db_session, f"refused-{outcome.value}")
    finding = await _finding(db_session, loan_file, outcome)

    with pytest.raises(CannotApplyError):
        await apply_finding(db_session, finding=finding, loan_file=loan_file, actor_user_id=actor)

"""Tests for the verification ↔ findings linkage and its cascade subtlety (LP-18).

The critical design point: findings *reference* the run that produced them but
**belong to the loan file**, so deleting a run must PRESERVE its findings. The FK
on ``findings.verification_id`` is ``ondelete=SET NULL`` (ADR-064). These tests
prove:

  * ``verification.findings`` / ``finding.verification`` navigate the link.
  * Hard-deleting a run nulls its findings' ``verification_id`` and keeps the
    findings (SET NULL, not CASCADE).
  * By contrast, deleting the *loan file* DOES remove its findings (they are
    owned children of the file) — the distinction that motivates the design.

Uses the transaction-rollback ``db_session`` fixture from LP-10.
"""

from app.models import (
    Company,
    Finding,
    FindingCategory,
    FindingStatus,
    LoanFile,
    Verification,
    VerificationTrigger,
)
from app.services.loan_files import create_loan_file
from app.services.verifications import create_verification_run
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


async def _make_loan_file(db_session: AsyncSession, slug: str) -> LoanFile:
    company = Company(name=slug.title(), slug=slug)
    db_session.add(company)
    await db_session.flush()
    return await create_loan_file(db_session, company_id=company.id)


async def _add_finding(
    db_session: AsyncSession,
    loan_file: LoanFile,
    *,
    verification: Verification | None,
    rule_id: str = "income.paystub_recency",
) -> Finding:
    finding = Finding(
        loan_file_id=loan_file.id,
        verification_id=verification.id if verification is not None else None,
        rule_id=rule_id,
        status=FindingStatus.YELLOW,
        category=FindingCategory.INCOME,
        message="Pay stub is older than 30 days.",
    )
    db_session.add(finding)
    await db_session.flush()
    return finding


async def test_run_and_finding_navigate_the_link(db_session: AsyncSession) -> None:
    """verification.findings returns its findings; finding.verification returns the run."""
    loan_file = await _make_loan_file(db_session, "acme")
    run = await create_verification_run(
        db_session, loan_file_id=loan_file.id, trigger=VerificationTrigger.MANUAL
    )
    f1 = await _add_finding(db_session, loan_file, verification=run, rule_id="income.a")
    f2 = await _add_finding(db_session, loan_file, verification=run, rule_id="assets.b")

    run_stmt = (
        select(Verification)
        .where(Verification.id == run.id)
        .options(selectinload(Verification.findings))
    )
    loaded_run = (await db_session.scalars(run_stmt)).one()
    assert {f.id for f in loaded_run.findings} == {f1.id, f2.id}

    finding_stmt = (
        select(Finding).where(Finding.id == f1.id).options(selectinload(Finding.verification))
    )
    loaded_finding = (await db_session.scalars(finding_stmt)).one()
    assert loaded_finding.verification is not None
    assert loaded_finding.verification.id == run.id


async def test_deleting_run_preserves_findings_and_nulls_reference(
    db_session: AsyncSession,
) -> None:
    """CRITICAL: hard-deleting a run SET NULLs its findings, never deletes them.

    Findings belong to the loan file, not the run (ADR-064), so the run's
    deletion must leave them intact with ``verification_id = None``.
    """
    loan_file = await _make_loan_file(db_session, "acme")
    run = await create_verification_run(
        db_session, loan_file_id=loan_file.id, trigger=VerificationTrigger.MANUAL
    )
    f1 = await _add_finding(db_session, loan_file, verification=run, rule_id="income.a")
    f2 = await _add_finding(db_session, loan_file, verification=run, rule_id="assets.b")
    # Capture ids before expiring (accessing attributes on expired objects would
    # trigger a lazy reload).
    finding_ids = {f1.id, f2.id}
    run_id = run.id

    # Hard-delete the run (not a soft delete).
    await db_session.delete(run)
    await db_session.flush()
    # Expire so the findings are re-read from the DB (the SET NULL happened there).
    db_session.expire_all()

    surviving = (await db_session.scalars(select(Finding).where(Finding.id.in_(finding_ids)))).all()
    assert {f.id for f in surviving} == finding_ids  # both still exist
    assert all(f.verification_id is None for f in surviving)  # reference nulled

    # The run is really gone.
    assert await db_session.scalar(select(Verification).where(Verification.id == run_id)) is None


async def test_deleting_loan_file_does_remove_findings(db_session: AsyncSession) -> None:
    """Contrast: findings ARE owned by the loan file, so deleting it removes them."""
    loan_file = await _make_loan_file(db_session, "acme")
    run = await create_verification_run(
        db_session, loan_file_id=loan_file.id, trigger=VerificationTrigger.MANUAL
    )
    finding = await _add_finding(db_session, loan_file, verification=run)
    finding_id = finding.id
    run_id = run.id

    await db_session.delete(loan_file)
    await db_session.flush()
    db_session.expire_all()

    # The finding (and the run) went with the file.
    assert await db_session.scalar(select(Finding).where(Finding.id == finding_id)) is None
    assert await db_session.scalar(select(Verification).where(Verification.id == run_id)) is None

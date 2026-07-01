"""LP-94 — re-run reconciliation: merge currently-detected, DROP no-longer-detected (open).

The re-run compares fresh detections against the file's existing findings by LP-93's normalized
identity and reconciles them into five cases:

1. still-detected OPEN → MERGE (keep the existing row — id/notes/resolution preserved)
2. no-longer-detected OPEN → DROP (removed — reverses LP-81's implicit keep-and-recreate)
3. still-detected RESOLVED → resolution preserved
4. no-longer-detected RESOLVED → RETAINED (a completed action — Undo/audit depend on it)
5. genuinely-new → ADDED

Plus: an unchanged re-run (nothing changed) drops nothing; the comparison is tenant-scoped.
"""

from uuid import UUID

from app.models import (
    Borrower,
    Company,
    Finding,
    FindingResolutionStatus,
    LoanFile,
    LoanProgram,
    User,
    UserRole,
)
from app.models.base import utcnow
from app.models.verification import VerificationTrigger
from app.services.cross_source_deterministic import run_cross_source_deterministic
from app.services.finding_resolution import override_finding
from app.services.loan_files import create_loan_file
from app.services.verifications import create_verification_run
from app.verification.cross_source import CrossSourceFacts
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_EMP_A = "Thermofisher Life Science - PPD Development LP."
_EMP_B = "Swad Mania LLC"
_STATED = ("Acme Payroll Co",)  # a different stated employer → documented ones don't match


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


async def _file(db: AsyncSession, company: Company) -> LoanFile:
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    db.add(Borrower(loan_file_id=loan_file.id, first_name="Mahesh", last_name="C", is_primary=True))
    await db.flush()
    return loan_file


async def _run(db: AsyncSession, loan_file: LoanFile, documented: tuple[str, ...]) -> None:
    facts = CrossSourceFacts(
        stated_employers=_STATED,
        documented_employers=documented,
        stated_employer_count=1,
    )
    run = await create_verification_run(
        db, loan_file_id=loan_file.id, trigger=VerificationTrigger.MANUAL
    )
    await run_cross_source_deterministic(db, loan_file=loan_file, run=run, facts=facts)


async def _employer_findings(
    db: AsyncSession, loan_file_id: UUID, *, include_deleted: bool = False
) -> list[Finding]:
    stmt = select(Finding).where(
        Finding.loan_file_id == loan_file_id,
        Finding.rule_id == "xsrc.income.employer_name_consistency",
    )
    if not include_deleted:
        stmt = stmt.where(Finding.deleted_at.is_(None))
    return list((await db.execute(stmt)).scalars().all())


def _for(findings: list[Finding], employer: str) -> Finding | None:
    return next((f for f in findings if employer in (f.message or "")), None)


# --- Case 1 + 5: still-detected merges (kept), new added -----------------------


async def test_still_detected_merges_keeps_the_same_row(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    loan_file = await _file(db_session, company)

    await _run(db_session, loan_file, (_EMP_A,))
    first = await _employer_findings(db_session, loan_file.id)
    assert len(first) == 1
    original_id = first[0].id

    # Re-run, still detected → the EXISTING row is kept (merge), not churned into a new one.
    await _run(db_session, loan_file, (_EMP_A,))
    again = await _employer_findings(db_session, loan_file.id)
    assert len(again) == 1
    assert again[0].id == original_id  # same row — true merge (id/history preserved)


async def test_open_finding_notes_survive_a_rerun(db_session: AsyncSession) -> None:
    """A note on an OPEN finding survives a re-run (merge preserves history, not supersede)."""
    company = await _company(db_session)
    loan_file = await _file(db_session, company)

    await _run(db_session, loan_file, (_EMP_A,))
    finding = (await _employer_findings(db_session, loan_file.id))[0]
    finding.details = {**finding.details, "notes": [{"note": "checked with LO"}]}
    await db_session.flush()

    await _run(db_session, loan_file, (_EMP_A,))
    again = await _employer_findings(db_session, loan_file.id)
    assert len(again) == 1
    assert again[0].details.get("notes") == [{"note": "checked with LO"}]  # history preserved


async def test_new_finding_added(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    loan_file = await _file(db_session, company)

    await _run(db_session, loan_file, (_EMP_A,))
    # Re-run with BOTH employers → the new one is added, the existing kept.
    await _run(db_session, loan_file, (_EMP_A, _EMP_B))
    findings = await _employer_findings(db_session, loan_file.id)
    assert len(findings) == 2


# --- Case 2: no-longer-detected OPEN → DROPPED (the reversal) ------------------


async def test_no_longer_detected_open_is_dropped(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    loan_file = await _file(db_session, company)

    await _run(db_session, loan_file, (_EMP_A, _EMP_B))
    assert len(await _employer_findings(db_session, loan_file.id)) == 2

    # Re-run with only EMP_A → EMP_B is no longer detected + was OPEN → DROPPED (gone).
    await _run(db_session, loan_file, (_EMP_A,))
    live = await _employer_findings(db_session, loan_file.id)
    assert len(live) == 1
    assert _for(live, _EMP_B) is None  # removed, not marked
    # It is soft-deleted, not resurfacable as live.
    all_rows = await _employer_findings(db_session, loan_file.id, include_deleted=True)
    dropped = _for(all_rows, _EMP_B)
    assert dropped is not None and dropped.deleted_at is not None


# --- Case 3: still-detected RESOLVED → resolution preserved -------------------


async def test_still_detected_resolved_preserves_resolution(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    user = await _user(db_session, company)
    loan_file = await _file(db_session, company)

    await _run(db_session, loan_file, (_EMP_A,))
    finding = (await _employer_findings(db_session, loan_file.id))[0]
    await override_finding(db_session, finding=finding, actor_user_id=user.id, reason="DBA ok")

    await _run(db_session, loan_file, (_EMP_A,))  # still detected
    live = await _employer_findings(db_session, loan_file.id)
    assert len(live) == 1  # not duplicated
    assert live[0].resolution_status is FindingResolutionStatus.OVERRIDDEN  # not reopened


# --- Case 4: no-longer-detected RESOLVED/APPLIED → RETAINED (Undo-safe) -------


async def test_no_longer_detected_resolved_is_retained(db_session: AsyncSession) -> None:
    """The careful case: a resolved finding that no longer reproduces is RETAINED, not dropped."""
    company = await _company(db_session)
    user = await _user(db_session, company)
    loan_file = await _file(db_session, company)

    await _run(db_session, loan_file, (_EMP_A,))
    finding = (await _employer_findings(db_session, loan_file.id))[0]
    await override_finding(db_session, finding=finding, actor_user_id=user.id, reason="DBA ok")

    # Re-run with NO documented employers → the discrepancy no longer detected.
    await _run(db_session, loan_file, ())
    live = await _employer_findings(db_session, loan_file.id)
    assert len(live) == 1  # RETAINED (not dropped) — a completed action
    assert live[0].resolution_status is FindingResolutionStatus.OVERRIDDEN
    assert live[0].deleted_at is None


async def test_no_longer_detected_applied_keeps_record_for_undo(db_session: AsyncSession) -> None:
    """An APPLIED finding no longer detected keeps its applied_record (LP-98 Undo depends on it)."""
    company = await _company(db_session)
    user = await _user(db_session, company)
    loan_file = await _file(db_session, company)

    await _run(db_session, loan_file, (_EMP_A,))
    finding = (await _employer_findings(db_session, loan_file.id))[0]
    # Simulate an APPLIED resolution with a recorded data change (what LP-98 Undo reads).
    finding.resolution_status = FindingResolutionStatus.APPLIED
    finding.applied_record = {"action": "add_liability", "liability_id": "lp-98-record"}
    finding.resolved_by_user_id = user.id
    finding.resolved_at = utcnow()
    await db_session.flush()

    await _run(db_session, loan_file, ())  # no longer detected
    live = await _employer_findings(db_session, loan_file.id)
    assert len(live) == 1  # retained
    assert live[0].resolution_status is FindingResolutionStatus.APPLIED
    assert live[0].applied_record is not None  # the record survives → Undo still works


# --- Cache: an unchanged re-run drops nothing ---------------------------------


async def test_unchanged_rerun_drops_nothing(db_session: AsyncSession) -> None:
    """The reconcile only runs on an actual pass; a no-op re-run of the SAME facts is stable."""
    company = await _company(db_session)
    loan_file = await _file(db_session, company)

    await _run(db_session, loan_file, (_EMP_A, _EMP_B))
    before = {f.id for f in await _employer_findings(db_session, loan_file.id)}
    assert len(before) == 2

    # Same facts again → both still detected → both kept (same rows), nothing dropped.
    await _run(db_session, loan_file, (_EMP_A, _EMP_B))
    after = {f.id for f in await _employer_findings(db_session, loan_file.id)}
    assert after == before  # identical set of rows — no churn, no drop


# --- Tenant scoping -----------------------------------------------------------


async def test_reconcile_is_tenant_scoped(db_session: AsyncSession) -> None:
    company_a = await _company(db_session, "company-a")
    company_b = await _company(db_session, "company-b")
    file_a = await _file(db_session, company_a)
    file_b = await _file(db_session, company_b)

    await _run(db_session, file_a, (_EMP_A,))
    await _run(db_session, file_b, (_EMP_A,))

    # Dropping A's finding (re-run without it) must not touch B's.
    await _run(db_session, file_a, ())
    assert len(await _employer_findings(db_session, file_a.id)) == 0
    assert len(await _employer_findings(db_session, file_b.id)) == 1  # B untouched

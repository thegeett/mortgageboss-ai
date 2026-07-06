"""LP-75 — the findings model extension (confidence, resolution, blocking, source).

Covers the four extensions on the EXISTING LP-66 Finding model, the uniform shape
across generators, and the APPLY→recompute hook. Uses the transaction-rollback
``db_session`` fixture.
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
    FindingResolutionStatus,
    FindingStatus,
    LoanProgram,
    StatedIncomeItem,
    StatedLiability,
    User,
    UserRole,
)
from app.services.finding_blocking import is_file_blocked, open_in_scope_findings
from app.services.finding_resolution import apply_finding, override_finding
from app.services.loan_files import create_loan_file
from app.services.verification_engine import run_verification
from app.verification.confidence import (
    CONFIDENCE_CUTOFFS,
    DEFAULT_CONFIDENCE_CUTOFF,
    DETERMINISTIC_CONFIDENCE,
    AggressionLevel,
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


async def _finding(
    db: AsyncSession,
    loan_file_id,
    *,
    status: FindingStatus = FindingStatus.RED,
    confidence: float = 1.0,
    origin: FindingOrigin = FindingOrigin.DETERMINISTIC_RULE,
    category: FindingCategory = FindingCategory.INCOME,
    details: dict | None = None,
) -> Finding:
    finding = Finding(
        loan_file_id=loan_file_id,
        rule_id="conv.dti.back_end_max",
        origin=origin,
        confidence=confidence,
        status=status,
        category=category,
        message="DTI exceeds the cap.",
        details=details or {},
    )
    db.add(finding)
    await db.flush()
    return finding


# --- Confidence --------------------------------------------------------------


async def test_deterministic_engine_findings_are_certain(db_session: AsyncSession) -> None:
    """LP-74's emitted findings carry full (certain) confidence + uniform shape."""
    company = await _company(db_session, "acme")
    loan_file = await create_loan_file(
        db_session, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    borrower = Borrower(loan_file_id=loan_file.id, first_name="Pat", last_name="B", is_primary=True)
    db_session.add(borrower)
    await db_session.flush()
    db_session.add(
        StatedIncomeItem(
            borrower_id=borrower.id, monthly_amount=Decimal("10000"), employment_income=True
        )
    )
    db_session.add(
        StatedLiability(
            loan_file_id=loan_file.id, liability_type="Installment", monthly_payment=Decimal("4800")
        )
    )
    await db_session.flush()

    await run_verification(db_session, loan_file=loan_file, company_id=company.id)

    findings = (
        (await db_session.execute(select(Finding).where(Finding.loan_file_id == loan_file.id)))
        .scalars()
        .all()
    )
    assert findings
    assert all(f.confidence == DETERMINISTIC_CONFIDENCE for f in findings)


async def test_confidence_accepts_varying_values_for_ai_findings(db_session: AsyncSession) -> None:
    """The field accepts the varying confidences LP-78's AI findings will carry."""
    company = await _company(db_session, "acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)

    low = await _finding(
        db_session, loan_file.id, origin=FindingOrigin.AI_CROSS_SOURCE, confidence=0.4
    )
    high = await _finding(
        db_session, loan_file.id, origin=FindingOrigin.AI_CROSS_SOURCE, confidence=0.95
    )
    assert low.confidence == 0.4
    assert high.confidence == 0.95


# --- Resolution states -------------------------------------------------------


async def test_open_to_applied(db_session: AsyncSession) -> None:
    """A finding goes open → APPLIED and records the resolution trail."""
    company = await _company(db_session, "acme")
    user = await _user(db_session, company)
    loan_file = await create_loan_file(db_session, company_id=company.id)
    finding = await _finding(db_session, loan_file.id)
    assert finding.resolution_status is FindingResolutionStatus.OPEN

    await apply_finding(db_session, finding=finding, loan_file=loan_file, actor_user_id=user.id)

    assert finding.resolution_status is FindingResolutionStatus.APPLIED
    assert finding.resolved_by_user_id == user.id
    assert finding.resolved_at is not None


async def test_open_to_overridden_requires_reason(db_session: AsyncSession) -> None:
    """Overriding records the reason; overriding WITHOUT a reason fails."""
    company = await _company(db_session, "acme")
    user = await _user(db_session, company)
    loan_file = await create_loan_file(db_session, company_id=company.id)
    finding = await _finding(db_session, loan_file.id)

    # Blank reason → rejected (no silent ignore).
    for bad in ("", "   "):
        try:
            await override_finding(db_session, finding=finding, actor_user_id=user.id, reason=bad)
        except ValueError:
            pass
        else:  # pragma: no cover
            raise AssertionError("override without a reason must fail")
    assert finding.resolution_status is FindingResolutionStatus.OPEN

    await override_finding(
        db_session,
        finding=finding,
        actor_user_id=user.id,
        reason="Already disclosed on the URLA; duplicate.",
    )
    assert finding.resolution_status is FindingResolutionStatus.OVERRIDDEN
    assert finding.resolution_note == "Already disclosed on the URLA; duplicate."


async def test_no_third_ignore_resolution() -> None:
    """The verification resolutions are exactly applied/overridden (+ open)."""
    values = {s.value for s in FindingResolutionStatus}
    assert {"open", "applied", "overridden"} <= values
    assert "ignored" not in values
    assert "dismissed" not in values


async def test_resolution_is_activity_logged(db_session: AsyncSession) -> None:
    """Override reasons are recorded in the activity log."""
    company = await _company(db_session, "acme")
    user = await _user(db_session, company)
    loan_file = await create_loan_file(db_session, company_id=company.id)
    finding = await _finding(db_session, loan_file.id)

    await override_finding(
        db_session, finding=finding, actor_user_id=user.id, reason="Paid at closing."
    )

    logs = (
        (
            await db_session.execute(
                select(ActivityLog).where(
                    ActivityLog.loan_file_id == loan_file.id,
                    ActivityLog.activity_type == ActivityType.FINDING_RESOLVED,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(logs) == 1
    assert logs[0].detail["reason"] == "Paid at closing."
    assert logs[0].detail["resolution"] == "overridden"


# --- Blocking ----------------------------------------------------------------


async def test_open_in_scope_finding_blocks(db_session: AsyncSession) -> None:
    """A file with an open in-scope finding is blocked from ready-to-submit."""
    company = await _company(db_session, "acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    await _finding(db_session, loan_file.id, status=FindingStatus.RED, confidence=1.0)

    assert await is_file_blocked(db_session, loan_file_id=loan_file.id) is True


async def test_resolving_unblocks(db_session: AsyncSession) -> None:
    """Applying (or overriding) the in-scope finding unblocks the file."""
    company = await _company(db_session, "acme")
    user = await _user(db_session, company)
    loan_file = await create_loan_file(db_session, company_id=company.id)
    finding = await _finding(db_session, loan_file.id, status=FindingStatus.RED)
    assert await is_file_blocked(db_session, loan_file_id=loan_file.id) is True

    await override_finding(
        db_session, finding=finding, actor_user_id=user.id, reason="N/A — duplicate."
    )
    assert await is_file_blocked(db_session, loan_file_id=loan_file.id) is False


async def test_below_cutoff_finding_does_not_block(db_session: AsyncSession) -> None:
    """A finding below the active confidence cutoff is out of scope (no block)."""
    company = await _company(db_session, "acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    # confidence 0.3 < Balanced cutoff (0.5) → not in scope.
    await _finding(db_session, loan_file.id, status=FindingStatus.YELLOW, confidence=0.3)

    assert CONFIDENCE_CUTOFFS[AggressionLevel.BALANCED] == DEFAULT_CONFIDENCE_CUTOFF
    assert await is_file_blocked(db_session, loan_file_id=loan_file.id) is False
    # ...but Thorough (cutoff 0.0) brings it into scope → blocks.
    thorough = CONFIDENCE_CUTOFFS[AggressionLevel.THOROUGH]
    assert (
        await is_file_blocked(db_session, loan_file_id=loan_file.id, confidence_cutoff=thorough)
        is True
    )


async def test_green_findings_do_not_block(db_session: AsyncSession) -> None:
    """Green findings are passes — they never block."""
    company = await _company(db_session, "acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    await _finding(db_session, loan_file.id, status=FindingStatus.GREEN, confidence=1.0)

    assert await is_file_blocked(db_session, loan_file_id=loan_file.id) is False


# --- Source location ---------------------------------------------------------


async def test_finding_carries_source_location(db_session: AsyncSession) -> None:
    """A finding carries page + verbatim snippet (the trust/audit anchor)."""
    company = await _company(db_session, "acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    finding = Finding(
        loan_file_id=loan_file.id,
        rule_id="cross_source.income.discrepancy",
        origin=FindingOrigin.AI_CROSS_SOURCE,
        confidence=0.9,
        status=FindingStatus.YELLOW,
        category=FindingCategory.INCOME,
        message="Stated income differs from the pay stub.",
        source_page=2,
        source_snippet="Gross pay $4,200.00",
    )
    db_session.add(finding)
    await db_session.flush()

    assert finding.source_page == 2
    assert finding.source_snippet == "Gross pay $4,200.00"


# --- The uniform shape -------------------------------------------------------


async def test_three_generators_fit_one_shape(db_session: AsyncSession) -> None:
    """deterministic_rule / ai_cross_source / document_analysis — one shape."""
    company = await _company(db_session, "acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)

    origins = [
        FindingOrigin.DETERMINISTIC_RULE,
        FindingOrigin.AI_CROSS_SOURCE,
        FindingOrigin.DOCUMENT_ANALYSIS,
    ]
    for origin in origins:
        await _finding(db_session, loan_file.id, origin=origin, confidence=0.7)

    rows = (
        (await db_session.execute(select(Finding).where(Finding.loan_file_id == loan_file.id)))
        .scalars()
        .all()
    )
    assert {f.origin for f in rows} == set(origins)
    # Every finding exposes the same uniform attributes regardless of generator.
    for f in rows:
        for attr in (
            "rule_id",
            "status",
            "category",
            "confidence",
            "origin",
            "resolution_status",
            "source_page",
            "source_snippet",
            "message",
            "details",
        ):
            assert hasattr(f, attr)


# --- The APPLY → recompute hook ---------------------------------------------


async def test_applying_obligation_adds_liability(db_session: AsyncSession) -> None:
    """Applying an undisclosed-obligation finding ADDS it to the structured data.

    The structured-data change is the observable hook a recompute consumer
    (LP-76/77/78) reads.
    """
    company = await _company(db_session, "acme")
    user = await _user(db_session, company)
    loan_file = await create_loan_file(db_session, company_id=company.id)
    finding = await _finding(
        db_session,
        loan_file.id,
        category=FindingCategory.CROSS_SOURCE,
        origin=FindingOrigin.AI_CROSS_SOURCE,
        confidence=0.8,
        details={
            "apply": {
                "action": "add_liability",
                "liability_type": "Installment",
                "monthly_payment": "800",
                "holder_name": "County Support",
            }
        },
    )

    before = (
        (
            await db_session.execute(
                select(StatedLiability).where(StatedLiability.loan_file_id == loan_file.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(before) == 0

    await apply_finding(db_session, finding=finding, loan_file=loan_file, actor_user_id=user.id)

    after = (
        (
            await db_session.execute(
                select(StatedLiability).where(StatedLiability.loan_file_id == loan_file.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(after) == 1
    assert after[0].monthly_payment == Decimal("800")
    # The finding records what it applied (for the audit trail).
    assert finding.applied_record is not None
    assert finding.applied_record["action"] == "add_liability"
    assert finding.applied_record["liability_id"] == str(after[0].id)


# --- Tenant scoping ----------------------------------------------------------


async def test_blocking_is_per_file(db_session: AsyncSession) -> None:
    """Blocking is computed per file — another file's finding doesn't leak in."""
    company = await _company(db_session, "acme")
    blocked_file = await create_loan_file(db_session, company_id=company.id)
    clean_file = await create_loan_file(db_session, company_id=company.id)
    await _finding(db_session, blocked_file.id, status=FindingStatus.RED)

    assert await is_file_blocked(db_session, loan_file_id=blocked_file.id) is True
    assert await is_file_blocked(db_session, loan_file_id=clean_file.id) is False
    scoped = await open_in_scope_findings(db_session, loan_file_id=clean_file.id)
    assert scoped == []

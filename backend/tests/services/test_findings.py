"""Tests for the finding resolution service (LP-17).

``resolve_finding`` records a finding's resolution as an audit trail (status +
who + when + why) in one place. These tests cover resolving with each terminal
status, that ``resolved_at`` is timezone-aware, and the re-open behaviour
(returning to OPEN clears the trail).

Uses the transaction-rollback ``db_session`` fixture from LP-10.
"""

from app.models import (
    Company,
    Finding,
    FindingCategory,
    FindingResolutionStatus,
    FindingStatus,
    User,
    UserRole,
)
from app.services.findings import resolve_finding
from app.services.loan_files import create_loan_file
from sqlalchemy.ext.asyncio import AsyncSession


async def _setup(db_session: AsyncSession) -> tuple[Finding, User]:
    company = Company(name="Acme", slug="acme")
    db_session.add(company)
    await db_session.flush()
    user = User(
        company_id=company.id,
        email="u@acme.test",
        hashed_password="h",
        first_name="Re",
        last_name="Solver",
        role=UserRole.PROCESSOR,
    )
    db_session.add(user)
    await db_session.flush()
    loan_file = await create_loan_file(db_session, company_id=company.id)
    finding = Finding(
        loan_file_id=loan_file.id,
        rule_id="income.paystub_recency",
        status=FindingStatus.YELLOW,
        category=FindingCategory.INCOME,
        message="Pay stub is older than 30 days.",
    )
    db_session.add(finding)
    await db_session.flush()
    return finding, user


async def test_resolve_sets_status_note_user_and_timestamp(db_session: AsyncSession) -> None:
    """resolve_finding records status, note, resolved_by, and resolved_at."""
    finding, user = await _setup(db_session)

    resolved = await resolve_finding(
        db_session,
        finding=finding,
        resolution_status=FindingResolutionStatus.RESOLVED,
        user_id=user.id,
        note="Obtained a current pay stub.",
    )

    assert resolved.resolution_status is FindingResolutionStatus.RESOLVED
    assert resolved.resolution_note == "Obtained a current pay stub."
    assert resolved.resolved_by_user_id == user.id
    assert resolved.resolved_at is not None


async def test_resolved_at_is_timezone_aware(db_session: AsyncSession) -> None:
    """resolved_at is a timezone-aware datetime (UTC)."""
    finding, user = await _setup(db_session)

    resolved = await resolve_finding(
        db_session,
        finding=finding,
        resolution_status=FindingResolutionStatus.WAIVED,
        user_id=user.id,
    )

    assert resolved.resolved_at is not None
    assert resolved.resolved_at.tzinfo is not None
    assert resolved.resolved_at.utcoffset() is not None


async def test_accepted_risk_resolution(db_session: AsyncSession) -> None:
    """A yellow flag can be accepted as risk with a note."""
    finding, user = await _setup(db_session)

    resolved = await resolve_finding(
        db_session,
        finding=finding,
        resolution_status=FindingResolutionStatus.ACCEPTED_RISK,
        user_id=user.id,
        note="Compensating factor: 12 months reserves.",
    )

    assert resolved.resolution_status is FindingResolutionStatus.ACCEPTED_RISK
    assert resolved.resolution_note == "Compensating factor: 12 months reserves."
    assert resolved.resolved_by_user_id == user.id


async def test_reopening_clears_the_resolution_trail(db_session: AsyncSession) -> None:
    """Setting the status back to OPEN clears note, resolved_by, and resolved_at."""
    finding, user = await _setup(db_session)

    # First resolve it...
    await resolve_finding(
        db_session,
        finding=finding,
        resolution_status=FindingResolutionStatus.RESOLVED,
        user_id=user.id,
        note="Fixed.",
    )
    # ...then re-open it.
    reopened = await resolve_finding(
        db_session,
        finding=finding,
        resolution_status=FindingResolutionStatus.OPEN,
        user_id=user.id,
    )

    assert reopened.resolution_status is FindingResolutionStatus.OPEN
    assert reopened.resolution_note is None
    assert reopened.resolved_by_user_id is None
    assert reopened.resolved_at is None

"""The aggression dial (LP-79) — confidence-cutoff gating of display + blocking.

The dial is a per-file CONFIDENCE CUTOFF with a user-level default + per-file override.
These tests cover: the three levels as cutoffs (Conservative high / Balanced medium-
default / Thorough low); resolving the active level (override beats default); the
read-time filter gating in-scope (display) + blocking (LP-75's computation at the
supplied cutoff); never-recolors (severity is intrinsic, untouched by the dial); a
file clear-at-Balanced → blocked-at-Thorough → clear-at-Conservative as the dial moves
(the SAME stored findings, re-filtered — no re-run); and the active level recorded at
submission. Tenant scoping + the endpoints are covered in the API tests.
"""

import pytest
from app.models import (
    Borrower,
    Company,
    Finding,
    FindingCategory,
    FindingOrigin,
    FindingResolutionStatus,
    FindingStatus,
    User,
    UserRole,
)
from app.models.loan_file import LoanFile, LoanFileStatus
from app.schemas.loan_file import LoanFileUpdate
from app.services.aggression import active_cutoff, resolve_aggression_level
from app.services.finding_blocking import is_file_blocked, open_in_scope_findings
from app.services.loan_files import (
    FileBlockedError,
    create_loan_file,
    update_loan_file_with_activity,
)
from app.verification.confidence import (
    CONFIDENCE_CUTOFFS,
    DEFAULT_AGGRESSION,
    AggressionLevel,
    cutoff_for_level,
)
from sqlalchemy.ext.asyncio import AsyncSession


async def _company(db: AsyncSession, slug: str = "acme") -> Company:
    company = Company(name=slug.title(), slug=slug)
    db.add(company)
    await db.flush()
    return company


async def _user(
    db: AsyncSession, company: Company, *, default: AggressionLevel = AggressionLevel.BALANCED
) -> User:
    user = User(
        company_id=company.id,
        email=f"u@{company.slug}.test",
        hashed_password="h",  # pragma: allowlist secret
        first_name="Pro",
        last_name="Cessor",
        role=UserRole.PROCESSOR,
        default_aggression_level=default,
    )
    db.add(user)
    await db.flush()
    return user


async def _file(db: AsyncSession, company: Company) -> LoanFile:
    loan_file = await create_loan_file(db, company_id=company.id)
    db.add(
        Borrower(loan_file_id=loan_file.id, first_name="Dana", last_name="Sample", is_primary=True)
    )
    await db.flush()
    return loan_file


async def _finding(
    db: AsyncSession,
    loan_file: LoanFile,
    *,
    confidence: float,
    status: FindingStatus = FindingStatus.YELLOW,
    resolution: FindingResolutionStatus = FindingResolutionStatus.OPEN,
) -> Finding:
    f = Finding(
        loan_file_id=loan_file.id,
        rule_id="cross_source.income_variance",
        origin=FindingOrigin.AI_CROSS_SOURCE,
        confidence=confidence,
        status=status,
        category=FindingCategory.INCOME,
        message="A discrepancy.",
        resolution_status=resolution,
    )
    db.add(f)
    await db.flush()
    return f


# --- The three levels as confidence cutoffs ----------------------------------


def test_levels_are_confidence_cutoffs() -> None:
    """Conservative is the high bar, Thorough the low bar; Balanced is the default."""
    assert CONFIDENCE_CUTOFFS[AggressionLevel.CONSERVATIVE] == 0.8
    assert CONFIDENCE_CUTOFFS[AggressionLevel.BALANCED] == 0.5
    assert CONFIDENCE_CUTOFFS[AggressionLevel.THOROUGH] == 0.0
    assert DEFAULT_AGGRESSION is AggressionLevel.BALANCED
    # Conservative filters out more than Thorough (a higher cutoff = stricter).
    assert (
        cutoff_for_level(AggressionLevel.CONSERVATIVE)
        > cutoff_for_level(AggressionLevel.BALANCED)
        > cutoff_for_level(AggressionLevel.THOROUGH)
    )


# --- Resolving the active level: per-file override beats the user default ------


async def test_resolve_uses_user_default_without_an_override(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    user = await _user(db_session, company, default=AggressionLevel.CONSERVATIVE)
    loan_file = await _file(db_session, company)

    assert loan_file.aggression_level_override is None
    assert resolve_aggression_level(loan_file, user) is AggressionLevel.CONSERVATIVE
    assert active_cutoff(loan_file, user) == 0.8


async def test_per_file_override_takes_precedence(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    user = await _user(db_session, company, default=AggressionLevel.BALANCED)
    loan_file = await _file(db_session, company)
    loan_file.aggression_level_override = AggressionLevel.THOROUGH

    assert resolve_aggression_level(loan_file, user) is AggressionLevel.THOROUGH
    assert active_cutoff(loan_file, user) == 0.0


# --- The read-time filter gates display (in-scope) + blocking ------------------


async def test_cutoff_gates_in_scope_findings(db_session: AsyncSession) -> None:
    """More thoroughness (a lower cutoff) makes MORE of the same findings in-scope."""
    company = await _company(db_session)
    loan_file = await _file(db_session, company)
    await _finding(db_session, loan_file, confidence=0.9)  # high
    await _finding(db_session, loan_file, confidence=0.6)  # medium
    await _finding(db_session, loan_file, confidence=0.3)  # low hunch

    conservative = await open_in_scope_findings(
        db_session, loan_file_id=loan_file.id, confidence_cutoff=0.8
    )
    balanced = await open_in_scope_findings(
        db_session, loan_file_id=loan_file.id, confidence_cutoff=0.5
    )
    thorough = await open_in_scope_findings(
        db_session, loan_file_id=loan_file.id, confidence_cutoff=0.0
    )

    assert len(conservative) == 1  # only the 0.9
    assert len(balanced) == 2  # 0.9 + 0.6
    assert len(thorough) == 3  # all three — same stored findings, re-filtered


async def test_below_cutoff_does_not_block(db_session: AsyncSession) -> None:
    """A low-confidence open finding blocks at Thorough but not at Balanced (gating)."""
    company = await _company(db_session)
    loan_file = await _file(db_session, company)
    await _finding(db_session, loan_file, confidence=0.3)  # below Balanced's 0.5

    assert (
        await is_file_blocked(db_session, loan_file_id=loan_file.id, confidence_cutoff=0.5) is False
    )
    assert (
        await is_file_blocked(db_session, loan_file_id=loan_file.id, confidence_cutoff=0.0) is True
    )


async def test_resolved_findings_never_block(db_session: AsyncSession) -> None:
    """An applied/overridden finding is out of scope at any cutoff (resolve = unblock)."""
    company = await _company(db_session)
    loan_file = await _file(db_session, company)
    await _finding(
        db_session,
        loan_file,
        confidence=1.0,
        resolution=FindingResolutionStatus.OVERRIDDEN,
    )
    assert (
        await is_file_blocked(db_session, loan_file_id=loan_file.id, confidence_cutoff=0.0) is False
    )


# --- Never recolors: the dial changes in-scope, not severity ------------------


async def test_dial_never_recolors_findings(db_session: AsyncSession) -> None:
    """A red finding stays red whether it's in scope or not — severity is intrinsic."""
    company = await _company(db_session)
    loan_file = await _file(db_session, company)
    red = await _finding(db_session, loan_file, confidence=0.3, status=FindingStatus.RED)

    # In scope at Thorough — still RED (the cutoff didn't change the color).
    in_scope = await open_in_scope_findings(
        db_session, loan_file_id=loan_file.id, confidence_cutoff=0.0
    )
    assert [f.id for f in in_scope] == [red.id]
    assert in_scope[0].status is FindingStatus.RED

    # Out of scope at Conservative — the row is just filtered out; its color is unchanged.
    out = await open_in_scope_findings(db_session, loan_file_id=loan_file.id, confidence_cutoff=0.8)
    assert out == []
    assert red.status is FindingStatus.RED  # the stored severity never moved


# --- Clear ↔ blocked as the dial moves (the same stored findings) -------------


async def test_clear_at_balanced_blocked_at_thorough_clear_at_conservative(
    db_session: AsyncSession,
) -> None:
    company = await _company(db_session)
    loan_file = await _file(db_session, company)
    # One borderline, low-confidence open finding (0.3): below Balanced + Conservative,
    # in-scope only at Thorough. Nothing about the finding changes — only the cutoff.
    await _finding(db_session, loan_file, confidence=0.3)

    async def blocked(level: AggressionLevel) -> bool:
        return await is_file_blocked(
            db_session, loan_file_id=loan_file.id, confidence_cutoff=cutoff_for_level(level)
        )

    assert await blocked(AggressionLevel.BALANCED) is False  # clear
    assert await blocked(AggressionLevel.THOROUGH) is True  # dial up → blocked
    assert await blocked(AggressionLevel.CONSERVATIVE) is False  # dial down → clear again


# --- The submit gate + recording the active level at submission ---------------


async def test_submit_gate_uses_the_active_level(db_session: AsyncSession) -> None:
    """A file clear at the user's Balanced default blocks once overridden to Thorough."""
    company = await _company(db_session)
    user = await _user(db_session, company, default=AggressionLevel.BALANCED)
    loan_file = await _file(db_session, company)
    await _finding(db_session, loan_file, confidence=0.3)  # only in-scope at Thorough
    await db_session.flush()

    loan_file.aggression_level_override = AggressionLevel.THOROUGH
    with pytest.raises(FileBlockedError):
        await update_loan_file_with_activity(
            db_session,
            loan_file=loan_file,
            data=LoanFileUpdate(status=LoanFileStatus.READY_TO_SUBMIT),
            actor_user_id=user.id,
            actor=user,
        )


async def test_records_the_active_level_at_submission(db_session: AsyncSession) -> None:
    """Passing the gate records 'cleared at <level> thoroughness' for auditability."""
    company = await _company(db_session)
    user = await _user(db_session, company, default=AggressionLevel.BALANCED)
    loan_file = await _file(db_session, company)
    # A low-confidence finding that is out of scope at Balanced → the file is clear.
    await _finding(db_session, loan_file, confidence=0.3)
    loan_file.aggression_level_override = AggressionLevel.BALANCED
    await db_session.flush()

    await update_loan_file_with_activity(
        db_session,
        loan_file=loan_file,
        data=LoanFileUpdate(status=LoanFileStatus.READY_TO_SUBMIT),
        actor_user_id=user.id,
        actor=user,
    )

    assert loan_file.status is LoanFileStatus.READY_TO_SUBMIT
    assert loan_file.submitted_aggression_level is AggressionLevel.BALANCED


async def test_records_the_override_level_at_submission(db_session: AsyncSession) -> None:
    """The recorded level is the active one — the per-file override when set."""
    company = await _company(db_session)
    user = await _user(db_session, company, default=AggressionLevel.BALANCED)
    loan_file = await _file(db_session, company)
    loan_file.aggression_level_override = AggressionLevel.CONSERVATIVE
    await db_session.flush()

    await update_loan_file_with_activity(
        db_session,
        loan_file=loan_file,
        data=LoanFileUpdate(status=LoanFileStatus.READY_TO_SUBMIT),
        actor_user_id=user.id,
        actor=user,
    )
    assert loan_file.submitted_aggression_level is AggressionLevel.CONSERVATIVE

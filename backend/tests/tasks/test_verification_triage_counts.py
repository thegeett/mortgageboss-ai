"""bug-007 — the run's red / yellow / green summary, against a real database.

Its own file rather than `test_verification_rules.py`: that module drives the completion path through
a hand-built session double under `pytest.mark.anyio`, and the DB fixtures here are pytest-asyncio's.
The question this asks cannot be answered by a double anyway — the defect was SQL three-valued logic,
which only a real Postgres evaluates.
"""

from __future__ import annotations

from uuid import uuid4

from app.models import Company, EvaluationOutcome
from app.models.finding import Finding, FindingCategory, FindingResolutionStatus, FindingStatus
from app.services.loan_files import create_loan_file
from app.tasks.verification_rules import _triage_counts
from sqlalchemy.ext.asyncio import AsyncSession


async def _loan_file_id(db: AsyncSession):
    company = Company(name="Acme", slug=f"acme-{uuid4().hex[:6]}")
    db.add(company)
    await db.flush()
    return (await create_loan_file(db, company_id=company.id)).id


def _finding(
    loan_file_id,
    status: FindingStatus,
    outcome: EvaluationOutcome | None,
    message: str,
    *,
    resolution: FindingResolutionStatus = FindingResolutionStatus.OPEN,
) -> Finding:
    return Finding(
        loan_file_id=loan_file_id,
        rule_id="ID-3",
        status=status,
        category=FindingCategory.INCOME,
        message=message,
        details={},
        evaluation_outcome=outcome,
        resolution_status=resolution,
    )


async def test_a_finding_with_no_evaluation_outcome_still_counts(db_session: AsyncSession) -> None:
    """`evaluation_outcome` IS NULLABLE BY DESIGN — "only tag-rule findings carry it; existing
    cross-source/document findings leave it null" — and in SQL `null != 'no_longer_applies'` is NULL,
    which WHERE drops. On staging that silently excluded 18 live, open, yellow findings from
    `yellow_count`: a run reporting a cleaner file than the file is, the one direction `_triage_counts`
    says in its own docstring that it refuses."""
    lf_id = await _loan_file_id(db_session)
    db_session.add_all(
        [
            _finding(lf_id, FindingStatus.YELLOW, None, "the dates of birth do not agree"),
            _finding(lf_id, FindingStatus.YELLOW, EvaluationOutcome.COULDNT_CHECK, "no source"),
            _finding(lf_id, FindingStatus.RED, EvaluationOutcome.OPEN, "an undisclosed obligation"),
        ]
    )
    await db_session.flush()

    assert await _triage_counts(db_session, lf_id) == (1, 2, 0)


async def test_retired_and_resolved_findings_stay_out(db_session: AsyncSession) -> None:
    """The other half of "active": a RETIRED finding is not soft-deleted (reconciliation sets
    `NO_LONGER_APPLIES` and a green status and leaves the row live), and a RESOLVED one keeps its
    severity because `_update_finding` deliberately never touches `resolution_status`. Counting either
    reports numbers a processor has already worked to clear."""
    lf_id = await _loan_file_id(db_session)
    db_session.add_all(
        [
            _finding(lf_id, FindingStatus.GREEN, EvaluationOutcome.NO_LONGER_APPLIES, "retired"),
            _finding(
                lf_id,
                FindingStatus.RED,
                EvaluationOutcome.OPEN,
                "applied by a processor",
                resolution=FindingResolutionStatus.APPLIED,
            ),
            _finding(
                lf_id,
                FindingStatus.RED,
                None,
                "overridden by a processor",
                resolution=FindingResolutionStatus.OVERRIDDEN,
            ),
            _finding(lf_id, FindingStatus.GREEN, EvaluationOutcome.SATISFIED, "still true"),
        ]
    )
    await db_session.flush()

    assert await _triage_counts(db_session, lf_id) == (0, 0, 1)

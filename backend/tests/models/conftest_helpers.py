"""Small builders for the condition model tests (LP-904).

Deliberately NOT a conftest fixture set. These tests need two companies at once — that is the whole
point of the tenancy one — and a fixture yielding "the" company would have to be parametrised or
duplicated to say that. A plain function that returns a new row each call reads the same way at every
call site and composes without ceremony.

Every name and slug is `uuid4`-suffixed, following `tests/services/test_overlay_update_audit.py`: the
session is rolled back per test, but a unique constraint on `(company_id, slug)` will still collide
inside one test that builds two lenders.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.models.company import Company
from app.models.condition import (
    BucketKind,
    Condition,
    OwnerHint,
    OwnerHintSource,
)
from app.models.condition_round import (
    ConditionRound,
    ConditionRoundCompleteness,
    ConditionRoundStatus,
    ConditionSheetFormat,
)
from app.models.lender import Lender
from app.models.loan_file import LoanFile
from app.services.loan_files import create_loan_file
from sqlalchemy.ext.asyncio import AsyncSession


async def make_company(db: AsyncSession, *, name: str = "Acme Processing") -> Company:
    company = Company(name=name, slug=f"acme-{uuid4().hex[:8]}")
    db.add(company)
    await db.flush()
    return company


async def make_lender(db: AsyncSession, *, company: Company, name: str = "UWM") -> Lender:
    lender = Lender(
        company_id=company.id,
        name=name,
        slug=f"{name.lower()}-{uuid4().hex[:8]}",
        supported_programs=["conventional"],
    )
    db.add(lender)
    await db.flush()
    return lender


async def make_loan_file(db: AsyncSession, *, company: Company) -> LoanFile:
    """Create a loan file the way the application does (LP-904 review fix).

    ⚠️ THROUGH `create_loan_file`, NEVER `LoanFile(...)` DIRECTLY. `display_id` and `inbox_token` are
    both NOT NULL with no server default — confirmed in the live schema, not just the model — and
    ADR-036/ADR-050 put their generation in `app/services/loan_files.py`. A bare construction raises
    `NotNullViolationError` at flush, so the test dies in SETUP before a single assertion runs.

    THAT IS HOW LP-904'S GUARDS SAT GREEN WITHOUT EVER EXECUTING. Six tests — the four tenancy ones
    and two append-only ones — failed this way on their first real run, through two review rounds and
    a suite that looked healthy, because the machine had no database and could only COLLECT them.
    Collection is not execution. "One company cannot see another's rounds" had never been
    demonstrated once.

    The service already flushes ("Uses `flush` rather than `commit` so the caller controls the
    transaction"), so this helper adds none of its own. Twelve other model-test files build loan
    files exactly this way; this is existing practice, not a new decision.
    """
    return await create_loan_file(db, company_id=company.id)


async def make_round(
    db: AsyncSession,
    *,
    company: Company,
    loan_file: LoanFile,
    lender: Lender | None = None,
    status: ConditionRoundStatus = ConditionRoundStatus.DRAFT,
    round_number: int | None = None,
) -> ConditionRound:
    """A round in whatever state the test needs. `round_number` stays None unless asked for —
    drafts have none, and the partial unique index only constrains rows that HAVE a number.

    ⚠️ THIS SAID "ONLY CONSTRAINS IMPORTED ROWS", WHICH IS THE BELIEF LP-904's REVIEW CORRECTED.
    The predicate is `round_number IS NOT NULL AND deleted_at IS NULL` — no status term at all — so
    a round that was imported and is later DISCARDED keeps its number and is still constrained. The
    omission is deliberate: `condition_events` is append-only, so a discarded round's ROUND_IMPORTED
    event survives forever, and freeing its number would leave two different sheets both recorded as
    "round 2" in an immutable history with nothing able to tell them apart.

    `tests/models/test_condition_round_number_uniqueness.py` pins both halves.
    """
    round_ = ConditionRound(
        company_id=company.id,
        loan_file_id=loan_file.id,
        lender_id=lender.id if lender is not None else None,
        status=status,
        round_number=round_number,
        completeness=ConditionRoundCompleteness.FULL,
        sheet_format=ConditionSheetFormat.UWM_APPROVAL_LETTER,
        round_date=datetime.now(UTC).date(),
        sources=[],
        parse_report={},
    )
    db.add(round_)
    await db.flush()
    return round_


async def make_condition(
    db: AsyncSession,
    *,
    company: Company,
    loan_file: LoanFile,
    round_: ConditionRound,
    lender: Lender | None = None,
    lender_code: str | None = "7086",
    verbatim_text: str = "Provide copy of invoice for credit report.",
    fingerprint: str | None = None,
) -> Condition:
    condition = Condition(
        company_id=company.id,
        loan_file_id=loan_file.id,
        lender_id=lender.id if lender is not None else None,
        first_round_id=round_.id,
        last_seen_round_id=round_.id,
        sequence=1,
        lender_code=lender_code,
        bucket_heading="Closing (PTF)",
        bucket_kind=BucketKind.PRIOR_TO_FUNDING,
        verbatim_text=verbatim_text,
        text_fingerprint=fingerprint or uuid4().hex * 2,
        underwriter_notes=[],
        owner_hint=OwnerHint.PROCESSOR,
        owner_hint_source=OwnerHintSource.CODE_MAP,
    )
    db.add(condition)
    await db.flush()
    return condition

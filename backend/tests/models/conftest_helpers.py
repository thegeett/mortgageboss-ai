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
    loan_file = LoanFile(company_id=company.id)
    db.add(loan_file)
    await db.flush()
    return loan_file


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
    drafts have none, and the partial unique index only constrains imported rows."""
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

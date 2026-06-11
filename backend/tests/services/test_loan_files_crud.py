"""Tests for the company-scoped loan-file CRUD service (LP-28).

Exercises :mod:`app.services.loan_files` against the rollback ``db_session``:
company scoping (the crux — one company never sees another's files), dual
identifier lookup (UUID and display_id), partial update semantics
(``exclude_unset``), soft delete exclusion, pagination, status filtering, and
the derived ``primary_borrower_name``.
"""

from app.models import Borrower, Company
from app.models.loan_file import LoanFileStatus
from app.schemas.loan_file import LoanFileSummary, LoanFileUpdate
from app.services.loan_files import (
    create_loan_file,
    get_loan_file,
    list_loan_files,
    soft_delete_loan_file,
    update_loan_file,
)
from sqlalchemy.ext.asyncio import AsyncSession


async def _company(db: AsyncSession, slug: str) -> Company:
    company = Company(name=slug.title(), slug=slug)
    db.add(company)
    await db.flush()
    return company


async def test_list_is_company_scoped(db_session: AsyncSession) -> None:
    """list_loan_files returns only the requested company's files."""
    a = await _company(db_session, "company-a")
    b = await _company(db_session, "company-b")
    await create_loan_file(db_session, company_id=a.id)
    await create_loan_file(db_session, company_id=a.id)
    await create_loan_file(db_session, company_id=b.id)

    items, total = await list_loan_files(db_session, company_id=a.id)
    assert total == 2
    assert len(items) == 2
    assert all(f.company_id == a.id for f in items)


async def test_get_other_companys_file_returns_none(db_session: AsyncSession) -> None:
    """A company cannot fetch another company's file by UUID or display_id."""
    a = await _company(db_session, "company-a")
    b = await _company(db_session, "company-b")
    b_file = await create_loan_file(db_session, company_id=b.id)

    assert await get_loan_file(db_session, company_id=a.id, identifier=str(b_file.id)) is None
    assert await get_loan_file(db_session, company_id=a.id, identifier=b_file.display_id) is None
    # The owning company can fetch it.
    assert await get_loan_file(db_session, company_id=b.id, identifier=str(b_file.id)) is not None


async def test_get_by_uuid_and_display_id(db_session: AsyncSession) -> None:
    """get_loan_file resolves both a UUID and a display_id to the same file."""
    a = await _company(db_session, "acme")
    created = await create_loan_file(db_session, company_id=a.id)

    by_uuid = await get_loan_file(db_session, company_id=a.id, identifier=str(created.id))
    by_display = await get_loan_file(db_session, company_id=a.id, identifier=created.display_id)
    assert by_uuid is not None
    assert by_display is not None
    assert by_uuid.id == by_display.id == created.id


async def test_update_applies_only_set_fields(db_session: AsyncSession) -> None:
    """exclude_unset: omitted fields are untouched; identifiers never change."""
    a = await _company(db_session, "acme")
    created = await create_loan_file(db_session, company_id=a.id, loan_officer_name="Original LO")
    display_id, company_id, inbox_token = (
        created.display_id,
        created.company_id,
        created.inbox_token,
    )

    await update_loan_file(
        db_session, loan_file=created, data=LoanFileUpdate(status=LoanFileStatus.IN_PROCESSING)
    )

    assert created.status is LoanFileStatus.IN_PROCESSING
    assert created.loan_officer_name == "Original LO"  # omitted → untouched
    # Identifiers / ownership are immutable.
    assert created.display_id == display_id
    assert created.company_id == company_id
    assert created.inbox_token == inbox_token


async def test_update_explicit_null_clears_field(db_session: AsyncSession) -> None:
    """An explicitly-provided null clears the field (distinct from omission)."""
    a = await _company(db_session, "acme")
    created = await create_loan_file(db_session, company_id=a.id, loan_officer_name="Original LO")

    await update_loan_file(
        db_session, loan_file=created, data=LoanFileUpdate(loan_officer_name=None)
    )
    assert created.loan_officer_name is None


async def test_soft_delete_excludes_from_reads(db_session: AsyncSession) -> None:
    """Soft delete sets deleted_at and removes the file from list/get."""
    a = await _company(db_session, "acme")
    created = await create_loan_file(db_session, company_id=a.id)

    await soft_delete_loan_file(db_session, loan_file=created)
    assert created.deleted_at is not None

    assert await get_loan_file(db_session, company_id=a.id, identifier=str(created.id)) is None
    items, total = await list_loan_files(db_session, company_id=a.id)
    assert total == 0
    assert items == []


async def test_status_filter_and_pagination(db_session: AsyncSession) -> None:
    """List supports a status filter and bounded pagination with a full total."""
    a = await _company(db_session, "acme")
    await create_loan_file(db_session, company_id=a.id)
    second = await create_loan_file(db_session, company_id=a.id)
    await create_loan_file(db_session, company_id=a.id)
    await update_loan_file(
        db_session, loan_file=second, data=LoanFileUpdate(status=LoanFileStatus.IN_PROCESSING)
    )

    drafts, draft_total = await list_loan_files(
        db_session, company_id=a.id, status=LoanFileStatus.DRAFT
    )
    assert draft_total == 2
    assert all(f.status is LoanFileStatus.DRAFT for f in drafts)

    page1, total = await list_loan_files(db_session, company_id=a.id, page=1, page_size=2)
    assert total == 3
    assert len(page1) == 2
    page2, _ = await list_loan_files(db_session, company_id=a.id, page=2, page_size=2)
    assert len(page2) == 1


async def test_primary_borrower_name_is_derived(db_session: AsyncSession) -> None:
    """The summary's primary_borrower_name comes from the is_primary borrower."""
    a = await _company(db_session, "acme")
    created = await create_loan_file(db_session, company_id=a.id)
    db_session.add(
        Borrower(
            loan_file_id=created.id,
            first_name="Pat",
            last_name="Buyer",
            is_primary=True,
            borrower_position=1,
        )
    )
    db_session.add(
        Borrower(
            loan_file_id=created.id,
            first_name="Sam",
            last_name="Cosigner",
            is_primary=False,
            borrower_position=2,
        )
    )
    await db_session.flush()

    items, _ = await list_loan_files(db_session, company_id=a.id)
    summary = LoanFileSummary.from_model(items[0])
    assert summary.primary_borrower_name == "Pat Buyer"

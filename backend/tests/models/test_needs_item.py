"""Tests for the NeedsItem model (LP-19).

Covers the needs-list record against a real table: field round-tripping, the
OUTSTANDING/MANUAL/STANDARD defaults, the four enum CHECK constraints
(status/origin/priority/category), needs_type as a flexible string, the nullable
borrower and satisfied-document links, relationships, multiple items per file,
soft delete, and tenant isolation.

The lifecycle helpers and the SET NULL behaviour live in
``tests/services/test_needs_items.py``.

Uses the transaction-rollback ``db_session`` fixture from LP-10.
"""

import pytest
from app.models import (
    Borrower,
    Company,
    Document,
    DocumentCategory,
    LoanFile,
    NeedsItem,
    NeedsItemOrigin,
    NeedsItemPriority,
    NeedsItemStatus,
    UploadSource,
    only_active,
    scope_to_company,
    utcnow,
)
from app.services.loan_files import create_loan_file
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


async def _make_company(db_session: AsyncSession, slug: str) -> Company:
    company = Company(name=slug.title(), slug=slug)
    db_session.add(company)
    await db_session.flush()
    return company


async def _make_loan_file(db_session: AsyncSession, company: Company) -> LoanFile:
    return await create_loan_file(db_session, company_id=company.id)


async def _make_borrower(db_session: AsyncSession, loan_file: LoanFile) -> Borrower:
    borrower = Borrower(loan_file_id=loan_file.id, first_name="Jane", last_name="Doe")
    db_session.add(borrower)
    await db_session.flush()
    return borrower


async def _make_document(db_session: AsyncSession, loan_file: LoanFile) -> Document:
    document = Document(
        loan_file_id=loan_file.id,
        original_filename="w2.pdf",
        mime_type="application/pdf",
        file_size_bytes=1024,
        storage_path="acme/lf/w2.pdf",
        upload_source=UploadSource.USER_UPLOAD,
    )
    db_session.add(document)
    await db_session.flush()
    return document


async def _add_needs_item(
    db_session: AsyncSession,
    loan_file: LoanFile,
    *,
    title: str = "2023 W-2",
    **kwargs: object,
) -> NeedsItem:
    item = NeedsItem(loan_file_id=loan_file.id, title=title, **kwargs)
    db_session.add(item)
    await db_session.flush()
    return item


async def test_create_needs_item_defaults(db_session: AsyncSession) -> None:
    """A new item defaults to OUTSTANDING / MANUAL / STANDARD with null links."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    item = await _add_needs_item(db_session, loan_file, title="2023 W-2")

    await db_session.refresh(item)
    assert item.title == "2023 W-2"
    assert item.status is NeedsItemStatus.OUTSTANDING
    assert item.origin is NeedsItemOrigin.MANUAL
    assert item.priority is NeedsItemPriority.STANDARD
    assert item.category is None
    assert item.borrower_id is None
    assert item.satisfied_by_document_id is None
    assert item.satisfied_at is None
    assert item.requested_at is None


async def test_create_with_category_and_type(db_session: AsyncSession) -> None:
    """category (reused DocumentCategory) and needs_type persist."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    item = await _add_needs_item(
        db_session,
        loan_file,
        title="LOE for large deposit",
        category=DocumentCategory.ASSETS,
        needs_type="loe_large_deposit",
        priority=NeedsItemPriority.BLOCKING,
        description="Explain the $9,000 deposit on the May statement.",
    )

    await db_session.refresh(item)
    assert item.category is DocumentCategory.ASSETS
    assert item.needs_type == "loe_large_deposit"
    assert item.priority is NeedsItemPriority.BLOCKING
    assert item.description == "Explain the $9,000 deposit on the May statement."


async def test_needs_type_is_a_flexible_string(db_session: AsyncSession) -> None:
    """needs_type accepts any string — it is not an enum."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    for value in ("w2", "loe_large_deposit", "voe_current"):
        item = await _add_needs_item(db_session, loan_file, needs_type=value)
        await db_session.refresh(item)
        assert item.needs_type == value


async def test_status_check_constraint_rejects_invalid_value(db_session: AsyncSession) -> None:
    """The DB CHECK constraint rejects an out-of-range status."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    item = await _add_needs_item(db_session, loan_file)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE needs_items SET status = :bad WHERE id = :id"),
                {"bad": "pending", "id": item.id},
            )


async def test_origin_check_constraint_rejects_invalid_value(db_session: AsyncSession) -> None:
    """The DB CHECK constraint rejects an out-of-range origin."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    item = await _add_needs_item(db_session, loan_file)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE needs_items SET origin = :bad WHERE id = :id"),
                {"bad": "import", "id": item.id},
            )


async def test_priority_check_constraint_rejects_invalid_value(db_session: AsyncSession) -> None:
    """The DB CHECK constraint rejects an out-of-range priority."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    item = await _add_needs_item(db_session, loan_file)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE needs_items SET priority = :bad WHERE id = :id"),
                {"bad": "urgent", "id": item.id},
            )


async def test_category_check_constraint_rejects_invalid_value(db_session: AsyncSession) -> None:
    """The DB CHECK constraint rejects an out-of-range category."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    item = await _add_needs_item(db_session, loan_file, category=DocumentCategory.ASSETS)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE needs_items SET category = :bad WHERE id = :id"),
                {"bad": "taxes", "id": item.id},
            )


async def test_all_enum_values_accepted(db_session: AsyncSession) -> None:
    """Every status, origin, and priority value is valid."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    for status in NeedsItemStatus:
        for origin in NeedsItemOrigin:
            for priority in NeedsItemPriority:
                item = await _add_needs_item(
                    db_session, loan_file, status=status, origin=origin, priority=priority
                )
                await db_session.refresh(item)
                assert item.status is status
                assert item.origin is origin
                assert item.priority is priority


async def test_borrower_link_nullable(db_session: AsyncSession) -> None:
    """A file-level need has null borrower; a borrower-specific need links one."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    borrower = await _make_borrower(db_session, loan_file)

    file_level = await _add_needs_item(db_session, loan_file, title="Appraisal")
    borrower_level = await _add_needs_item(
        db_session, loan_file, title="W-2", borrower_id=borrower.id
    )

    await db_session.refresh(file_level)
    await db_session.refresh(borrower_level)
    assert file_level.borrower_id is None
    assert borrower_level.borrower_id == borrower.id


async def test_relationships_load(db_session: AsyncSession) -> None:
    """needs_item.loan_file/borrower/satisfied_by_document and loan_file.needs_items load."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    borrower = await _make_borrower(db_session, loan_file)
    document = await _make_document(db_session, loan_file)
    item = await _add_needs_item(
        db_session,
        loan_file,
        borrower_id=borrower.id,
        satisfied_by_document_id=document.id,
    )

    stmt = (
        select(NeedsItem)
        .where(NeedsItem.id == item.id)
        .options(
            selectinload(NeedsItem.loan_file),
            selectinload(NeedsItem.borrower),
            selectinload(NeedsItem.satisfied_by_document),
        )
    )
    loaded = (await db_session.scalars(stmt)).one()
    assert loaded.loan_file.id == loan_file.id
    assert loaded.borrower is not None
    assert loaded.borrower.id == borrower.id
    assert loaded.satisfied_by_document is not None
    assert loaded.satisfied_by_document.id == document.id

    file_stmt = (
        select(LoanFile)
        .where(LoanFile.id == loan_file.id)
        .options(selectinload(LoanFile.needs_items))
    )
    loaded_file = (await db_session.scalars(file_stmt)).one()
    assert item.id in {n.id for n in loaded_file.needs_items}


async def test_multiple_needs_items_per_loan_file(db_session: AsyncSession) -> None:
    """loan_file.needs_items returns every item attached to the file."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    n1 = await _add_needs_item(db_session, loan_file, title="W-2")
    n2 = await _add_needs_item(db_session, loan_file, title="Bank statement")
    n3 = await _add_needs_item(db_session, loan_file, title="Appraisal")

    stmt = (
        select(LoanFile)
        .where(LoanFile.id == loan_file.id)
        .options(selectinload(LoanFile.needs_items))
    )
    loaded = (await db_session.scalars(stmt)).one()
    assert {n.id for n in loaded.needs_items} == {n1.id, n2.id, n3.id}


async def test_soft_delete_and_only_active(db_session: AsyncSession) -> None:
    """Soft delete sets deleted_at; only_active() filters the item out."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    live = await _add_needs_item(db_session, loan_file, title="Live")
    gone = await _add_needs_item(db_session, loan_file, title="Gone")

    gone.deleted_at = utcnow()
    await db_session.flush()
    assert gone.is_deleted is True

    stmt = only_active(select(NeedsItem), NeedsItem)
    ids = {n.id for n in (await db_session.scalars(stmt)).all()}
    assert live.id in ids
    assert gone.id not in ids


async def test_needs_items_are_isolated_by_company_through_their_loan_file(
    db_session: AsyncSession,
) -> None:
    """Needs items carry no company_id; isolation is transitive via the loan file."""
    company_a = await _make_company(db_session, "company-a")
    company_b = await _make_company(db_session, "company-b")
    file_a = await _make_loan_file(db_session, company_a)
    file_b = await _make_loan_file(db_session, company_b)

    item_a = await _add_needs_item(db_session, file_a, title="A")
    item_b = await _add_needs_item(db_session, file_b, title="B")

    stmt_a = scope_to_company(
        select(NeedsItem).join(LoanFile, NeedsItem.loan_file_id == LoanFile.id),
        LoanFile,
        company_a.id,
    )
    ids_a = {n.id for n in (await db_session.scalars(stmt_a)).all()}
    assert ids_a == {item_a.id}
    assert item_b.id not in ids_a

    stmt_b = scope_to_company(
        select(NeedsItem).join(LoanFile, NeedsItem.loan_file_id == LoanFile.id),
        LoanFile,
        company_b.id,
    )
    ids_b = {n.id for n in (await db_session.scalars(stmt_b)).all()}
    assert ids_b == {item_b.id}
    assert ids_a.isdisjoint(ids_b)

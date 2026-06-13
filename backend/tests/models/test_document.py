"""Tests for the Document model (LP-15).

Covers the uploaded-file record against a real table: field round-tripping, the
PENDING status default, document_type as a flexible string, the three enum CHECK
constraints (category/status/upload_source), the nullable uploaded_by provenance
(user uploads link a user; borrower-inbox / MISMO imports do not), float
confidence, relationships, multiple documents per file, soft delete, and tenant
isolation (documents reachable only through the owning company's loan files,
since they have no company_id of their own).

Uses the transaction-rollback ``db_session`` fixture from LP-10.
"""

import pytest
from app.models import (
    Company,
    Document,
    DocumentCategory,
    DocumentStatus,
    LoanFile,
    UploadSource,
    User,
    UserRole,
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


async def _make_user(db_session: AsyncSession, company: Company, email: str) -> User:
    user = User(
        company_id=company.id,
        email=email,
        hashed_password="h",
        first_name="Up",
        last_name="Loader",
        role=UserRole.PROCESSOR,
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def _make_loan_file(db_session: AsyncSession, company: Company) -> LoanFile:
    return await create_loan_file(db_session, company_id=company.id)


async def _add_document(
    db_session: AsyncSession,
    loan_file: LoanFile,
    *,
    original_filename: str = "paystub.pdf",
    mime_type: str = "application/pdf",
    file_size_bytes: int = 12345,
    storage_path: str = "company/loan/doc.pdf",
    upload_source: UploadSource = UploadSource.USER_UPLOAD,
    uploaded_by_user_id: object = None,
    **kwargs: object,
) -> Document:
    document = Document(
        loan_file_id=loan_file.id,
        original_filename=original_filename,
        mime_type=mime_type,
        file_size_bytes=file_size_bytes,
        storage_path=storage_path,
        upload_source=upload_source,
        uploaded_by_user_id=uploaded_by_user_id,
        **kwargs,
    )
    db_session.add(document)
    await db_session.flush()
    return document


async def test_create_document_with_all_fields(db_session: AsyncSession) -> None:
    """A document persists its storage metadata, classification, and provenance."""
    company = await _make_company(db_session, "acme")
    user = await _make_user(db_session, company, "u@acme.test")
    loan_file = await _make_loan_file(db_session, company)
    document = await _add_document(
        db_session,
        loan_file,
        original_filename="w2_2025.pdf",
        mime_type="application/pdf",
        file_size_bytes=88_213,
        storage_path="acme/lf-1/w2_2025.pdf",
        document_type="w2",
        category=DocumentCategory.INCOME_EMPLOYMENT,
        classification_confidence=0.97,
        upload_source=UploadSource.USER_UPLOAD,
        uploaded_by_user_id=user.id,
    )

    await db_session.refresh(document)
    assert document.original_filename == "w2_2025.pdf"
    assert document.mime_type == "application/pdf"
    assert document.file_size_bytes == 88_213
    assert document.storage_path == "acme/lf-1/w2_2025.pdf"
    assert document.document_type == "w2"
    assert document.category is DocumentCategory.INCOME_EMPLOYMENT
    assert document.classification_confidence == pytest.approx(0.97)
    assert document.upload_source is UploadSource.USER_UPLOAD
    assert document.uploaded_by_user_id == user.id


async def test_status_defaults_to_pending(db_session: AsyncSession) -> None:
    """A freshly created document has status PENDING and no classification yet."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    document = await _add_document(db_session, loan_file)

    await db_session.refresh(document)
    assert document.status is DocumentStatus.PENDING
    assert document.document_type is None
    assert document.category is None
    assert document.classification_confidence is None
    assert document.processing_error is None


async def test_document_type_is_a_flexible_string(db_session: AsyncSession) -> None:
    """document_type accepts any string — it is not constrained to an enum."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    for value in ("pay_stub", "some_custom_type", "1099-misc"):
        document = await _add_document(db_session, loan_file, document_type=value)
        await db_session.refresh(document)
        assert document.document_type == value


async def test_all_categories_accepted(db_session: AsyncSession) -> None:
    """Every one of the eight categories is a valid value."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    for category in DocumentCategory:
        document = await _add_document(db_session, loan_file, category=category)
        await db_session.refresh(document)
        assert document.category is category


async def test_category_check_constraint_rejects_invalid_value(db_session: AsyncSession) -> None:
    """The DB CHECK constraint rejects an out-of-range category."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    document = await _add_document(db_session, loan_file)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE documents SET category = :bad WHERE id = :id"),
                {"bad": "tax_returns", "id": document.id},
            )


async def test_status_check_constraint_rejects_invalid_value(db_session: AsyncSession) -> None:
    """The DB CHECK constraint rejects an out-of-range status."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    document = await _add_document(db_session, loan_file)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE documents SET status = :bad WHERE id = :id"),
                {"bad": "uploading", "id": document.id},
            )


async def test_upload_source_check_constraint_rejects_invalid_value(
    db_session: AsyncSession,
) -> None:
    """The DB CHECK constraint rejects an out-of-range upload_source."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    document = await _add_document(db_session, loan_file)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE documents SET upload_source = :bad WHERE id = :id"),
                {"bad": "fax", "id": document.id},
            )


async def test_uploaded_by_is_set_for_user_upload(db_session: AsyncSession) -> None:
    """A USER_UPLOAD document links to the uploading user."""
    company = await _make_company(db_session, "acme")
    user = await _make_user(db_session, company, "u@acme.test")
    loan_file = await _make_loan_file(db_session, company)
    document = await _add_document(
        db_session,
        loan_file,
        upload_source=UploadSource.USER_UPLOAD,
        uploaded_by_user_id=user.id,
    )

    await db_session.refresh(document)
    assert document.uploaded_by_user_id == user.id


async def test_uploaded_by_is_null_for_borrower_inbox(db_session: AsyncSession) -> None:
    """A BORROWER_INBOX document has no user actor (uploaded_by is null)."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    document = await _add_document(
        db_session,
        loan_file,
        upload_source=UploadSource.BORROWER_INBOX,
        uploaded_by_user_id=None,
    )

    await db_session.refresh(document)
    assert document.upload_source is UploadSource.BORROWER_INBOX
    assert document.uploaded_by_user_id is None


async def test_relationships_load(db_session: AsyncSession) -> None:
    """document.loan_file, document.uploaded_by, and loan_file.documents load."""
    company = await _make_company(db_session, "acme")
    user = await _make_user(db_session, company, "u@acme.test")
    loan_file = await _make_loan_file(db_session, company)
    document = await _add_document(db_session, loan_file, uploaded_by_user_id=user.id)

    stmt = (
        select(Document)
        .where(Document.id == document.id)
        .options(selectinload(Document.loan_file), selectinload(Document.uploaded_by))
    )
    loaded = (await db_session.scalars(stmt)).one()
    assert loaded.loan_file.id == loan_file.id
    assert loaded.uploaded_by is not None
    assert loaded.uploaded_by.id == user.id

    file_stmt = (
        select(LoanFile)
        .where(LoanFile.id == loan_file.id)
        .options(selectinload(LoanFile.documents))
    )
    loaded_file = (await db_session.scalars(file_stmt)).one()
    assert document.id in {d.id for d in loaded_file.documents}


async def test_multiple_documents_per_loan_file(db_session: AsyncSession) -> None:
    """loan_file.documents returns every document attached to the file."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    doc1 = await _add_document(db_session, loan_file, original_filename="a.pdf")
    doc2 = await _add_document(db_session, loan_file, original_filename="b.pdf")
    doc3 = await _add_document(db_session, loan_file, original_filename="c.pdf")

    stmt = (
        select(LoanFile)
        .where(LoanFile.id == loan_file.id)
        .options(selectinload(LoanFile.documents))
    )
    loaded = (await db_session.scalars(stmt)).one()
    assert {d.id for d in loaded.documents} == {doc1.id, doc2.id, doc3.id}


async def test_soft_delete_and_only_active(db_session: AsyncSession) -> None:
    """Soft delete sets deleted_at; only_active() filters the document out."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    live = await _add_document(db_session, loan_file, original_filename="live.pdf")
    gone = await _add_document(db_session, loan_file, original_filename="gone.pdf")

    gone.deleted_at = utcnow()
    await db_session.flush()
    assert gone.is_deleted is True

    stmt = only_active(select(Document), Document)
    ids = {d.id for d in (await db_session.scalars(stmt)).all()}
    assert live.id in ids
    assert gone.id not in ids


async def test_cascade_delete_with_loan_file(db_session: AsyncSession) -> None:
    """Hard-deleting a loan file cascades to its documents (owned child)."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    document = await _add_document(db_session, loan_file)
    doc_id = document.id

    # Hard delete the file; the FK ondelete=CASCADE removes its documents.
    await db_session.delete(loan_file)
    await db_session.flush()

    remaining = await db_session.scalar(select(Document).where(Document.id == doc_id))
    assert remaining is None


async def test_documents_are_isolated_by_company_through_their_loan_file(
    db_session: AsyncSession,
) -> None:
    """Documents carry no company_id; isolation is transitive via the loan file.

    A query scoped to company A's loan files must never surface company B's
    documents (ADR-052).
    """
    company_a = await _make_company(db_session, "company-a")
    company_b = await _make_company(db_session, "company-b")
    file_a = await _make_loan_file(db_session, company_a)
    file_b = await _make_loan_file(db_session, company_b)

    doc_a = await _add_document(db_session, file_a, original_filename="a.pdf")
    doc_b = await _add_document(db_session, file_b, original_filename="b.pdf")

    stmt_a = scope_to_company(
        select(Document).join(LoanFile, Document.loan_file_id == LoanFile.id),
        LoanFile,
        company_a.id,
    )
    ids_a = {d.id for d in (await db_session.scalars(stmt_a)).all()}
    assert ids_a == {doc_a.id}
    assert doc_b.id not in ids_a

    stmt_b = scope_to_company(
        select(Document).join(LoanFile, Document.loan_file_id == LoanFile.id),
        LoanFile,
        company_b.id,
    )
    ids_b = {d.id for d in (await db_session.scalars(stmt_b)).all()}
    assert ids_b == {doc_b.id}
    assert ids_a.isdisjoint(ids_b)

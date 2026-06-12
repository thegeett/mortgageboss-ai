"""Service-layer tests for documents (LP-36).

Cover the create/list/soft-delete service functions, the upload validator
(size + type + magic bytes), and — the security crux — the flat-route scoping
gate :func:`get_document_for_company`, which must return ``None`` for another
company's document.
"""

from uuid import uuid4

import pytest
from app.core.security import hash_password
from app.models import Company, User, UserRole
from app.models.document import DocumentStatus, UploadSource
from app.services.documents import (
    MAX_FILE_SIZE_BYTES,
    DocumentValidationError,
    create_document,
    get_document_for_company,
    list_documents,
    soft_delete_document,
    validate_upload,
)
from app.services.loan_files import create_loan_file
from sqlalchemy.ext.asyncio import AsyncSession

# Minimal valid magic-byte headers — enough for the signature checks.
PDF_BYTES = b"%PDF-1.7\n%minimal\n"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 16


async def _company(db: AsyncSession, *, slug: str) -> tuple[Company, User]:
    company = Company(name=slug.title(), slug=slug)
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id,
        email=f"u@{slug}.com",
        hashed_password=hash_password("irrelevant"),
        first_name="Test",
        last_name="User",
        role=UserRole.PROCESSOR,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return company, user


# --------------------------------------------------------------------------- #
# validate_upload
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("content", "declared"),
    [
        (PDF_BYTES, "application/pdf"),
        (PNG_BYTES, "image/png"),
        (JPEG_BYTES, "image/jpeg"),
        (PDF_BYTES, "application/pdf; charset=binary"),  # parameter stripped
    ],
)
def test_validate_upload_accepts_allowed_types(content: bytes, declared: str) -> None:
    assert validate_upload(content=content, declared_content_type=declared) in {
        "application/pdf",
        "image/png",
        "image/jpeg",
    }


def test_validate_upload_rejects_disallowed_type() -> None:
    with pytest.raises(DocumentValidationError) as exc:
        validate_upload(content=b"hello text", declared_content_type="text/plain")
    assert exc.value.http_status == 415


def test_validate_upload_rejects_content_type_spoofing() -> None:
    # Declares PDF but the bytes are a PNG — magic-byte check must reject it.
    with pytest.raises(DocumentValidationError) as exc:
        validate_upload(content=PNG_BYTES, declared_content_type="application/pdf")
    assert exc.value.http_status == 415


def test_validate_upload_rejects_oversize() -> None:
    big = b"%PDF" + b"\x00" * (MAX_FILE_SIZE_BYTES + 1)
    with pytest.raises(DocumentValidationError) as exc:
        validate_upload(content=big, declared_content_type="application/pdf")
    assert exc.value.http_status == 413


# --------------------------------------------------------------------------- #
# create / list / soft-delete
# --------------------------------------------------------------------------- #


async def test_create_document_is_pending(db_session: AsyncSession) -> None:
    company, user = await _company(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc_id = uuid4()
    document = await create_document(
        db_session,
        loan_file=loan_file,
        document_id=doc_id,
        filename="paystub.pdf",
        mime_type="application/pdf",
        size=len(PDF_BYTES),
        storage_path=f"{company.id}/{loan_file.id}/{doc_id}.pdf",
        uploaded_by_user_id=user.id,
    )
    assert document.id == doc_id
    assert document.status == DocumentStatus.PENDING
    assert document.upload_source == UploadSource.USER_UPLOAD
    assert document.uploaded_by_user_id == user.id
    assert document.loan_file_id == loan_file.id


async def test_list_documents_excludes_soft_deleted(db_session: AsyncSession) -> None:
    company, user = await _company(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)

    async def _add(name: str):
        did = uuid4()
        return await create_document(
            db_session,
            loan_file=loan_file,
            document_id=did,
            filename=name,
            mime_type="application/pdf",
            size=10,
            storage_path=f"{company.id}/{loan_file.id}/{did}.pdf",
            uploaded_by_user_id=user.id,
        )

    keep = await _add("keep.pdf")
    drop = await _add("drop.pdf")
    await soft_delete_document(db_session, document=drop)

    listed = await list_documents(db_session, loan_file_id=loan_file.id)
    ids = {d.id for d in listed}
    assert keep.id in ids
    assert drop.id not in ids


async def test_soft_delete_sets_deleted_at(db_session: AsyncSession) -> None:
    company, user = await _company(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    did = uuid4()
    document = await create_document(
        db_session,
        loan_file=loan_file,
        document_id=did,
        filename="x.pdf",
        mime_type="application/pdf",
        size=10,
        storage_path=f"{company.id}/{loan_file.id}/{did}.pdf",
        uploaded_by_user_id=user.id,
    )
    await soft_delete_document(db_session, document=document)
    assert document.deleted_at is not None


# --------------------------------------------------------------------------- #
# get_document_for_company — the flat-route scoping gate
# --------------------------------------------------------------------------- #


async def test_get_document_for_company_returns_owned(db_session: AsyncSession) -> None:
    company, user = await _company(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    did = uuid4()
    await create_document(
        db_session,
        loan_file=loan_file,
        document_id=did,
        filename="x.pdf",
        mime_type="application/pdf",
        size=10,
        storage_path=f"{company.id}/{loan_file.id}/{did}.pdf",
        uploaded_by_user_id=user.id,
    )
    found = await get_document_for_company(db_session, document_id=did, company_id=company.id)
    assert found is not None and found.id == did


async def test_get_document_for_company_rejects_other_company(db_session: AsyncSession) -> None:
    """The crux: another company's document is invisible by id (returns None)."""
    company_a, user_a = await _company(db_session, slug="company-a")
    company_b, _user_b = await _company(db_session, slug="company-b")
    a_file = await create_loan_file(db_session, company_id=company_a.id)
    did = uuid4()
    await create_document(
        db_session,
        loan_file=a_file,
        document_id=did,
        filename="x.pdf",
        mime_type="application/pdf",
        size=10,
        storage_path=f"{company_a.id}/{a_file.id}/{did}.pdf",
        uploaded_by_user_id=user_a.id,
    )
    # Company B asking for Company A's document id → None.
    assert (
        await get_document_for_company(db_session, document_id=did, company_id=company_b.id) is None
    )


async def test_get_document_for_company_excludes_soft_deleted(db_session: AsyncSession) -> None:
    company, user = await _company(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    did = uuid4()
    document = await create_document(
        db_session,
        loan_file=loan_file,
        document_id=did,
        filename="x.pdf",
        mime_type="application/pdf",
        size=10,
        storage_path=f"{company.id}/{loan_file.id}/{did}.pdf",
        uploaded_by_user_id=user.id,
    )
    await soft_delete_document(db_session, document=document)
    assert (
        await get_document_for_company(db_session, document_id=did, company_id=company.id) is None
    )

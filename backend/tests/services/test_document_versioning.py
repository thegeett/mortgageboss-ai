"""LP-71 document versioning (Model C) — explicit replace.

Covers: explicit replace (old → historical, new → current, both kept, version chain,
the satisfied need re-opens to re-evaluate); new uploads are standalone/current
(multiples are NOT auto-replaced — no replacement assumption); version_count.
"""

from uuid import uuid4

from app.core.security import hash_password
from app.models import Company, User, UserRole
from app.models.document import Document, DocumentStatus, UploadSource
from app.models.needs_item import NeedsItemStatus
from app.services.document_versioning import supersede_document, version_count
from app.services.loan_files import create_loan_file
from app.services.needs_items import create_needs_item
from sqlalchemy.ext.asyncio import AsyncSession


async def _loan_file(db: AsyncSession, slug: str = "acme"):
    company = Company(name=slug.title(), slug=slug)
    db.add(company)
    await db.flush()
    db.add(
        User(
            company_id=company.id,
            email=f"u@{slug}.com",
            hashed_password=hash_password("x"),
            first_name="T",
            last_name="U",
            role=UserRole.PROCESSOR,
            is_active=True,
        )
    )
    await db.flush()
    return await create_loan_file(db, company_id=company.id)


async def _document(db: AsyncSession, loan_file_id, *, document_type: str = "pay_stub") -> Document:
    doc = Document(
        id=uuid4(),
        loan_file_id=loan_file_id,
        original_filename="paystub.pdf",
        mime_type="application/pdf",
        file_size_bytes=10,
        storage_path=f"{loan_file_id}/{uuid4()}.pdf",
        document_type=document_type,
        status=DocumentStatus.COMPLETED,
        upload_source=UploadSource.USER_UPLOAD,
    )
    db.add(doc)
    await db.flush()
    return doc


async def test_explicit_replace_supersedes_old_keeps_both(db_session: AsyncSession) -> None:
    lf = await _loan_file(db_session)
    old = await _document(db_session, lf.id)
    new = await _document(db_session, lf.id)

    await supersede_document(db_session, old_document=old, new_document=new)

    # Old → historical, new → current; both kept.
    assert old.is_current is False
    assert new.is_current is True
    # The version chain: same group (originating at the first doc), v2, links back.
    assert old.version_group_id == old.id
    assert new.version_group_id == old.id
    assert new.version == 2
    assert new.supersedes_document_id == old.id
    # Both rows still active (audit).
    assert old.deleted_at is None and new.deleted_at is None
    assert await version_count(db_session, document=new) == 2


async def test_replace_reopens_the_satisfied_need(db_session: AsyncSession) -> None:
    """The need the old document satisfied re-evaluates against the new current version."""
    lf = await _loan_file(db_session)
    old = await _document(db_session, lf.id, document_type="pay_stub")
    need = await create_needs_item(
        db_session, loan_file_id=lf.id, title="Pay stubs", needs_type="pay_stub"
    )
    # The old document had satisfied the need.
    need.status = NeedsItemStatus.VERIFIED
    need.satisfied_by_document_id = old.id
    await db_session.flush()

    new = await _document(db_session, lf.id, document_type="pay_stub")
    await supersede_document(db_session, old_document=old, new_document=new)

    # Re-opened: PENDING, link cleared — the new doc's pipeline will re-satisfy it.
    assert need.status is NeedsItemStatus.PENDING
    assert need.satisfied_by_document_id is None
    assert need.satisfied_at is None


async def test_multiples_are_not_auto_replaced(db_session: AsyncSession) -> None:
    """Two same-type uploads are a SET, not a replacement — both current, standalone."""
    lf = await _loan_file(db_session)
    first = await _document(db_session, lf.id, document_type="bank_statement")
    second = await _document(db_session, lf.id, document_type="bank_statement")

    # No supersede happened: both current, standalone (no version group), v1.
    assert first.is_current is True and second.is_current is True
    assert first.version_group_id is None and second.version_group_id is None
    assert first.version == 1 and second.version == 1
    assert await version_count(db_session, document=first) == 1

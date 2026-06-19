"""Composable entity factories for the integration suite (LP-45).

Minimal async helpers that create real rows in the test database. Each takes the
test ``db`` session and ``flush``es (never commits — the suite's outer
transaction is rolled back per test). They build the smallest valid entity and
let callers override the fields a test actually cares about.

Kept deliberately plain (functions, not fixtures) so flow/isolation tests can
compose them inline:  ``doc = await make_document(db, loan_file=lf, company=co)``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.models import Borrower, Company, Lender, Property, User, UserRole
from app.models.document import Document, DocumentCategory, DocumentStatus, UploadSource
from app.models.extraction import Extraction, ExtractionStatus
from app.models.loan_file import LoanFile
from app.models.needs_item import (
    NeedsItem,
    NeedsItemOrigin,
    NeedsItemPriority,
    NeedsItemStatus,
)
from app.services.loan_files import create_loan_file
from app.storage import get_storage_backend
from sqlalchemy.ext.asyncio import AsyncSession

# A known password so login-flow tests can authenticate the created user.
DEFAULT_PASSWORD = "Sup3r-secret-pw"  # pragma: allowlist secret
# Minimal valid PDF (magic bytes) for real upload/storage round-trips.
PDF_BYTES = b"%PDF-1.7\n%integration test\n"


async def make_company(db: AsyncSession, *, slug: str = "acme") -> Company:
    company = Company(name=slug.replace("-", " ").title(), slug=slug)
    db.add(company)
    await db.flush()
    return company


async def make_user(
    db: AsyncSession,
    *,
    company: Company,
    email: str | None = None,
    role: UserRole = UserRole.PROCESSOR,
    password: str = DEFAULT_PASSWORD,
) -> User:
    user = User(
        company_id=company.id,
        email=email or f"user-{uuid4().hex[:8]}@{company.slug}.com",
        hashed_password=hash_password(password),
        first_name="Test",
        last_name="User",
        role=role,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


def token_for(user: User) -> str:
    """A valid Bearer access token for ``user`` (real JWT minting)."""
    return create_access_token(user.id)


async def make_loan_file(
    db: AsyncSession, *, company: Company, lender_id: UUID | None = None
) -> LoanFile:
    return await create_loan_file(db, company_id=company.id, lender_id=lender_id)


async def make_borrower(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    ssn: str | None = "123-45-6789",
    first_name: str = "Jane",
    last_name: str = "Borrower",
) -> Borrower:
    borrower = Borrower(
        loan_file_id=loan_file.id,
        first_name=first_name,
        last_name=last_name,
        ssn=ssn,  # stored encrypted (EncryptedString); response masks to last-4
    )
    db.add(borrower)
    await db.flush()
    return borrower


async def make_property(db: AsyncSession, *, loan_file: LoanFile) -> Property:
    prop = Property(
        loan_file_id=loan_file.id,
        address_line="123 Main St",
        city="Springfield",
        state="IL",
        postal_code="62704",
    )
    db.add(prop)
    await db.flush()
    return prop


async def make_needs_item(
    db: AsyncSession, *, loan_file: LoanFile, title: str = "Most recent W-2"
) -> NeedsItem:
    item = NeedsItem(
        loan_file_id=loan_file.id,
        title=title,
        category=DocumentCategory.INCOME_EMPLOYMENT,
        origin=NeedsItemOrigin.MANUAL,
        priority=NeedsItemPriority.STANDARD,
        status=NeedsItemStatus.PENDING,
    )
    db.add(item)
    await db.flush()
    return item


async def make_lender(db: AsyncSession, *, company: Company, name: str = "Acme Bank") -> Lender:
    lender = Lender(company_id=company.id, name=name, slug=name.lower().replace(" ", "-"))
    db.add(lender)
    await db.flush()
    return lender


async def make_document(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    company: Company,
    filename: str = "document.pdf",
    content: bytes = PDF_BYTES,
    mime_type: str = "application/pdf",
    document_type: str | None = None,
    category: DocumentCategory | None = None,
    status: DocumentStatus = DocumentStatus.PENDING,
    uploaded_by: User | None = None,
) -> Document:
    """Create a Document with its bytes actually stored (so download works).

    Requires the storage temp-dir fixture to be active (it is, autouse).
    """
    document_id = uuid4()
    storage_path = await get_storage_backend().save(
        company_id=company.id,
        file_id=loan_file.id,
        document_id=document_id,
        filename=filename,
        content=content,
    )
    document = Document(
        id=document_id,
        loan_file_id=loan_file.id,
        original_filename=filename,
        mime_type=mime_type,
        file_size_bytes=len(content),
        storage_path=storage_path,
        document_type=document_type,
        category=category,
        status=status,
        upload_source=UploadSource.USER_UPLOAD,
        uploaded_by_user_id=uploaded_by.id if uploaded_by else None,
    )
    db.add(document)
    await db.flush()
    return document


async def make_extraction(
    db: AsyncSession,
    *,
    document: Document,
    data: dict[str, Any],
    status: ExtractionStatus = ExtractionStatus.SUCCEEDED,
    version: int = 1,
    model_used: str = "claude-test",
) -> Extraction:
    extraction = Extraction(
        document_id=document.id,
        version=version,
        is_current=True,
        extracted_data=data,
        extraction_status=status,
        model_used=model_used,
    )
    db.add(extraction)
    await db.flush()
    return extraction

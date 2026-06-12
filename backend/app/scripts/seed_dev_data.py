"""Seed the dev database with realistic demo data (LP-48). DEV-ONLY.

Usage::

    uv run python -m app.scripts.seed_dev_data          # check-and-skip (safe re-run)
    uv run python -m app.scripts.seed_dev_data --reset  # clear seeded data + recreate

Creates one company, an **admin** + a **processor** user (known dev credentials,
printed at the end), the **UWM** and **Sun-West** lenders, and **three loan files
in various workflow states** (fresh / mid / near-submission) — each with a
fake-PII borrower (synthetic SSN written through the encrypted column), a
property, loan details, documents in various processing states with
**pre-canned** extractions (no AI calls — the extraction JSON is built from the
real LP-39a Pydantic models so the shape can't drift), needs items, and activity.

Safety:
- **Production guard** — refuses to run if ``settings`` says production.
- **No real PII** — synthetic names/addresses and never-issued ``900-`` SSNs.
- **No AI / no key / no broker** — extractions are inserted directly.
- **Idempotent** — re-run is a safe no-op (check-and-skip by stable identifiers);
  ``--reset`` hard-clears the seeded company (and its storage) and recreates it.

Emails use a real ``.com`` TLD (Pydantic ``EmailStr`` rejects reserved
``.test``/``.example`` TLDs, and the login endpoint must accept these accounts).
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.extraction.bank_statement import BankStatementExtraction, Transaction
from app.ai.extraction.pay_stub import PayStubExtraction
from app.ai.extraction.shape import CatchAllField, CatchAllSection, SourceLocation, TypedField
from app.ai.extraction.w2 import W2Extraction
from app.core.config import settings
from app.core.database import async_session_maker
from app.core.security import hash_password
from app.models.activity_log import ActivityType
from app.models.base import utcnow
from app.models.borrower import Borrower, MaritalStatus
from app.models.company import Company
from app.models.document import Document, DocumentCategory, DocumentStatus, UploadSource
from app.models.extraction import ExtractionStatus
from app.models.lender import Lender, LoanProgram
from app.models.loan_file import LoanFile, LoanFileStatus, LoanPurpose
from app.models.needs_item import (
    NeedsItem,
    NeedsItemOrigin,
    NeedsItemPriority,
    NeedsItemStatus,
)
from app.models.property import OccupancyType, Property, PropertyType
from app.models.user import User, UserRole
from app.services.activity_log import log_activity
from app.services.extractions import create_extraction_version
from app.services.loan_files import create_loan_file
from app.storage import get_storage_backend

logger = structlog.get_logger(__name__)

# --- Stable identifiers (idempotency keys) + DEV-ONLY credentials ----------- #
# These passwords are local-dev conveniences, not secrets.
_COMPANY_NAME = "Summit Mortgage Processing"
_COMPANY_SLUG = "summit"
_ADMIN_EMAIL = "admin@summit-demo.com"
_PROCESSOR_EMAIL = "priya@summit-demo.com"
_SEED_PASSWORD = "DevPassword123!"  # pragma: allowlist secret  (DEV-ONLY, documented)
_MODEL_USED = "claude-sonnet-4-6"  # plausible placeholder for seeded extractions


# --------------------------------------------------------------------------- #
# Minimal placeholder PDF (so a seeded document is downloadable)
# --------------------------------------------------------------------------- #


def _make_pdf(title: str) -> bytes:
    """A tiny but valid one-page PDF showing ``title`` — a stand-in for real
    document bytes so the seeded documents are downloadable. Not real content."""
    safe = title.replace("(", "").replace(")", "").replace("\\", "")
    stream = f"BT /F1 18 Tf 72 720 Td ({safe}) Tj ET".encode("latin-1", "replace")
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += str(i).encode() + b" 0 obj\n" + body + b"\nendobj\n"
    xref_pos = len(pdf)
    pdf += b"xref\n0 " + str(len(objects) + 1).encode() + b"\n"
    pdf += b"0000000000 65535 f \n"
    for off in offsets:
        pdf += f"{off:010d} 00000 n \n".encode()
    pdf += (
        b"trailer\n<< /Size "
        + str(len(objects) + 1).encode()
        + b" /Root 1 0 R >>\nstartxref\n"
        + str(xref_pos).encode()
        + b"\n%%EOF"
    )
    return bytes(pdf)


# --------------------------------------------------------------------------- #
# Pre-canned extractions — built from the REAL LP-39a models, then serialized,
# so the stored JSON always matches the live extraction shape. NO AI.
# --------------------------------------------------------------------------- #


def _src(snippet: str, page: int = 1) -> SourceLocation:
    return SourceLocation(page=page, snippet=snippet)


def _paystub_extraction() -> PayStubExtraction:
    return PayStubExtraction(
        employer_name=TypedField(
            value="Cascade Logistics LLC", source=_src("Cascade Logistics LLC")
        ),
        employee_name=TypedField(value="Jordan A. Rivera", source=_src("Jordan A. Rivera")),
        pay_period_start=TypedField(
            value=date(2026, 3, 1), source=_src("Period Beginning 03/01/2026")
        ),
        pay_period_end=TypedField(value=date(2026, 3, 15), source=_src("Period Ending 03/15/2026")),
        pay_date=TypedField(value=date(2026, 3, 20), source=_src("Pay Date 03/20/2026")),
        gross_pay=TypedField(value=Decimal("4200.00"), source=_src("Gross Pay 4,200.00")),
        net_pay=TypedField(value=Decimal("3088.42"), source=_src("Net Pay 3,088.42")),
        ytd_gross=TypedField(value=Decimal("25200.00"), source=_src("YTD Gross 25,200.00")),
        pay_frequency=TypedField(value="bi-weekly", source=_src("Bi-Weekly")),
        hours=TypedField(value=Decimal("80.00"), source=_src("Hours 80.00")),
        rate=TypedField(value=Decimal("52.50"), source=_src("Rate 52.50")),
        additional_sections=[
            CatchAllSection(
                section="Deductions",
                fields=[
                    CatchAllField(label="401(k)", value="210.00", source=_src("401(k) 210.00")),
                    CatchAllField(label="Medical", value="142.30", source=_src("Medical 142.30")),
                ],
            ),
            CatchAllSection(
                section="Taxes",
                fields=[
                    CatchAllField(label="Federal", value="512.88", source=_src("Federal 512.88")),
                    CatchAllField(label="State", value="246.40", source=_src("State 246.40")),
                ],
            ),
        ],
    )


def _w2_extraction() -> W2Extraction:
    return W2Extraction(
        tax_year=TypedField(value=2025, source=_src("2025")),
        employee_name=TypedField(value="Jordan A. Rivera", source=_src("Jordan A. Rivera")),
        # Synthetic, never-issued SSN (900- range). Captured masked-ish; display masks it.
        employee_ssn=TypedField(value="900-12-3456", source=_src("XXX-XX-3456")),
        employer_name=TypedField(
            value="Cascade Logistics LLC", source=_src("Cascade Logistics LLC")
        ),
        employer_ein=TypedField(value="00-1234567", source=_src("EIN 00-1234567")),
        wages_tips_other_comp=TypedField(value=Decimal("98500.00"), source=_src("Box 1 98,500.00")),
        federal_income_tax_withheld=TypedField(
            value=Decimal("14120.00"), source=_src("Box 2 14,120.00")
        ),
        social_security_wages=TypedField(value=Decimal("98500.00"), source=_src("Box 3 98,500.00")),
        social_security_tax_withheld=TypedField(
            value=Decimal("6107.00"), source=_src("Box 4 6,107.00")
        ),
        medicare_wages=TypedField(value=Decimal("98500.00"), source=_src("Box 5 98,500.00")),
        medicare_tax_withheld=TypedField(value=Decimal("1428.25"), source=_src("Box 6 1,428.25")),
        additional_sections=[
            CatchAllSection(
                section="State (Boxes 15-17)",
                fields=[
                    CatchAllField(label="State", value="WA", source=_src("WA")),
                    CatchAllField(label="State wages", value="98500.00", source=_src("98,500.00")),
                ],
            ),
        ],
    )


def _bank_statement_extraction() -> BankStatementExtraction:
    def _tx(day: int, desc: str, amount: str, kind: str, balance: str) -> Transaction:
        return Transaction(
            date=date(2026, 2, day),
            description=desc,
            amount=Decimal(amount),
            transaction_type=kind,
            running_balance=Decimal(balance),
            source=_src(desc),
        )

    return BankStatementExtraction(
        account_holder_name=TypedField(value="Morgan T. Ellis", source=_src("Morgan T. Ellis")),
        bank_name=TypedField(value="Evergreen Credit Union", source=_src("Evergreen Credit Union")),
        account_number_masked=TypedField(value="****6789", source=_src("Account ****6789")),
        account_type=TypedField(value="Checking", source=_src("Checking")),
        statement_period_start=TypedField(value=date(2026, 2, 1), source=_src("02/01/2026")),
        statement_period_end=TypedField(value=date(2026, 2, 28), source=_src("02/28/2026")),
        beginning_balance=TypedField(
            value=Decimal("8450.12"), source=_src("Beginning Balance 8,450.12")
        ),
        ending_balance=TypedField(
            value=Decimal("11230.55"), source=_src("Ending Balance 11,230.55")
        ),
        total_deposits=TypedField(value=Decimal("6400.00"), source=_src("Total Deposits 6,400.00")),
        total_withdrawals=TypedField(
            value=Decimal("3619.57"), source=_src("Total Withdrawals 3,619.57")
        ),
        transactions=[
            _tx(3, "Payroll Deposit - Cascade Logistics", "3200.00", "deposit", "11650.12"),
            _tx(7, "Mortgage Payment - Evergreen", "-1840.22", "withdrawal", "9809.90"),
            _tx(17, "Payroll Deposit - Cascade Logistics", "3200.00", "deposit", "13009.90"),
            _tx(24, "Auto Loan - Summit Auto", "-379.35", "withdrawal", "12630.55"),
            _tx(26, "Utilities - City Power", "-1400.00", "withdrawal", "11230.55"),
        ],
        additional_sections=[],
    )


# --------------------------------------------------------------------------- #
# get-or-create helpers (check-and-skip idempotency)
# --------------------------------------------------------------------------- #


async def _get_or_create_company(db: AsyncSession) -> tuple[Company, bool]:
    existing = await db.scalar(select(Company).where(Company.slug == _COMPANY_SLUG))
    if existing is not None:
        return existing, False
    company = Company(name=_COMPANY_NAME, slug=_COMPANY_SLUG, is_active=True)
    db.add(company)
    await db.flush()
    return company, True


async def _get_or_create_user(
    db: AsyncSession,
    *,
    company_id: UUID,
    email: str,
    first_name: str,
    last_name: str,
    role: UserRole,
) -> tuple[User, bool]:
    existing = await db.scalar(select(User).where(User.email == email))
    if existing is not None:
        return existing, False
    user = User(
        company_id=company_id,
        email=email,
        hashed_password=hash_password(_SEED_PASSWORD),
        first_name=first_name,
        last_name=last_name,
        role=role,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user, True


async def _get_or_create_lender(
    db: AsyncSession, *, company_id: UUID, name: str, slug: str, programs: list[str]
) -> tuple[Lender, bool]:
    existing = await db.scalar(
        select(Lender).where(Lender.company_id == company_id, Lender.slug == slug)
    )
    if existing is not None:
        return existing, False
    lender = Lender(
        company_id=company_id,
        name=name,
        slug=slug,
        supported_programs=programs,
        is_active=True,
    )
    db.add(lender)
    await db.flush()
    return lender, True


# --------------------------------------------------------------------------- #
# Entity builders
# --------------------------------------------------------------------------- #


async def _add_borrower(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    first_name: str,
    last_name: str,
    ssn: str,
    email: str,
    phone: str,
) -> Borrower:
    borrower = Borrower(
        loan_file_id=loan_file.id,
        first_name=first_name,
        last_name=last_name,
        ssn=ssn,  # synthetic; stored encrypted (EncryptedString)
        date_of_birth=date(1986, 7, 14),
        email=email,
        phone=phone,
        marital_status=MaritalStatus.MARRIED,
        is_primary=True,
        borrower_position=1,
    )
    db.add(borrower)
    await db.flush()
    return borrower


async def _add_property(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    address_line: str,
    city: str,
    state: str,
    postal_code: str,
    occupancy: OccupancyType,
    estimated_value: str,
    purchase_price: str | None,
) -> Property:
    prop = Property(
        loan_file_id=loan_file.id,
        address_line=address_line,
        city=city,
        state=state,
        postal_code=postal_code,
        property_type=PropertyType.SINGLE_FAMILY,
        occupancy_type=occupancy,
        estimated_value=Decimal(estimated_value),
        purchase_price=Decimal(purchase_price) if purchase_price else None,
    )
    db.add(prop)
    await db.flush()
    return prop


async def _add_document(
    db: AsyncSession,
    *,
    company: Company,
    loan_file: LoanFile,
    uploader: User,
    filename: str,
    document_type: str | None,
    category: DocumentCategory | None,
    status: DocumentStatus,
    confidence: float | None,
    processing_error: str | None = None,
) -> Document:
    """Create a Document with real stored bytes (a placeholder PDF) so download works."""
    document_id = uuid4()
    content = _make_pdf(f"DEMO {filename}")
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
        mime_type="application/pdf",
        file_size_bytes=len(content),
        storage_path=storage_path,
        document_type=document_type,
        category=category,
        classification_confidence=confidence,
        status=status,
        processing_error=processing_error,
        upload_source=UploadSource.USER_UPLOAD,
        uploaded_by_user_id=uploader.id,
    )
    db.add(document)
    await db.flush()
    return document


async def _add_need(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    title: str,
    category: DocumentCategory,
    status: NeedsItemStatus,
    priority: NeedsItemPriority = NeedsItemPriority.STANDARD,
    satisfied_by: Document | None = None,
) -> NeedsItem:
    item = NeedsItem(
        loan_file_id=loan_file.id,
        title=title,
        category=category,
        origin=NeedsItemOrigin.MANUAL,
        priority=priority,
        status=status,
        satisfied_by_document_id=satisfied_by.id if satisfied_by else None,
        satisfied_at=utcnow() if status == NeedsItemStatus.RECEIVED else None,
    )
    db.add(item)
    await db.flush()
    return item


# --------------------------------------------------------------------------- #
# The three loan files, in various workflow states
# --------------------------------------------------------------------------- #


async def _seed_loan_files(
    db: AsyncSession, *, company: Company, processor: User, uwm: Lender, sunwest: Lender
) -> int:
    """Create the three demo files (idempotent: skip if the company already has files)."""
    existing = await db.scalar(
        select(func.count())
        .select_from(LoanFile)
        .where(LoanFile.company_id == company.id, LoanFile.deleted_at.is_(None))
    )
    if existing:
        logger.info("seed_loan_files_skipped", existing=int(existing))
        return 0

    created = 0

    # --- File A — "just started": borrower/property/loan set, no documents yet --- #
    file_a = await create_loan_file(
        db,
        company_id=company.id,
        lender_id=uwm.id,
        loan_program=LoanProgram.CONVENTIONAL,
        loan_purpose=LoanPurpose.PURCHASE,
        loan_officer_name="Dana Brooks",
        loan_officer_email="dana.brooks@uwm-demo.com",
    )
    file_a.loan_amount = Decimal("425000.00")
    file_a.status = LoanFileStatus.DRAFT
    await db.flush()
    await _add_borrower(
        db,
        loan_file=file_a,
        first_name="Jordan",
        last_name="Rivera",
        ssn="900-12-3456",  # synthetic
        email="jordan.rivera@example.com",
        phone="(206) 555-0188",
    )
    await _add_property(
        db,
        loan_file=file_a,
        address_line="1420 Alder Court",
        city="Tacoma",
        state="WA",
        postal_code="98403",
        occupancy=OccupancyType.PRIMARY_RESIDENCE,
        estimated_value="530000.00",
        purchase_price="525000.00",
    )
    await log_activity(
        db,
        loan_file_id=file_a.id,
        activity_type=ActivityType.FILE_CREATED,
        summary="Loan file created",
        actor_user_id=processor.id,
    )
    await _add_need(
        db,
        loan_file=file_a,
        title="Most recent pay stub",
        category=DocumentCategory.INCOME_EMPLOYMENT,
        status=NeedsItemStatus.OUTSTANDING,
        priority=NeedsItemPriority.BLOCKING,
    )
    await _add_need(
        db,
        loan_file=file_a,
        title="Two most recent W-2s",
        category=DocumentCategory.INCOME_EMPLOYMENT,
        status=NeedsItemStatus.OUTSTANDING,
    )
    await _add_need(
        db,
        loan_file=file_a,
        title="Two months of bank statements",
        category=DocumentCategory.ASSETS,
        status=NeedsItemStatus.OUTSTANDING,
    )
    created += 1

    # --- File B — "mid-workflow": pay stub + W-2 processed, some needs satisfied --- #
    file_b = await create_loan_file(
        db,
        company_id=company.id,
        lender_id=sunwest.id,
        loan_program=LoanProgram.FHA,
        loan_purpose=LoanPurpose.PURCHASE,
        loan_officer_name="Marcus Vale",
        loan_officer_email="marcus.vale@sunwest-demo.com",
    )
    file_b.loan_amount = Decimal("312500.00")
    file_b.status = LoanFileStatus.IN_PROCESSING
    await db.flush()
    await _add_borrower(
        db,
        loan_file=file_b,
        first_name="Priya",
        last_name="Nair",
        ssn="900-44-7788",
        email="priya.nair@example.com",
        phone="(253) 555-0142",
    )
    await _add_property(
        db,
        loan_file=file_b,
        address_line="88 Marigold Way",
        city="Kent",
        state="WA",
        postal_code="98032",
        occupancy=OccupancyType.PRIMARY_RESIDENCE,
        estimated_value="365000.00",
        purchase_price="360000.00",
    )
    await log_activity(
        db,
        loan_file_id=file_b.id,
        activity_type=ActivityType.FILE_CREATED,
        summary="Loan file created",
        actor_user_id=processor.id,
    )
    paystub_b = await _add_completed_document(
        db,
        company=company,
        loan_file=file_b,
        uploader=processor,
        filename="rivera-paystub-mar.pdf",
        document_type="pay_stub",
        category=DocumentCategory.INCOME_EMPLOYMENT,
        extracted=_paystub_extraction().model_dump(mode="json"),
        tokens=1840,
        cost=0.0121,
    )
    w2_b = await _add_completed_document(
        db,
        company=company,
        loan_file=file_b,
        uploader=processor,
        filename="rivera-w2-2025.pdf",
        document_type="w2",
        category=DocumentCategory.INCOME_EMPLOYMENT,
        extracted=_w2_extraction().model_dump(mode="json"),
        tokens=1605,
        cost=0.0104,
    )
    await _add_need(
        db,
        loan_file=file_b,
        title="Most recent pay stub",
        category=DocumentCategory.INCOME_EMPLOYMENT,
        status=NeedsItemStatus.RECEIVED,
        satisfied_by=paystub_b,
    )
    await _add_need(
        db,
        loan_file=file_b,
        title="Two most recent W-2s",
        category=DocumentCategory.INCOME_EMPLOYMENT,
        status=NeedsItemStatus.RECEIVED,
        satisfied_by=w2_b,
    )
    await _add_need(
        db,
        loan_file=file_b,
        title="Two months of bank statements",
        category=DocumentCategory.ASSETS,
        status=NeedsItemStatus.OUTSTANDING,
        priority=NeedsItemPriority.BLOCKING,
    )
    await log_activity(
        db,
        loan_file_id=file_b.id,
        activity_type=ActivityType.NEEDS_ITEM_SATISFIED,
        summary="Need satisfied: Most recent pay stub",
        actor_user_id=processor.id,
    )
    created += 1

    # --- File C — "near submission": more docs incl. a NEEDS_REVIEW + a PENDING --- #
    file_c = await create_loan_file(
        db,
        company_id=company.id,
        lender_id=uwm.id,
        loan_program=LoanProgram.CONVENTIONAL,
        loan_purpose=LoanPurpose.REFINANCE,
        loan_officer_name="Dana Brooks",
        loan_officer_email="dana.brooks@uwm-demo.com",
    )
    file_c.loan_amount = Decimal("540000.00")
    file_c.status = LoanFileStatus.READY_TO_SUBMIT
    await db.flush()
    await _add_borrower(
        db,
        loan_file=file_c,
        first_name="Morgan",
        last_name="Ellis",
        ssn="900-31-9021",
        email="morgan.ellis@example.com",
        phone="(425) 555-0119",
    )
    await _add_property(
        db,
        loan_file=file_c,
        address_line="3307 Lakeshore Drive",
        city="Bellevue",
        state="WA",
        postal_code="98006",
        occupancy=OccupancyType.PRIMARY_RESIDENCE,
        estimated_value="720000.00",
        purchase_price=None,
    )
    await log_activity(
        db,
        loan_file_id=file_c.id,
        activity_type=ActivityType.FILE_CREATED,
        summary="Loan file created",
        actor_user_id=processor.id,
    )
    bank_c = await _add_completed_document(
        db,
        company=company,
        loan_file=file_c,
        uploader=processor,
        filename="ellis-bank-feb.pdf",
        document_type="bank_statement",
        category=DocumentCategory.ASSETS,
        extracted=_bank_statement_extraction().model_dump(mode="json"),
        tokens=2310,
        cost=0.0152,
    )
    # A low-confidence pay stub flagged for human review (demos the LP-44 override).
    review_doc = await _add_document(
        db,
        company=company,
        loan_file=file_c,
        uploader=processor,
        filename="ellis-paystub-scan.pdf",
        document_type="pay_stub",
        category=DocumentCategory.INCOME_EMPLOYMENT,
        status=DocumentStatus.NEEDS_REVIEW,
        confidence=0.42,
        processing_error="Low classification confidence — please confirm the document type.",
    )
    await create_extraction_version(
        db,
        document_id=review_doc.id,
        extracted_data=_paystub_extraction().model_dump(mode="json"),
        extraction_status=ExtractionStatus.PARTIAL,
        model_used=_MODEL_USED,
        tokens_used=1500,
        cost_estimate=0.0098,
        error_detail="Some fields were low-confidence; flagged for review.",
    )
    # A document still waiting in the queue (PENDING, no extraction yet).
    await _add_document(
        db,
        company=company,
        loan_file=file_c,
        uploader=processor,
        filename="ellis-id.pdf",
        document_type=None,
        category=None,
        status=DocumentStatus.PENDING,
        confidence=None,
    )
    await _add_need(
        db,
        loan_file=file_c,
        title="Two months of bank statements",
        category=DocumentCategory.ASSETS,
        status=NeedsItemStatus.RECEIVED,
        satisfied_by=bank_c,
    )
    await _add_need(
        db,
        loan_file=file_c,
        title="Government-issued photo ID",
        category=DocumentCategory.BORROWER_INFO,
        status=NeedsItemStatus.REQUESTED,
    )
    await _add_need(
        db,
        loan_file=file_c,
        title="Homeowners insurance declaration",
        category=DocumentCategory.PROPERTY,
        status=NeedsItemStatus.OUTSTANDING,
    )
    for doc in (bank_c, review_doc):
        await log_activity(
            db,
            loan_file_id=file_c.id,
            activity_type=ActivityType.DOCUMENT_PROCESSED,
            summary=f"Document processed: {doc.original_filename}",
            actor_user_id=processor.id,
        )
    created += 1

    return created


async def _add_completed_document(
    db: AsyncSession,
    *,
    company: Company,
    loan_file: LoanFile,
    uploader: User,
    filename: str,
    document_type: str,
    category: DocumentCategory,
    extracted: dict[str, object],
    tokens: int,
    cost: float,
) -> Document:
    """A COMPLETED document plus its current, pre-canned extraction (no AI)."""
    document = await _add_document(
        db,
        company=company,
        loan_file=loan_file,
        uploader=uploader,
        filename=filename,
        document_type=document_type,
        category=category,
        status=DocumentStatus.COMPLETED,
        confidence=0.96,
    )
    await create_extraction_version(
        db,
        document_id=document.id,
        extracted_data=extracted,
        extraction_status=ExtractionStatus.SUCCEEDED,
        model_used=_MODEL_USED,
        tokens_used=tokens,
        cost_estimate=cost,
    )
    await log_activity(
        db,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.DOCUMENT_UPLOADED,
        summary=f"Document uploaded: {filename}",
        actor_user_id=uploader.id,
    )
    return document


# --------------------------------------------------------------------------- #
# Reset (hard-clear the seeded company + its storage)
# --------------------------------------------------------------------------- #


async def _clear_seed(db: AsyncSession) -> None:
    company = await db.scalar(select(Company).where(Company.slug == _COMPANY_SLUG))
    if company is None:
        logger.info("seed_reset_nothing_to_clear")
        return
    company_id = company.id
    # Deleting loan files cascades (DB ondelete=CASCADE) to borrowers, properties,
    # documents (→ extractions), needs, and activity. Then users, lenders, company.
    await db.execute(delete(LoanFile).where(LoanFile.company_id == company_id))
    await db.execute(delete(User).where(User.company_id == company_id))
    await db.execute(delete(Lender).where(Lender.company_id == company_id))
    await db.execute(delete(Company).where(Company.id == company_id))
    await db.flush()
    _clear_company_storage(company_id)
    logger.info("seed_reset_done", company_id=str(company_id))


def _clear_company_storage(company_id: UUID) -> None:
    """Best-effort removal of the seeded company's local storage subtree."""
    if settings.storage_backend != "local":
        return
    company_dir = Path(settings.storage_local_path) / str(company_id)
    if company_dir.exists():
        shutil.rmtree(company_dir, ignore_errors=True)
        logger.info("seed_reset_storage_cleared", path=str(company_dir))


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


async def seed(*, reset: bool) -> None:
    async with async_session_maker() as db:
        if reset:
            await _clear_seed(db)

        company, company_created = await _get_or_create_company(db)
        admin, admin_created = await _get_or_create_user(
            db,
            company_id=company.id,
            email=_ADMIN_EMAIL,
            first_name="Avery",
            last_name="Stone",
            role=UserRole.ADMIN,
        )
        processor, processor_created = await _get_or_create_user(
            db,
            company_id=company.id,
            email=_PROCESSOR_EMAIL,
            first_name="Priya",
            last_name="Desai",
            role=UserRole.PROCESSOR,
        )
        uwm, uwm_created = await _get_or_create_lender(
            db,
            company_id=company.id,
            name="UWM",
            slug="uwm",
            programs=["conventional", "fha"],
        )
        sunwest, sunwest_created = await _get_or_create_lender(
            db,
            company_id=company.id,
            name="Sun-West",
            slug="sun-west",
            programs=["fha"],
        )
        files_created = await _seed_loan_files(
            db, company=company, processor=processor, uwm=uwm, sunwest=sunwest
        )
        await db.commit()

    logger.info(
        "seed_complete",
        company_created=company_created,
        admin_created=admin_created,
        processor_created=processor_created,
        uwm_created=uwm_created,
        sunwest_created=sunwest_created,
        loan_files_created=files_created,
    )
    _print_summary(
        company_created=company_created,
        files_created=files_created,
        admin_id=str(admin.id),
        processor_id=str(processor.id),
    )


def _print_summary(
    *, company_created: bool, files_created: int, admin_id: str, processor_id: str
) -> None:
    state = "created" if company_created else "already existed"
    print("\n=== Dev seed complete (DEV-ONLY) ===")
    print(f"Company: {_COMPANY_NAME} (slug: {_COMPANY_SLUG}) [{state}]")
    print(f"Loan files seeded this run: {files_created} (re-runs skip existing)")
    print("Login (DEV-ONLY passwords):")
    print(f"  Admin:     {_ADMIN_EMAIL} / {_SEED_PASSWORD}")
    print(f"  Processor: {_PROCESSOR_EMAIL} / {_SEED_PASSWORD}")
    print("Extractions are pre-canned (no AI); all PII is synthetic.")


def main() -> None:
    # PRODUCTION GUARD — refuse to write anything in production.
    if settings.is_production:
        print("Refusing to seed: production environment detected. This script is DEV-ONLY.")
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Seed the dev database with demo data (DEV-ONLY).")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Hard-clear the seeded company (and its storage), then recreate it fresh.",
    )
    args = parser.parse_args()
    asyncio.run(seed(reset=args.reset))


if __name__ == "__main__":
    main()

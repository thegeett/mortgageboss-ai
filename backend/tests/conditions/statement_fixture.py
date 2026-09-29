"""Fictional Capital One ··9912 statements for Alex Rivera (ADR-405), as the extractor stores them.

LP-923's evidence checks read a bank statement's CURRENT EXTRACTION, so these build exactly that: a
`BankStatementExtraction` dumped to JSON, with `page_count_present` / `page_count_declared` as the
pipeline sets them. The figures are the Stage 3 screens' (LP-934's arithmetic):

- July 2026: ends $36,120.18 (the month already in the file when 6132 asks for "the next month").
- August 2026: the $2,850.00 earnest money check #1042 clears 08/06; payroll twice; a $4,000.00 mobile
  deposit on 08/21; ends $41,914.42 — so without the deposit $37,914.42, short of $38,210.40 (S3-08).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4

from app.ai.extraction.bank_statement import BankStatementExtraction, Transaction
from app.ai.extraction.shape import TypedField
from app.models.document import Document, DocumentStatus, UploadSource
from app.models.extraction import Extraction, ExtractionStatus
from app.models.loan_file import LoanFile
from sqlalchemy.ext.asyncio import AsyncSession


def _tx(on: date, description: str, amount: str, kind: str) -> Transaction:
    return Transaction(
        date=on, description=description, amount=Decimal(amount), transaction_type=kind
    )


JULY = [
    _tx(date(2026, 7, 1), "Payroll Deposit - Harbor Freight Lines", "2650.66", "deposit"),
    _tx(date(2026, 7, 15), "Payroll Deposit - Harbor Freight Lines", "2650.66", "deposit"),
    _tx(date(2026, 7, 20), "Rent - Palmetto Apartments", "-1450.00", "withdrawal"),
]
AUGUST = [
    _tx(date(2026, 8, 1), "Payroll Deposit - Harbor Freight Lines", "2650.66", "deposit"),
    _tx(date(2026, 8, 6), "Check 1042", "-2850.00", "withdrawal"),
    _tx(date(2026, 8, 15), "Payroll Deposit - Harbor Freight Lines", "2650.66", "deposit"),
    _tx(date(2026, 8, 21), "Mobile Deposit", "4000.00", "deposit"),
    _tx(date(2026, 8, 25), "Rent - Palmetto Apartments", "-1450.00", "withdrawal"),
]


def statement_data(
    *,
    start: date,
    end: date,
    ending: str,
    transactions: list[Transaction],
    pages_present: int,
    pages_declared: int,
    last4: str = "9912",
    holder: str = "Alex Rivera",
) -> dict[str, Any]:
    """The extraction JSON the pipeline stores for one statement."""
    return BankStatementExtraction(
        account_holder_name=TypedField(value=holder),
        bank_name=TypedField(value="Capital One"),
        account_number_masked=TypedField(value=f"****{last4}"),
        account_type=TypedField(value="Checking"),
        statement_period_start=TypedField(value=start),
        statement_period_end=TypedField(value=end),
        ending_balance=TypedField(value=Decimal(ending)),
        page_count_declared=TypedField(value=pages_declared),
        page_count_present=TypedField(value=pages_present),
        transactions=transactions,
    ).model_dump(mode="json")


def july(**overrides: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "start": date(2026, 7, 1),
        "end": date(2026, 7, 31),
        "ending": "36120.18",
        "transactions": JULY,
        "pages_present": 6,
        "pages_declared": 6,
    }
    return statement_data(**(args | overrides))


def august(**overrides: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "start": date(2026, 8, 1),
        "end": date(2026, 8, 31),
        "ending": "41914.42",
        "transactions": AUGUST,
        "pages_present": 6,
        "pages_declared": 6,
    }
    return statement_data(**(args | overrides))


def july_and_august(**overrides: Any) -> dict[str, Any]:
    """S3-08's single upload: both months, 12 pages."""
    args: dict[str, Any] = {
        "start": date(2026, 7, 1),
        "end": date(2026, 8, 31),
        "ending": "41914.42",
        "transactions": JULY + AUGUST,
        "pages_present": 12,
        "pages_declared": 12,
    }
    return statement_data(**(args | overrides))


async def add_statement(
    db: AsyncSession,
    loan_file: LoanFile,
    data: dict[str, Any],
    *,
    name: str = "statement.pdf",
    via_link: bool = True,
) -> Document:
    """A processed bank statement on the file, as the borrower's upload link leaves it."""
    document = Document(
        id=uuid4(),
        loan_file_id=loan_file.id,
        original_filename=name,
        mime_type="application/pdf",
        file_size_bytes=10,
        storage_path=f"{loan_file.company_id}/{loan_file.id}/{name}",
        document_type="bank_statement",
        status=DocumentStatus.COMPLETED,
        upload_source=UploadSource.SECURE_LINK if via_link else UploadSource.USER_UPLOAD,
    )
    db.add(document)
    await db.flush()
    db.add(
        Extraction(
            document_id=document.id,
            version=1,
            is_current=True,
            extracted_data=data,
            extraction_status=ExtractionStatus.SUCCEEDED,
            model_used="fixture",
        )
    )
    await db.flush()
    return document


async def add_declarations(
    db: AsyncSession,
    loan_file: LoanFile,
    *,
    annual: str = "1860.00",
    effective: date = date(2026, 9, 30),
) -> Document:
    """The new homeowners insurance declarations page: $1,860.00 a year ($155.00 a month), in force
    09/30/2026 — the policy 6178's text names (LP-934 M2)."""
    from app.ai.extraction.homeowners_insurance import HomeownersInsuranceExtraction

    document = Document(
        id=uuid4(),
        loan_file_id=loan_file.id,
        original_filename="declarations.pdf",
        mime_type="application/pdf",
        file_size_bytes=10,
        storage_path=f"{loan_file.company_id}/{loan_file.id}/declarations.pdf",
        document_type="homeowners_insurance",
        document_name="Homeowners declarations 09/30/2026",
        status=DocumentStatus.COMPLETED,
        upload_source=UploadSource.USER_UPLOAD,
    )
    db.add(document)
    await db.flush()
    data = HomeownersInsuranceExtraction(
        annual_premium=TypedField(value=Decimal(annual)),
        effective_date=TypedField(value=effective),
    ).model_dump(mode="json")
    db.add(
        Extraction(
            document_id=document.id,
            version=1,
            is_current=True,
            extracted_data=data,
            extraction_status=ExtractionStatus.SUCCEEDED,
            model_used="fixture",
        )
    )
    await db.flush()
    return document


async def add_receipt(
    db: AsyncSession,
    loan_file: LoanFile,
    *,
    amount: str = "2850.00",
    received: date = date(2026, 8, 3),
) -> Document:
    """Title's earnest money receipt for 6637: the $2,850.00 deposit received 08/03/2026, as the
    `earnest_money_receipt` extractor stores it (LP-938 review)."""
    from app.ai.extraction.earnest_money_receipt import EarnestMoneyReceiptExtraction

    document = Document(
        id=uuid4(),
        loan_file_id=loan_file.id,
        original_filename="emd-receipt.pdf",
        mime_type="application/pdf",
        file_size_bytes=10,
        storage_path=f"{loan_file.company_id}/{loan_file.id}/emd-receipt.pdf",
        document_type="earnest_money_receipt",
        document_name="Earnest money receipt",
        status=DocumentStatus.COMPLETED,
        upload_source=UploadSource.USER_UPLOAD,
    )
    db.add(document)
    await db.flush()
    data = EarnestMoneyReceiptExtraction(
        earnest_money_amount=TypedField(value=Decimal(amount)),
        funds_received_date=TypedField(value=received),
        check_number=TypedField(value="1042"),
    ).model_dump(mode="json")
    db.add(
        Extraction(
            document_id=document.id,
            version=1,
            is_current=True,
            extracted_data=data,
            extraction_status=ExtractionStatus.SUCCEEDED,
            model_used="fixture",
        )
    )
    await db.flush()
    return document

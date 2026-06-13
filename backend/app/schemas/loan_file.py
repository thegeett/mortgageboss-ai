"""Loan file request/response schemas (LP-28).

The public contract for the loan-file CRUD endpoints. Two read shapes: a lean
``LoanFileSummary`` for lists and a richer ``LoanFileDetail`` for a single file
(nesting borrowers/property). Security-critical exclusions:

  * ``inbox_token`` is NEVER exposed — it is a capability (the borrower inbox
    email); surfacing it would let anyone email documents into the file.
  * raw ``ssn`` is NEVER exposed — borrowers carry ``masked_ssn`` only.

``company_id`` is never part of any request body: the tenant is always derived
from the authenticated user (LP-24), never the client.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models.borrower import Borrower
from app.models.lender import LoanProgram
from app.models.loan_file import LoanFile, LoanFileStatus, LoanPurpose
from app.models.property import OccupancyType, PropertyType


class LoanFileCreate(BaseModel):
    """Fields settable when creating a file. All optional — a file may start
    empty in DRAFT and be filled in later. No ``company_id`` (from the user)."""

    lender_id: UUID | None = None
    loan_program: LoanProgram | None = None
    loan_purpose: LoanPurpose | None = None
    loan_officer_name: str | None = None
    loan_officer_email: EmailStr | None = None


class LoanFileUpdate(BaseModel):
    """Partial update of mutable fields (PATCH).

    Only fields the client explicitly sends are applied (``exclude_unset`` in
    the service), so omitting a field leaves it untouched; sending an explicit
    ``null`` clears it. Identifiers and ownership (``id``, ``display_id``,
    ``inbox_token``, ``company_id``) are immutable and intentionally absent here.
    """

    lender_id: UUID | None = None
    loan_program: LoanProgram | None = None
    loan_purpose: LoanPurpose | None = None
    loan_amount: Decimal | None = None
    status: LoanFileStatus | None = None
    loan_officer_name: str | None = None
    loan_officer_email: EmailStr | None = None
    # MISMO-specific loan terms (LP-56) — editable after import.
    note_amount: Decimal | None = None
    note_rate_percent: Decimal | None = None
    lien_priority: str | None = None
    amortization_type: str | None = None
    amortization_months: int | None = None
    application_received_date: date | None = None


class BorrowerPublic(BaseModel):
    """Safe borrower view — ``masked_ssn`` only, NEVER the raw/encrypted SSN."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    first_name: str
    last_name: str
    masked_ssn: str | None
    is_primary: bool
    borrower_position: int


class PropertyPublic(BaseModel):
    """Safe subject-property view (no sensitive data)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    address_line: str | None
    address_line_2: str | None
    city: str | None
    state: str | None
    postal_code: str | None
    property_type: PropertyType | None
    occupancy_type: OccupancyType | None
    estimated_value: Decimal | None
    purchase_price: Decimal | None


def _primary_borrower_name(loan_file: LoanFile, borrowers: list[Borrower]) -> str | None:
    """The primary borrower's full name, or None. Derived, not a column."""
    for borrower in borrowers:
        if borrower.is_primary:
            return borrower.full_name
    return None


class LoanFileSummary(BaseModel):
    """Lean list item. No ``inbox_token``. ``primary_borrower_name`` is derived."""

    id: UUID
    display_id: str
    status: LoanFileStatus
    loan_program: LoanProgram | None
    loan_purpose: LoanPurpose | None
    loan_amount: Decimal | None
    lender_id: UUID | None
    lender_name: str | None
    property_address: str | None
    primary_borrower_name: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, loan_file: LoanFile) -> Self:
        """Build a summary from an ORM file.

        ``borrowers``, ``lender``, and ``property`` must be eager-loaded (async
        sessions can't lazy-load on attribute access) — ``list_loan_files`` does so.
        """
        return cls(
            id=loan_file.id,
            display_id=loan_file.display_id,
            status=loan_file.status,
            loan_program=loan_file.loan_program,
            loan_purpose=loan_file.loan_purpose,
            loan_amount=loan_file.loan_amount,
            lender_id=loan_file.lender_id,
            lender_name=loan_file.lender.name if loan_file.lender is not None else None,
            property_address=(
                loan_file.property.address_line if loan_file.property is not None else None
            ),
            primary_borrower_name=_primary_borrower_name(loan_file, list(loan_file.borrowers)),
            created_at=loan_file.created_at,
            updated_at=loan_file.updated_at,
        )


class LoanFileDetail(LoanFileSummary):
    """Single-file view: summary + loan-officer fields + nested borrowers/property.

    Still no ``inbox_token`` and no raw SSN (borrowers use ``masked_ssn``)."""

    loan_officer_name: str | None
    loan_officer_email: str | None
    borrowers: list[BorrowerPublic]
    property: PropertyPublic | None

    @classmethod
    def from_model(cls, loan_file: LoanFile) -> Self:
        """Build a detail from an ORM file. ``borrowers`` and ``property`` must
        be eager-loaded (async sessions can't lazy-load on attribute access)."""
        borrowers = list(loan_file.borrowers)
        return cls(
            id=loan_file.id,
            display_id=loan_file.display_id,
            status=loan_file.status,
            loan_program=loan_file.loan_program,
            loan_purpose=loan_file.loan_purpose,
            loan_amount=loan_file.loan_amount,
            lender_id=loan_file.lender_id,
            lender_name=loan_file.lender.name if loan_file.lender is not None else None,
            property_address=(
                loan_file.property.address_line if loan_file.property is not None else None
            ),
            primary_borrower_name=_primary_borrower_name(loan_file, borrowers),
            created_at=loan_file.created_at,
            updated_at=loan_file.updated_at,
            loan_officer_name=loan_file.loan_officer_name,
            loan_officer_email=loan_file.loan_officer_email,
            borrowers=[BorrowerPublic.model_validate(b) for b in borrowers],
            property=(
                PropertyPublic.model_validate(loan_file.property)
                if loan_file.property is not None
                else None
            ),
        )


class PaginatedLoanFiles(BaseModel):
    """A page of loan-file summaries plus pagination metadata."""

    items: list[LoanFileSummary]
    total: int
    page: int
    page_size: int

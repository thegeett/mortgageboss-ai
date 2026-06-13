"""Borrower request/response schemas (LP-29).

The SSN is **in-but-masked-out** at the API boundary: create/update accept a raw
``ssn`` as input (stored encrypted via the ``EncryptedString`` column), but no
response schema has a raw ``ssn`` field — borrowers are returned with
``masked_ssn`` (``***-**-1234``) only. The raw SSN never leaves the server and is
never logged (ADR for SSN handling; LP-14 discipline).
"""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models.borrower import MaritalStatus


class BorrowerCreate(BaseModel):
    """Fields accepted when adding a borrower. ``ssn`` is raw input (encrypted at
    rest); names are required, the rest arrive incrementally."""

    first_name: str
    last_name: str
    middle_name: str | None = None
    ssn: str | None = None  # RAW input; stored encrypted; NEVER echoed back.
    date_of_birth: date | None = None
    email: EmailStr | None = None
    phone: str | None = None
    marital_status: MaritalStatus | None = None
    is_primary: bool | None = None
    borrower_position: int | None = None


class BorrowerUpdate(BaseModel):
    """Partial update (PATCH). Only provided fields are applied; a provided
    ``ssn`` is re-encrypted."""

    first_name: str | None = None
    last_name: str | None = None
    middle_name: str | None = None
    ssn: str | None = None  # if provided, re-encrypted; never returned
    date_of_birth: date | None = None
    email: EmailStr | None = None
    phone: str | None = None
    marital_status: MaritalStatus | None = None
    is_primary: bool | None = None
    borrower_position: int | None = None


class BorrowerResponse(BaseModel):
    """Safe borrower view — ``masked_ssn`` only, NEVER the raw/encrypted SSN.

    ``masked_ssn`` maps from the model property (``from_attributes``). There is
    deliberately no ``ssn`` field, so the raw value cannot be serialized.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    first_name: str
    last_name: str
    middle_name: str | None
    masked_ssn: str | None
    date_of_birth: date | None
    email: str | None
    phone: str | None
    marital_status: MaritalStatus | None
    is_primary: bool
    borrower_position: int
    created_at: datetime
    updated_at: datetime

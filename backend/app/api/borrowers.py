"""Borrower endpoints — a collection nested under a loan file (LP-29).

Routes live under ``/api/v1/loan-files/{file_identifier}/borrowers``. Every route
declares :data:`ScopedLoanFile`, so the parent file is fetched and
company-scope-checked **first** (``404`` if it isn't the caller's) — the tenant
gate. Borrowers have no ``company_id``; reaching a borrower at all means the file
passed the gate, and ``get_borrower`` additionally checks the borrower belongs to
*this* file (a borrower from another file → ``404``).

SSN is accepted on create/update (encrypted at rest) but every response carries
``masked_ssn`` only — never the raw SSN, which is also never logged.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.dependencies import ScopedLoanFile
from app.core.database import DbSession
from app.schemas.borrower import BorrowerCreate, BorrowerResponse, BorrowerUpdate
from app.services.borrowers import (
    create_borrower,
    get_borrower,
    list_borrowers,
    soft_delete_borrower,
    update_borrower,
)

router = APIRouter(prefix="/loan-files/{file_identifier}/borrowers", tags=["borrowers"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Borrower not found")


@router.get("", response_model=list[BorrowerResponse])
async def list_(loan_file: ScopedLoanFile, db: DbSession) -> list[BorrowerResponse]:
    """List the file's borrowers, ordered by position. (File gate via dependency.)"""
    borrowers = await list_borrowers(db, loan_file_id=loan_file.id)
    return [BorrowerResponse.model_validate(b) for b in borrowers]


@router.post("", response_model=BorrowerResponse, status_code=status.HTTP_201_CREATED)
async def add(
    payload: BorrowerCreate, loan_file: ScopedLoanFile, db: DbSession
) -> BorrowerResponse:
    """Add a borrower to the file (SSN stored encrypted; masked in the response)."""
    borrower = await create_borrower(db, loan_file_id=loan_file.id, data=payload)
    await db.commit()
    return BorrowerResponse.model_validate(borrower)


@router.get("/{borrower_id}", response_model=BorrowerResponse)
async def retrieve(borrower_id: UUID, loan_file: ScopedLoanFile, db: DbSession) -> BorrowerResponse:
    """Retrieve one of the file's borrowers; 404 if it isn't under this file."""
    borrower = await get_borrower(db, loan_file_id=loan_file.id, borrower_id=borrower_id)
    if borrower is None:
        raise _NOT_FOUND
    return BorrowerResponse.model_validate(borrower)


@router.patch("/{borrower_id}", response_model=BorrowerResponse)
async def update(
    borrower_id: UUID, payload: BorrowerUpdate, loan_file: ScopedLoanFile, db: DbSession
) -> BorrowerResponse:
    """Partially update one of the file's borrowers (provided ``ssn`` re-encrypted)."""
    borrower = await get_borrower(db, loan_file_id=loan_file.id, borrower_id=borrower_id)
    if borrower is None:
        raise _NOT_FOUND
    await update_borrower(db, borrower=borrower, data=payload)
    await db.commit()
    return BorrowerResponse.model_validate(borrower)


@router.delete("/{borrower_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(borrower_id: UUID, loan_file: ScopedLoanFile, db: DbSession) -> None:
    """Soft-delete one of the file's borrowers; 404 if it isn't under this file."""
    borrower = await get_borrower(db, loan_file_id=loan_file.id, borrower_id=borrower_id)
    if borrower is None:
        raise _NOT_FOUND
    await soft_delete_borrower(db, borrower=borrower)
    await db.commit()

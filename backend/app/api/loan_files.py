"""Loan file CRUD endpoints (LP-28) — the first tenant-scoped business API.

Every route requires authentication (``CurrentUser``) and is scoped to the
caller's company: the tenant is ``current_user.company_id`` (LP-24), **never**
taken from the request. Reads/writes go through the company-scoped service
functions, so a file in another company is unreachable — out-of-company access
returns ``404`` (not ``403``: we don't reveal that it exists).

``inbox_token`` and raw SSN never appear in any response (see the schemas).
``get_db`` does not auto-commit, so write endpoints commit explicitly after the
service flushes.
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.api.dependencies import CurrentUser
from app.core.database import DbSession
from app.models.loan_file import LoanFileStatus
from app.schemas.loan_file import (
    LoanFileCreate,
    LoanFileDetail,
    LoanFileSummary,
    LoanFileUpdate,
    PaginatedLoanFiles,
)
from app.services.loan_files import (
    create_loan_file_with_setup,
    get_loan_file,
    list_loan_files,
    soft_delete_loan_file_with_activity,
    update_loan_file_with_activity,
)

router = APIRouter(prefix="/loan-files", tags=["loan-files"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan file not found")


@router.post("", response_model=LoanFileDetail, status_code=status.HTTP_201_CREATED)
async def create(
    payload: LoanFileCreate, db: DbSession, current_user: CurrentUser
) -> LoanFileDetail:
    """Create a loan file in the caller's company (status DRAFT).

    ``company_id`` is taken from the authenticated user, never the body. Creation
    is orchestrated (LP-30): the file also gets a provisional initial needs list
    and a ``FILE_CREATED`` activity. Reloads the new file scoped so the response
    is built with relationships loaded. The response contract is unchanged.
    """
    loan_file = await create_loan_file_with_setup(
        db,
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        lender_id=payload.lender_id,
        loan_program=payload.loan_program,
        loan_purpose=payload.loan_purpose,
        loan_officer_name=payload.loan_officer_name,
        loan_officer_email=payload.loan_officer_email,
    )
    await db.commit()

    created = await get_loan_file(
        db, company_id=current_user.company_id, identifier=str(loan_file.id)
    )
    if created is None:  # pragma: no cover - just created, always found
        raise _NOT_FOUND
    return LoanFileDetail.from_model(created)


@router.get("", response_model=PaginatedLoanFiles)
async def list_files(
    db: DbSession,
    current_user: CurrentUser,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status: Annotated[LoanFileStatus | None, Query()] = None,
) -> PaginatedLoanFiles:
    """List the caller's company's loan files (newest first), paginated.

    Optional ``status`` filter. Excludes soft-deleted and other companies' files.
    """
    items, total = await list_loan_files(
        db,
        company_id=current_user.company_id,
        page=page,
        page_size=page_size,
        status=status,
    )
    return PaginatedLoanFiles(
        items=[LoanFileSummary.from_model(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{identifier}", response_model=LoanFileDetail)
async def retrieve(identifier: str, db: DbSession, current_user: CurrentUser) -> LoanFileDetail:
    """Retrieve one of the caller's files by UUID or display id; 404 if not in
    the caller's company."""
    loan_file = await get_loan_file(db, company_id=current_user.company_id, identifier=identifier)
    if loan_file is None:
        raise _NOT_FOUND
    return LoanFileDetail.from_model(loan_file)


@router.patch("/{identifier}", response_model=LoanFileDetail)
async def update(
    identifier: str, payload: LoanFileUpdate, db: DbSession, current_user: CurrentUser
) -> LoanFileDetail:
    """Partially update one of the caller's files; 404 if not in the company.

    Only provided fields change; identifiers/ownership are immutable (not in the
    update schema). Logs the change (LP-30): ``STATUS_CHANGED`` on a status
    transition, else ``FILE_UPDATED``."""
    loan_file = await get_loan_file(db, company_id=current_user.company_id, identifier=identifier)
    if loan_file is None:
        raise _NOT_FOUND
    await update_loan_file_with_activity(
        db, loan_file=loan_file, data=payload, actor_user_id=current_user.id
    )
    await db.commit()
    return LoanFileDetail.from_model(loan_file)


@router.delete("/{identifier}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(identifier: str, db: DbSession, current_user: CurrentUser) -> None:
    """Soft-delete one of the caller's files; 404 if not in the company.

    Logs a ``FILE_DELETED`` activity with the acting user (LP-30)."""
    loan_file = await get_loan_file(db, company_id=current_user.company_id, identifier=identifier)
    if loan_file is None:
        raise _NOT_FOUND
    await soft_delete_loan_file_with_activity(
        db, loan_file=loan_file, actor_user_id=current_user.id
    )
    await db.commit()

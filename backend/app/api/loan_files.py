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

import structlog
from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status

from app.api.dependencies import CurrentUser
from app.core.database import DbSession
from app.mismo.import_service import MismoImportError, create_loan_file_from_mismo
from app.mismo.parser import MismoParseError, parse_mismo
from app.models.loan_file import LoanFileStatus
from app.schemas.loan_file import (
    LoanFileCreate,
    LoanFileDetail,
    LoanFileSummary,
    LoanFileUpdate,
    PaginatedLoanFiles,
)
from app.schemas.mismo import MismoImportResponse
from app.services.loan_files import (
    create_loan_file_with_setup,
    get_loan_file,
    list_loan_files,
    soft_delete_loan_file_with_activity,
    update_loan_file_with_activity,
)

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/loan-files", tags=["loan-files"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan file not found")

# MISMO import is parsed inline (fast, deterministic — no AI/Celery). The cap is
# generous (a real MISMO is ~60 KB) and only rejects absurd uploads.
_MAX_MISMO_BYTES = 10 * 1024 * 1024
_MISMO_CHUNK = 1024 * 1024


async def _read_capped(upload: UploadFile, *, max_bytes: int) -> bytes:
    """Read an upload into memory, aborting (413) once it exceeds ``max_bytes``."""
    chunks: list[bytes] = []
    total = 0
    while chunk := await upload.read(_MISMO_CHUNK):
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="The MISMO file exceeds the size limit.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


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


@router.post(
    "/import-mismo",
    response_model=MismoImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_mismo(
    current_user: CurrentUser,
    db: DbSession,
    file: Annotated[UploadFile, File(description="A MISMO 3.4 XML (or HTML-wrapped) file")],
) -> MismoImportResponse:
    """Import a MISMO 3.4 file → a fully-populated loan file (LP-54).

    The primary file-creation path: the processor uploads the MISMO her LOS
    produced and gets back the populated file. A **thin** boundary — the work is
    in the services it orchestrates **inline** (no Celery): MISMO parsing is fast,
    deterministic lxml work with no AI (unlike document processing), so
    parse + create run in-request and the response *is* the created file
    (import-directly).

    Boundary validation only (a file is present + a size cap); the *content* is
    validated by :func:`parse_mismo`, which accepts raw XML and HTML-wrapped XML.
    ``company_id`` is the authenticated user's (never the body). A **partial
    parse still creates the file** and returns its ``warnings`` (success with
    warnings). Failures map to safe LP-46 envelope errors: an unparseable /
    not-MISMO file → ``400``; a file with no usable borrower or loan → ``422``.
    """
    raw = await _read_capped(file, max_bytes=_MAX_MISMO_BYTES)
    if not raw:
        raise HTTPException(
            status_code=422,
            detail="No file provided.",  # 422 literal: avoids a Starlette deprecation
        )

    try:
        parsed = parse_mismo(raw)
    except MismoParseError as exc:
        # Safe message only (rendered into the LP-46 envelope). The underlying
        # detail is never surfaced.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This file couldn't be parsed as a MISMO file.",
        ) from exc

    try:
        loan_file = await create_loan_file_from_mismo(
            db,
            parsed=parsed,
            company_id=current_user.company_id,
            raw_content=raw,
            source_format=parsed.source_format,
            actor_user_id=current_user.id,
        )
    except MismoImportError as exc:
        raise HTTPException(
            status_code=422,  # Unprocessable Content (literal avoids a deprecation)
            detail="This MISMO file is missing the borrower and loan data needed to create a file.",
        ) from exc

    await db.commit()

    # Reload scoped, with relationships eager-loaded for the response (same as the
    # manual create path — MISMO and manual converge on the same response).
    created = await get_loan_file(
        db, company_id=current_user.company_id, identifier=str(loan_file.id)
    )
    if created is None:  # pragma: no cover - just created, always found
        raise _NOT_FOUND

    # Metadata-only logging — NEVER the SSN, names, amounts, or file content.
    log.info(
        "mismo_import_endpoint",
        loan_file_id=str(loan_file.id),
        source_format=parsed.source_format,
        warnings=len(parsed.parse_warnings),
    )
    return MismoImportResponse(
        loan_file=LoanFileDetail.from_model(created),
        warnings=parsed.parse_warnings,
    )


@router.get("", response_model=PaginatedLoanFiles)
async def list_files(
    db: DbSession,
    current_user: CurrentUser,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status: Annotated[list[LoanFileStatus] | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=128)] = None,
) -> PaginatedLoanFiles:
    """List the caller's company's loan files (newest first), paginated.

    ``status`` is repeatable (``?status=draft&status=submitted``) so grouped
    dashboard pills filter to several statuses at once. ``search`` (display_id or
    borrower name, case-insensitive, company-scoped). Excludes soft-deleted and
    other companies' files.
    """
    items, total = await list_loan_files(
        db,
        company_id=current_user.company_id,
        page=page,
        page_size=page_size,
        statuses=status,
        search=search,
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

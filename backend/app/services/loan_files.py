"""Loan file service — creation and core CRUD operations.

Every query that reads or mutates a loan file is **scoped to one company** via
:func:`scope_to_company` and excludes soft-deleted rows via :func:`only_active`.
Callers pass ``company_id`` (the authenticated user's company, LP-24); a file in
another company is simply never returned — the endpoint maps that to a 404, so
existence is never revealed (anti-enumeration). Services ``flush``; the endpoint
controls the transaction and commits.
"""

from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.base import utcnow
from app.models.helpers import only_active, scope_to_company
from app.models.lender import LoanProgram
from app.models.loan_file import LoanFile, LoanFileStatus, LoanPurpose
from app.schemas.loan_file import LoanFileUpdate
from app.services.loan_file_ids import (
    generate_inbox_token,
    generate_unique_display_id,
)


async def create_loan_file(
    db: AsyncSession,
    *,
    company_id: UUID,
    lender_id: UUID | None = None,
    loan_program: LoanProgram | None = None,
    loan_purpose: LoanPurpose | None = None,
    loan_officer_name: str | None = None,
    loan_officer_email: str | None = None,
) -> LoanFile:
    """Create a new loan file with generated display ID and inbox token.

    The display ID is collision-checked against existing files; the inbox token
    is an independent cryptographic value (ADR-036, ADR-050). The new file
    starts in :attr:`LoanFileStatus.DRAFT`.

    Minimal creation only: needs-list generation and activity logging are added
    in later tickets (LP-30). Uses ``flush`` rather than ``commit`` so the
    caller controls the transaction (and tests stay isolated).
    """
    display_id = await generate_unique_display_id(db)
    inbox_token = generate_inbox_token()

    loan_file = LoanFile(
        display_id=display_id,
        inbox_token=inbox_token,
        company_id=company_id,
        lender_id=lender_id,
        loan_program=loan_program,
        loan_purpose=loan_purpose,
        status=LoanFileStatus.DRAFT,
        loan_officer_name=loan_officer_name,
        loan_officer_email=loan_officer_email,
    )
    db.add(loan_file)
    await db.flush()  # populate defaults/PK without committing (caller controls tx)
    return loan_file


def _scoped(company_id: UUID) -> Select[tuple[LoanFile]]:
    """A base ``select(LoanFile)`` already scoped to the company and active rows.

    Centralizes the two filters every read must apply, so no call site can
    forget tenant scoping or accidentally surface soft-deleted files.
    """
    stmt = select(LoanFile)
    stmt = scope_to_company(stmt, LoanFile, company_id)
    stmt = only_active(stmt, LoanFile)
    return stmt


async def list_loan_files(
    db: AsyncSession,
    *,
    company_id: UUID,
    page: int = 1,
    page_size: int = 20,
    status: LoanFileStatus | None = None,
) -> tuple[list[LoanFile], int]:
    """List a company's loan files, newest first, paginated.

    Returns ``(items, total)`` where ``total`` is the full count for the same
    filters (company + active + optional status), independent of the page.
    Borrowers are eager-loaded so the summary's ``primary_borrower_name`` can be
    computed without a lazy load.
    """
    base = _scoped(company_id)
    if status is not None:
        base = base.where(LoanFile.status == status)

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.scalar(count_stmt)) or 0

    items_stmt = (
        base.options(selectinload(LoanFile.borrowers))
        .order_by(LoanFile.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(items_stmt)
    return list(result.scalars().all()), total


async def get_loan_file(
    db: AsyncSession,
    *,
    company_id: UUID,
    identifier: str,
) -> LoanFile | None:
    """Fetch one of the company's loan files by UUID **or** ``display_id``.

    Returns ``None`` if no active file with that identifier exists *in this
    company* — including when it exists in another company (it's simply out of
    scope). Borrowers and property are eager-loaded for the detail view.
    """
    stmt = _scoped(company_id).options(
        selectinload(LoanFile.borrowers),
        selectinload(LoanFile.property),
    )
    try:
        stmt = stmt.where(LoanFile.id == UUID(identifier))
    except ValueError:
        # Not a UUID — treat it as a human display id (e.g. "LF-AB12").
        stmt = stmt.where(LoanFile.display_id == identifier)

    loan_file: LoanFile | None = await db.scalar(stmt)
    return loan_file


async def update_loan_file(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    data: LoanFileUpdate,
) -> LoanFile:
    """Apply a partial update to a loan file.

    Only fields the client explicitly provided are written (``exclude_unset``),
    so omitted fields are untouched while an explicit ``null`` clears a field.
    Identifiers and ownership are never in :class:`LoanFileUpdate`, so they can't
    be changed here. Uses ``flush``; the caller commits.
    """
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(loan_file, field, value)
    await db.flush()
    return loan_file


async def soft_delete_loan_file(db: AsyncSession, *, loan_file: LoanFile) -> None:
    """Soft-delete a loan file (set ``deleted_at``); never a hard delete.

    Subsequent scoped reads exclude it via :func:`only_active`. Uses ``flush``;
    the caller commits.
    """
    loan_file.deleted_at = utcnow()
    await db.flush()

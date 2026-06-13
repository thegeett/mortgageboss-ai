"""Borrower service — CRUD for the borrowers owned by a loan file (LP-29).

Borrowers have no ``company_id`` of their own (ADR-052/053): they are scoped
**transitively** through their loan file. These functions take an already
scope-checked ``loan_file_id`` (the endpoint first fetches the file via
``get_loan_file`` with the caller's company, so reaching here means the file is
the caller's). Reads exclude soft-deleted rows; services ``flush`` and the
endpoint commits.

The SSN flows in as plaintext on ``BorrowerCreate``/``BorrowerUpdate`` and is
written to the ``EncryptedString`` column, so it is encrypted at rest. It is
never returned (responses use ``masked_ssn``) or logged.

Primary/position handling is intentionally minimal (V1): the first borrower on a
file defaults to primary at position 1; later borrowers default to non-primary
at the next position. Creating or updating a borrower to ``is_primary=True``
demotes the file's other borrowers, keeping a single primary; otherwise primary
state is client-managed.
"""

from uuid import UUID

from sqlalchemy import Select, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utcnow
from app.models.borrower import Borrower
from app.models.helpers import only_active
from app.schemas.borrower import BorrowerCreate, BorrowerUpdate


def _active_borrowers_stmt(loan_file_id: UUID) -> Select[tuple[Borrower]]:
    stmt = select(Borrower).where(Borrower.loan_file_id == loan_file_id)
    return only_active(stmt, Borrower).order_by(Borrower.borrower_position)


async def list_borrowers(db: AsyncSession, *, loan_file_id: UUID) -> list[Borrower]:
    """The file's active borrowers, ordered by ``borrower_position``."""
    result = await db.execute(_active_borrowers_stmt(loan_file_id))
    return list(result.scalars().all())


async def get_borrower(
    db: AsyncSession, *, loan_file_id: UUID, borrower_id: UUID
) -> Borrower | None:
    """Fetch one active borrower that belongs to ``loan_file_id``.

    Returns ``None`` if no such active borrower exists *under this file* —
    including a borrower that exists under a different file (the ``loan_file_id``
    match is what makes a cross-file id a 404).
    """
    stmt = select(Borrower).where(
        Borrower.id == borrower_id,
        Borrower.loan_file_id == loan_file_id,
    )
    stmt = only_active(stmt, Borrower)
    borrower: Borrower | None = await db.scalar(stmt)
    return borrower


async def _demote_other_primaries(
    db: AsyncSession, *, loan_file_id: UUID, keep_id: UUID | None
) -> None:
    """Clear ``is_primary`` on the file's other (active) borrowers.

    Keeps a single primary per file when one is set. ``keep_id`` is the borrower
    that should remain primary (``None`` when demoting before the new row has an
    id — the new borrower is added as primary right after).
    """
    stmt = (
        update(Borrower)
        .where(
            Borrower.loan_file_id == loan_file_id,
            Borrower.deleted_at.is_(None),
            Borrower.is_primary.is_(True),
        )
        .values(is_primary=False)
    )
    if keep_id is not None:
        stmt = stmt.where(Borrower.id != keep_id)
    await db.execute(stmt)


async def create_borrower(
    db: AsyncSession, *, loan_file_id: UUID, data: BorrowerCreate
) -> Borrower:
    """Add a borrower to a file (SSN encrypted at rest), applying V1 defaults.

    First borrower → primary at position 1; otherwise non-primary at the next
    position. An explicit ``is_primary``/``borrower_position`` wins. A borrower
    that ends up primary demotes the file's other borrowers.
    """
    existing = await list_borrowers(db, loan_file_id=loan_file_id)
    is_first = len(existing) == 0

    is_primary = data.is_primary if data.is_primary is not None else is_first
    if data.borrower_position is not None:
        position = data.borrower_position
    elif is_first:
        position = 1
    else:
        position = max(b.borrower_position for b in existing) + 1

    if is_primary and existing:
        await _demote_other_primaries(db, loan_file_id=loan_file_id, keep_id=None)

    borrower = Borrower(
        loan_file_id=loan_file_id,
        first_name=data.first_name,
        last_name=data.last_name,
        middle_name=data.middle_name,
        ssn=data.ssn,  # plaintext in → EncryptedString encrypts at rest
        date_of_birth=data.date_of_birth,
        email=data.email,
        phone=data.phone,
        marital_status=data.marital_status,
        is_primary=is_primary,
        borrower_position=position,
    )
    db.add(borrower)
    await db.flush()
    return borrower


async def update_borrower(
    db: AsyncSession, *, borrower: Borrower, data: BorrowerUpdate
) -> Borrower:
    """Apply a partial update. Only provided fields change; a provided ``ssn`` is
    re-encrypted. Setting ``is_primary=True`` demotes the file's other borrowers."""
    fields = data.model_dump(exclude_unset=True)
    for field, value in fields.items():
        setattr(borrower, field, value)
    if fields.get("is_primary") is True:
        await _demote_other_primaries(db, loan_file_id=borrower.loan_file_id, keep_id=borrower.id)
    await db.flush()
    return borrower


async def soft_delete_borrower(db: AsyncSession, *, borrower: Borrower) -> None:
    """Soft-delete a borrower (set ``deleted_at``); never a hard delete."""
    borrower.deleted_at = utcnow()
    await db.flush()

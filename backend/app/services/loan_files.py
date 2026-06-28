"""Loan file service — creation, core CRUD, and lifecycle orchestration.

Every query that reads or mutates a loan file is **scoped to one company** via
:func:`scope_to_company` and excludes soft-deleted rows via :func:`only_active`.
Callers pass ``company_id`` (the authenticated user's company, LP-24); a file in
another company is simply never returned — the endpoint maps that to a 404, so
existence is never revealed (anti-enumeration). Services ``flush``; the endpoint
controls the transaction and commits.

Creation is a **workflow**, not just a row insert (LP-30): the minimal
:func:`create_loan_file` (ids + DRAFT) stays for internal reuse, and
:func:`create_loan_file_with_setup` composes it with a provisional initial needs
list and a ``FILE_CREATED`` activity. Update/delete have ``*_with_activity``
wrappers that record the audit trail (the first adoption of ``log_activity``,
ADR-073) while the pure mutators stay logging-free for internal/test callers.
"""

from uuid import UUID

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.activity_log import ActivityType
from app.models.base import utcnow
from app.models.borrower import Borrower
from app.models.helpers import only_active, scope_to_company
from app.models.lender import LoanProgram
from app.models.loan_file import LoanFile, LoanFileStatus, LoanPurpose
from app.models.needs_item import NeedsItem, NeedsItemOrigin
from app.schemas.loan_file import LoanFileUpdate
from app.services.activity_log import log_activity
from app.services.finding_blocking import is_file_blocked
from app.services.loan_file_ids import (
    generate_inbox_token,
    generate_unique_display_id,
)
from app.services.needs_items import create_needs_item
from app.services.needs_templates import needs_for_program


class FileBlockedError(Exception):
    """A file with open in-scope findings cannot be marked ready to submit (LP-75).

    Raised when a status transition to ``READY_TO_SUBMIT`` is attempted while the
    blocking computation reports open in-scope findings — every finding must be
    resolved (applied or overridden) first. The endpoint maps this to a 409.
    """


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
    statuses: list[LoanFileStatus] | None = None,
    search: str | None = None,
) -> tuple[list[LoanFile], int]:
    """List a company's loan files, newest first, paginated.

    Returns ``(items, total)`` where ``total`` is the full count for the same
    filters (company + active + optional statuses + search), independent of the
    page. ``statuses`` filters to any of the given statuses (so the dashboard's
    grouped pills — e.g. "Active" = several statuses — paginate correctly).
    ``search`` (case-insensitive) matches the ``display_id`` OR a primary/
    co-borrower's name; it composes with the company scope, so it can never reach
    another company's files. Borrowers, lender, and property are eager-loaded so
    the summary fields are built without a lazy load.
    """
    base = _scoped(company_id)
    if statuses:
        base = base.where(LoanFile.status.in_(statuses))
    if search:
        pattern = f"%{search}%"
        # Files whose display_id matches, OR that have an active borrower whose
        # full name matches. The borrower subquery is joined by loan_file_id; the
        # outer query stays company-scoped, so a cross-company match can't leak.
        borrower_match = (
            select(Borrower.loan_file_id)
            .where(Borrower.deleted_at.is_(None))
            .where((Borrower.first_name + " " + Borrower.last_name).ilike(pattern))
        )
        base = base.where(or_(LoanFile.display_id.ilike(pattern), LoanFile.id.in_(borrower_match)))

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.scalar(count_stmt)) or 0

    items_stmt = (
        base.options(
            selectinload(LoanFile.borrowers),
            selectinload(LoanFile.lender),
            selectinload(LoanFile.property),
        )
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
    scope). Borrowers, lender, and property are eager-loaded for the detail view
    (the summary fields ``lender_name``/``property_address`` need lender/property).
    """
    stmt = _scoped(company_id).options(
        selectinload(LoanFile.borrowers),
        selectinload(LoanFile.lender),
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


# --------------------------------------------------------------------------- #
# Lifecycle orchestration + activity logging (LP-30)
# --------------------------------------------------------------------------- #


async def generate_initial_needs_list(
    db: AsyncSession, *, loan_file_id: UUID, loan_program: LoanProgram | None
) -> list[NeedsItem]:
    """Create the file's provisional initial needs list (origin ``TEMPLATE``).

    Uses the per-program starter template (``needs_for_program``); ``None`` →
    the universal baseline only. The template is **provisional** and pending
    domain refinement — see :mod:`app.services.needs_templates`. Uses ``flush``.
    """
    created: list[NeedsItem] = []
    for template in needs_for_program(loan_program):
        item = await create_needs_item(
            db,
            loan_file_id=loan_file_id,
            title=template.title,
            category=template.category,
            needs_type=template.needs_type,
            origin=NeedsItemOrigin.TEMPLATE,
            priority=template.priority,
        )
        created.append(item)
    return created


async def create_loan_file_with_setup(
    db: AsyncSession,
    *,
    company_id: UUID,
    actor_user_id: UUID,
    lender_id: UUID | None = None,
    loan_program: LoanProgram | None = None,
    loan_purpose: LoanPurpose | None = None,
    loan_officer_name: str | None = None,
    loan_officer_email: str | None = None,
) -> LoanFile:
    """Create a loan file as a workflow: the file + an initial needs list + a
    ``FILE_CREATED`` activity, all in the caller's transaction.

    Composes the existing :func:`create_loan_file` (ids, DRAFT) with
    :func:`generate_initial_needs_list` and one ``log_activity`` call (the needs
    count is folded into its detail rather than logging one activity per item).
    Uses ``flush``; the endpoint commits.
    """
    loan_file = await create_loan_file(
        db,
        company_id=company_id,
        lender_id=lender_id,
        loan_program=loan_program,
        loan_purpose=loan_purpose,
        loan_officer_name=loan_officer_name,
        loan_officer_email=loan_officer_email,
    )
    needs = await generate_initial_needs_list(
        db, loan_file_id=loan_file.id, loan_program=loan_program
    )
    await log_activity(
        db,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.FILE_CREATED,
        summary=f"Loan file {loan_file.display_id} created",
        actor_user_id=actor_user_id,
        detail={
            "loan_program": loan_program.value if loan_program else None,
            "loan_purpose": loan_purpose.value if loan_purpose else None,
            "initial_needs_count": len(needs),
        },
    )
    await db.flush()
    return loan_file


async def update_loan_file_with_activity(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    data: LoanFileUpdate,
    actor_user_id: UUID,
) -> LoanFile:
    """Apply an update and record an activity for it.

    Captures the status **before** applying changes so a transition is detected:
    a status change logs ``STATUS_CHANGED`` with ``{from, to}``; any other field
    change logs ``FILE_UPDATED`` with the changed field names; a no-op PATCH logs
    nothing. Uses ``flush``; the endpoint commits.
    """
    old_status = loan_file.status
    changed_fields = set(data.model_dump(exclude_unset=True).keys())

    # Findings are blocking (LP-75): a file with open in-scope findings cannot be
    # marked ready to submit. Check before applying so the transition is gated.
    if (
        "status" in changed_fields
        and data.status is LoanFileStatus.READY_TO_SUBMIT
        and old_status is not LoanFileStatus.READY_TO_SUBMIT
        and await is_file_blocked(db, loan_file_id=loan_file.id)
    ):
        raise FileBlockedError(
            "Open in-scope findings must be resolved before the file can submit."
        )

    await update_loan_file(db, loan_file=loan_file, data=data)

    if "status" in changed_fields and loan_file.status != old_status:
        await log_activity(
            db,
            loan_file_id=loan_file.id,
            activity_type=ActivityType.STATUS_CHANGED,
            summary=f"Status changed from {old_status.value} to {loan_file.status.value}",
            actor_user_id=actor_user_id,
            detail={"from": old_status.value, "to": loan_file.status.value},
        )
    elif changed_fields:
        await log_activity(
            db,
            loan_file_id=loan_file.id,
            activity_type=ActivityType.FILE_UPDATED,
            summary=f"Loan file {loan_file.display_id} updated",
            actor_user_id=actor_user_id,
            detail={"changed_fields": sorted(changed_fields)},
        )
    return loan_file


async def soft_delete_loan_file_with_activity(
    db: AsyncSession, *, loan_file: LoanFile, actor_user_id: UUID
) -> None:
    """Soft-delete a loan file and record a ``FILE_DELETED`` activity.

    The activity is logged before the soft delete so it references the live file.
    Uses ``flush``; the endpoint commits.
    """
    await log_activity(
        db,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.FILE_DELETED,
        summary=f"Loan file {loan_file.display_id} deleted",
        actor_user_id=actor_user_id,
    )
    await soft_delete_loan_file(db, loan_file=loan_file)

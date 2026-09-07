"""Lender endpoints — the picker (LP-32), the admin writes and contacts (LP-813).

TWO AUDIENCES ON ONE PREFIX, and the split is deliberate rather than incidental.

Reads are open to any authenticated user of the company: a processor filling in the intake form
needs the lender list, and one choosing an underwriter needs that lender's contacts. Writes are
ADMIN-gated, declared per route rather than on the router, because gating the router would have
taken the existing processor-facing GET with it and broken intake.

Nothing here derives a company from anything. `current_user.company_id` is the scope for every
route, and the one place two ownerships have to be reconciled — a loan file pointing at a contact
reached through a lender — is `services/lender_contacts.assign_underwriter`, not this module.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import CurrentUser, ScopedLoanFile, require_role
from app.core.database import DbSession
from app.models.lender_contact import LenderContact
from app.models.user import UserRole
from app.schemas.lender import (
    LenderContactCreate,
    LenderContactPublic,
    LenderContactUpdate,
    LenderCreate,
    LenderDetail,
    LenderSummary,
    LenderUpdate,
    UnderwriterAssignment,
)
from app.services.lender_contacts import (
    CannotAssignError,
    assign_underwriter,
    find_contact_by_email,
    get_scoped_contact,
    list_contacts,
)
from app.services.lenders import (
    LenderError,
    create_lender,
    get_scoped_lender,
    list_lenders,
    update_lender,
)

router = APIRouter(prefix="/lenders", tags=["lenders"])

#: Admin-only, per route. On the router it would have caught the processor-facing GET too.
_ADMIN = Depends(require_role(UserRole.ADMIN))

_LENDER_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, detail="Lender not found")
_CONTACT_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, detail="Lender contact not found")


@router.get("", response_model=list[LenderSummary])
async def list_files(db: DbSession, current_user: CurrentUser) -> list[LenderSummary]:
    """List the caller's company's lenders (for the intake dropdown)."""
    lenders = await list_lenders(db, company_id=current_user.company_id)
    return [LenderSummary.model_validate(lender) for lender in lenders]


@router.post("", response_model=LenderDetail, status_code=status.HTTP_201_CREATED)
async def create(
    payload: LenderCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: None = _ADMIN,
) -> LenderDetail:
    """Add a lender.

    THE FIRST WAY TO CREATE ONE. Until LP-813 every lender in every environment came from the seed
    script, which is why `lenders.contact_email` — one of LP-805's three participant sources — was
    NULL on any real installation.
    """
    try:
        lender = await create_lender(
            db,
            company_id=current_user.company_id,
            name=payload.name,
            slug=payload.slug,
            supported_programs=payload.supported_programs,
            contact_email=payload.contact_email,
            contact_phone=payload.contact_phone,
            portal_url=payload.portal_url,
            notes=payload.notes,
        )
    except LenderError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await db.commit()
    return LenderDetail.model_validate(lender)


@router.get("/{lender_id}", response_model=LenderDetail)
async def read(lender_id: UUID, db: DbSession, current_user: CurrentUser) -> LenderDetail:
    lender = await get_scoped_lender(db, lender_id=lender_id, company_id=current_user.company_id)
    if lender is None:
        raise _LENDER_NOT_FOUND
    return LenderDetail.model_validate(lender)


@router.patch("/{lender_id}", response_model=LenderDetail)
async def update(
    lender_id: UUID,
    payload: LenderUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: None = _ADMIN,
) -> LenderDetail:
    lender = await get_scoped_lender(db, lender_id=lender_id, company_id=current_user.company_id)
    if lender is None:
        raise _LENDER_NOT_FOUND
    try:
        updated = await update_lender(
            db, lender=lender, fields=payload.model_dump(exclude_unset=True)
        )
    except LenderError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await db.commit()
    return LenderDetail.model_validate(updated)


# --------------------------------------------------------------------------------------------- #
# Contacts — the people a processor actually corresponds with
# --------------------------------------------------------------------------------------------- #
@router.get("/{lender_id}/contacts", response_model=list[LenderContactPublic])
async def contacts(
    lender_id: UUID, db: DbSession, current_user: CurrentUser
) -> list[LenderContactPublic]:
    """A lender's contacts. Readable by any processor — they are who a file gets assigned to."""
    lender = await get_scoped_lender(db, lender_id=lender_id, company_id=current_user.company_id)
    if lender is None:
        raise _LENDER_NOT_FOUND
    rows = await list_contacts(db, lender_id=lender_id, company_id=current_user.company_id)
    return [LenderContactPublic.model_validate(row) for row in rows]


@router.post(
    "/{lender_id}/contacts",
    response_model=LenderContactPublic,
    status_code=status.HTTP_201_CREATED,
)
async def create_contact(
    lender_id: UUID,
    payload: LenderContactCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: None = _ADMIN,
) -> LenderContactPublic:
    lender = await get_scoped_lender(db, lender_id=lender_id, company_id=current_user.company_id)
    if lender is None:
        raise _LENDER_NOT_FOUND
    if payload.email is not None:
        existing = await find_contact_by_email(db, lender_id=lender_id, email=payload.email)
        if existing is not None:
            # THE SAME PERSON TWICE IS THE FAILURE, not a constraint to be surprised by: two rows
            # for one underwriter means a file assigned to one and their mail arriving from the
            # other, so the participant lookup misses and the reply goes to triage.
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="This lender already has a contact with that email address.",
            )
    contact = LenderContact(
        lender_id=lender_id,
        name=payload.name,
        email=payload.email,
        phone=payload.phone,
        role=payload.role,
        notes=payload.notes,
    )
    db.add(contact)
    await db.commit()
    return LenderContactPublic.model_validate(contact)


@router.patch("/contacts/{contact_id}", response_model=LenderContactPublic)
async def update_contact(
    contact_id: UUID,
    payload: LenderContactUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: None = _ADMIN,
) -> LenderContactPublic:
    contact = await get_scoped_contact(
        db, contact_id=contact_id, company_id=current_user.company_id
    )
    if contact is None:
        raise _CONTACT_NOT_FOUND
    fields = payload.model_dump(exclude_unset=True)
    if fields.get("email") is not None:
        clash = await find_contact_by_email(
            db, lender_id=contact.lender_id, email=str(fields["email"])
        )
        if clash is not None and clash.id != contact.id:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="This lender already has a contact with that email address.",
            )
    for field, value in fields.items():
        setattr(contact, field, value)
    await db.commit()
    return LenderContactPublic.model_validate(contact)


@router.delete("/contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact(
    contact_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
    _: None = _ADMIN,
) -> None:
    """Soft-delete a contact. Files assigned to them are left naming nobody, not left broken.

    The FK is `ondelete SET NULL` for the hard-delete case that never happens; this path sets
    `deleted_at`, so the row survives for the audit trail while every scoped read stops returning
    it. The loan file's `underwriter_contact_id` still points at it — deliberately, because it is
    the record of who the underwriter WAS, and the reads that matter go through `get_scoped_contact`
    and `only_active`.
    """
    from app.models.base import utcnow

    contact = await get_scoped_contact(
        db, contact_id=contact_id, company_id=current_user.company_id
    )
    if contact is None:
        raise _CONTACT_NOT_FOUND
    contact.deleted_at = utcnow()
    await db.commit()


# --------------------------------------------------------------------------------------------- #
# The assignment, which is the one place two ownership chains meet
# --------------------------------------------------------------------------------------------- #
file_router = APIRouter(prefix="/loan-files/{file_identifier}", tags=["lenders"])


@file_router.put("/underwriter", response_model=LenderContactPublic | None)
async def set_underwriter(
    payload: UnderwriterAssignment,
    loan_file: ScopedLoanFile,
    db: DbSession,
    current_user: CurrentUser,
) -> LenderContactPublic | None:
    """Assign this file's underwriter, or clear it with ``contact_id: null``.

    NOT ADMIN-GATED. Configuring which lenders exist is administration; deciding who is handling
    this file is the processor's own work, and gating it would mean every reassignment waited on
    somebody else.

    The refusals live in the service so any future caller inherits them — the route proves the
    caller owns the FILE, and the contact id is a body parameter anybody can type.
    """
    try:
        await assign_underwriter(
            db,
            loan_file=loan_file,
            contact_id=payload.contact_id,
            company_id=current_user.company_id,
        )
    except CannotAssignError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if loan_file.underwriter_contact_id is None:
        await db.commit()
        return None

    # RE-SEED THE PARTICIPANTS. The assignment is only half the point: an underwriter who is not on
    # the file's participant list is a stranger to LP-805, so their reply lands in triage — or, if
    # they write to the file address, routes with no idea who they are. Seeding is idempotent and
    # never sets trust.
    from app.services.inbound_participants import seed_participants

    await seed_participants(db, loan_file=loan_file)
    contact = await get_scoped_contact(
        db,
        contact_id=loan_file.underwriter_contact_id,
        company_id=current_user.company_id,
    )
    await db.commit()
    return LenderContactPublic.model_validate(contact) if contact else None

"""Lender contacts, and assigning one to a loan file (LP-813).

TWO OWNERS HAVE TO AGREE, and that is what makes this module worth reading. A loan file is owned by a
company; a contact is owned by a lender, which is owned by a company. Assigning one to the other is
the only place in the schema where a loan file points at a row reached through a different
ownership chain — so it is the only place those two companies can disagree, and nothing but
:func:`assign_underwriter` proves they do not.

The route proves the caller owns the FILE. The contact id is a body parameter, which anybody can
type. That is the same shape as LP-806's accept, and the same answer: check it here, in the service,
so every caller inherits it.

AND THE CONTACT MUST BE AT THE FILE'S OWN LENDER. Same-company is not enough. "Submitted to
Sun-West, underwriter at UWM" is a file that reads as complete and is wrong in the one field a
processor would act on — they would email a stranger about somebody else's loan.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.helpers import only_active
from app.models.lender import Lender
from app.models.lender_contact import LenderContact
from app.models.loan_file import LoanFile

logger = get_logger(__name__)


class CannotAssignError(Exception):
    """The contact cannot be assigned to this file. Always names the rule that stopped it."""


async def get_scoped_contact(
    db: AsyncSession, *, contact_id: UUID, company_id: UUID
) -> LenderContact | None:
    """One contact, only if it belongs to a lender this company owns. None otherwise.

    ONE QUERY, NOT A FETCH THEN A CHECK. A caller that loads the row first has the row, and the
    check becomes something a later edit can drop while the code still reads as scoped.
    """
    return (
        await db.execute(
            only_active(
                select(LenderContact)
                .join(Lender, Lender.id == LenderContact.lender_id)
                .where(LenderContact.id == contact_id, Lender.company_id == company_id),
                LenderContact,
            )
        )
    ).scalar_one_or_none()


async def list_contacts(
    db: AsyncSession, *, lender_id: UUID, company_id: UUID
) -> list[LenderContact]:
    """A lender's contacts, newest name order, scoped through the lender's company."""
    return list(
        (
            await db.execute(
                only_active(
                    select(LenderContact)
                    .join(Lender, Lender.id == LenderContact.lender_id)
                    .where(LenderContact.lender_id == lender_id, Lender.company_id == company_id)
                    .order_by(LenderContact.name),
                    LenderContact,
                )
            )
        )
        .scalars()
        .all()
    )


async def find_contact_by_email(
    db: AsyncSession, *, lender_id: UUID, email: str
) -> LenderContact | None:
    """An existing contact at this lender with this address, case-insensitively. None otherwise.

    Mirrors the partial unique index, so a create that would violate it is refused with a sentence
    rather than an IntegrityError — and mirrors `normalise_address`, so "is this the same person"
    has one answer across the codebase.
    """
    return (
        await db.execute(
            only_active(
                select(LenderContact).where(
                    LenderContact.lender_id == lender_id,
                    func.lower(LenderContact.email) == email.strip().lower(),
                ),
                LenderContact,
            )
        )
    ).scalar_one_or_none()


async def assign_underwriter(
    db: AsyncSession, *, loan_file: LoanFile, contact_id: UUID | None, company_id: UUID
) -> LoanFile:
    """Put ``contact_id`` on ``loan_file`` as its underwriter, or clear it with None.

    THREE THINGS MUST HOLD, and each of them has its own way of being wrong:

    * **The contact must belong to this company.** Otherwise a loan file points at another tenant's
      row, and every later read of "who is the underwriter" answers with their data.
    * **The file must have a lender.** "The underwriter for this file" means nothing before anyone
      has decided where the file is going, and allowing it invites the third failure below.
    * **The contact must be at THAT lender.** Same-company is not enough — it is the check that
      stops a file reading "submitted to Sun-West, underwriter at UWM", which looks complete and is
      wrong in the one field a processor acts on.

    Clearing is always allowed and needs none of them: removing something is not an assertion about
    what it was.

    ``flush`` only; the caller commits.
    """
    if contact_id is None:
        loan_file.underwriter_contact_id = None
        await db.flush()
        return loan_file

    contact = await get_scoped_contact(db, contact_id=contact_id, company_id=company_id)
    if contact is None:
        # THE SAME MESSAGE FOR "no such contact" AND "that one is another company's". Telling them
        # apart would confirm the id exists, which is an oracle over another tenant's rows — the
        # same reasoning as LP-806's 404.
        raise CannotAssignError("No such contact for this company.")
    if loan_file.lender_id is None:
        raise CannotAssignError(
            "Assign a lender to this file before choosing an underwriter for it."
        )
    if contact.lender_id != loan_file.lender_id:
        raise CannotAssignError("That contact works for a different lender than this file.")

    loan_file.underwriter_contact_id = contact.id
    await db.flush()
    # METADATA ONLY — ids and a role. Never the name, the address or the phone number: a contact is
    # a person, and this is the same rule the participant seeding logs under.
    logger.info(
        "underwriter_assigned",
        loan_file_id=str(loan_file.id),
        contact_role=contact.role.value,
    )
    return loan_file


async def clear_underwriter_if_lender_changed(
    db: AsyncSession, *, loan_file: LoanFile, previous_lender_id: UUID | None
) -> bool:
    """Drop the assignment when the file's lender moved out from under it. True if it cleared.

    THE INVARIANT IS NOT SELF-ENFORCING. `assign_underwriter` proves the contact is at the file's
    lender at the moment of assignment, and a later PATCH of `lender_id` — an ordinary edit, through
    `update_loan_file`, which setattrs whatever it is given — silently makes that false. The file
    would then name an underwriter at a lender it is no longer going to, and nothing on the screen
    would say so.

    Clearing rather than refusing the lender change: changing where a file is submitted is a
    decision a processor is entitled to make, and the underwriter is a consequence of it, not a
    constraint on it.
    """
    if loan_file.lender_id == previous_lender_id:
        return False
    if loan_file.underwriter_contact_id is None:
        return False
    loan_file.underwriter_contact_id = None
    await db.flush()
    logger.info("underwriter_cleared_on_lender_change", loan_file_id=str(loan_file.id))
    return True


__all__ = [
    "CannotAssignError",
    "assign_underwriter",
    "clear_underwriter_if_lender_changed",
    "find_contact_by_email",
    "get_scoped_contact",
    "list_contacts",
]

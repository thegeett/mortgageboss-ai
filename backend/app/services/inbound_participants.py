"""Who is on a loan file, and whether their mail may be trusted (LP-805).

SEEDED FROM WHAT ALREADY EXISTS. `borrowers.email`, `loan_files.loan_officer_email` and
`lenders.contact_email` are populated today, so the allowlist is real on day one rather than a table
somebody has to fill in before the feature works.

WITH ONE CORRECTION MADE IN LP-813. "`lenders.contact_email` is populated today" was true of the
seed script and of nothing else: there was no create or update path for a lender anywhere in the
product, so on any real installation that source was always NULL. LP-813 adds the write path and the
named underwriter assigned to the file, which is the source this actually wanted — an institution's
generic mailbox is not who a processor corresponds with.

MEMBERSHIP IS NOT TRUST. `phase4.md` §2.3 makes quarantine the default: a participant is somebody we
recognise, and `is_trusted_sender` is a separate, opt-in fact about whether their attachments may
skip a human. Seeding sets membership and never sets trust — an estate agent belongs on the file and
is not somebody whose mail should be accepted unreviewed.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.borrower import Borrower
from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.models.loan_file_participant import LoanFileParticipant, ParticipantRole

logger = get_logger(__name__)


def normalise_address(raw: str | None) -> str | None:
    """An address in the form participants are stored and compared in, or None.

    Lowercased and stripped of display name and angle brackets. Comparison is what this exists for:
    a case-sensitive match fails to recognise a borrower whose own client capitalised their address,
    and sends their documents to triage every single time.
    """
    if not raw:
        return None
    candidate = raw.strip()
    if "<" in candidate and ">" in candidate:
        candidate = candidate[candidate.rfind("<") + 1 : candidate.rfind(">")]
    candidate = candidate.strip().lower()
    return candidate if "@" in candidate else None


async def seed_participants(db: AsyncSession, *, loan_file: LoanFile) -> int:
    """Populate the file's participant list from the data already on it. Returns rows added.

    IDEMPOTENT AND NON-DESTRUCTIVE. It runs again whenever a borrower's email is edited or a loan
    officer is assigned, so it converges rather than accumulating — and it never clears
    `is_trusted_sender` on a row that already exists, because that is a decision a person made and
    re-seeding must not quietly undo it.
    """
    candidates: list[tuple[str, ParticipantRole, str | None]] = []

    borrowers = (
        (
            await db.execute(
                only_active(select(Borrower).where(Borrower.loan_file_id == loan_file.id), Borrower)
            )
        )
        .scalars()
        .all()
    )
    for index, borrower in enumerate(borrowers):
        borrower_email = normalise_address(borrower.email)
        if borrower_email is None:
            continue
        # The FIRST borrower is the borrower; the rest are co-borrowers. Ordering by creation is what
        # every other view of this file already does, so the roles agree with what a processor sees.
        role = ParticipantRole.BORROWER if index == 0 else ParticipantRole.CO_BORROWER
        name = " ".join(part for part in (borrower.first_name, borrower.last_name) if part)
        candidates.append((borrower_email, role, name or None))

    if (officer := normalise_address(loan_file.loan_officer_email)) is not None:
        candidates.append((officer, ParticipantRole.LOAN_OFFICER, loan_file.loan_officer_name))

    # THE ASSIGNED UNDERWRITER FIRST (LP-813), so they win the address if the lender's generic
    # mailbox happens to be the same string. A named person with the role UNDERWRITER is strictly
    # more information than an institution with the role OTHER, and the de-duplication below keeps
    # whichever candidate it saw first.
    if loan_file.underwriter_contact_id is not None:
        from app.models.lender_contact import LenderContact

        underwriter = await db.get(LenderContact, loan_file.underwriter_contact_id)
        if (
            underwriter is not None
            and underwriter.deleted_at is None
            and (address := normalise_address(underwriter.email)) is not None
        ):
            candidates.append((address, ParticipantRole.UNDERWRITER, underwriter.name))

    if loan_file.lender_id is not None:
        from app.models.lender import Lender

        lender = await db.get(Lender, loan_file.lender_id)
        if lender is not None and (contact := normalise_address(lender.contact_email)) is not None:
            candidates.append((contact, ParticipantRole.OTHER, lender.name))

    existing: set[str] = {
        row.email
        for row in (
            (
                await db.execute(
                    select(LoanFileParticipant).where(
                        LoanFileParticipant.loan_file_id == loan_file.id
                    )
                )
            )
            .scalars()
            .all()
        )
    }

    added = 0
    seen: set[str] = set()
    for email, role, display_name in candidates:
        if email in existing or email in seen:
            continue
        seen.add(email)
        db.add(
            LoanFileParticipant(
                loan_file_id=loan_file.id,
                role=role,
                name=display_name,
                email=email,
                # NEVER SET HERE. Trust is a decision a person makes; seeding establishes only that
                # we recognise the address.
                is_trusted_sender=False,
            )
        )
        added += 1

    await db.flush()
    # A COUNT, never an address.
    logger.info("participants_seeded", added=added, existing=len(existing))
    return added


async def is_participant(db: AsyncSession, *, loan_file_id: UUID, address: str | None) -> bool:
    """Whether this address is on the file. Case-insensitive; a malformed address is not."""
    normalised = normalise_address(address)
    if normalised is None:
        return False
    found = await db.scalar(
        only_active(
            select(LoanFileParticipant.id).where(
                LoanFileParticipant.loan_file_id == loan_file_id,
                LoanFileParticipant.email == normalised,
            ),
            LoanFileParticipant,
        )
    )
    return found is not None


async def is_trusted_sender(db: AsyncSession, *, loan_file_id: UUID, address: str | None) -> bool:
    """Whether this address may have its mail accepted without a human looking.

    A SEPARATE QUESTION FROM MEMBERSHIP, and both have to be true. Collapsing them would make every
    seeded borrower trusted the moment their email was recorded, which is the opposite of §2.3's
    "quarantine is the default, not the exception".
    """
    normalised = normalise_address(address)
    if normalised is None:
        return False
    found = await db.scalar(
        only_active(
            select(LoanFileParticipant.id).where(
                LoanFileParticipant.loan_file_id == loan_file_id,
                LoanFileParticipant.email == normalised,
                LoanFileParticipant.is_trusted_sender.is_(True),
            ),
            LoanFileParticipant,
        )
    )
    return found is not None


__all__ = [
    "is_participant",
    "is_trusted_sender",
    "normalise_address",
    "seed_participants",
]

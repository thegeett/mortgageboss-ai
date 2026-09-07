"""Asking somebody who is not the borrower (LP-820).

THE MEASUREMENT THAT SHAPED THIS TICKET. LP-800 sorts 166 document types to eight parties, and
before this ticket only one of them could be written to. Counted:

    borrower   113   `borrowers.email`                          reachable
    processor   24   orders it themselves — needs no request     n/a by design
    lender      16   `lenders.contact_email` / the underwriter   reachable since LP-813
    title        5   role existed, NO WRITER                     unreachable
    agent        3   role existed, NO WRITER                     unreachable
    cpa          2   no column anywhere in the schema            unreachable
    insurer      2   no column anywhere in the schema            unreachable
    employer     1   no column anywhere in the schema            unreachable

So 13 document types across four parties had no address in the product at all, and the build plan's
own words for the consequence are exact: they *"sit at PENDING forever, never get `requested_at`,
and are invisible to LP-814."* A per-party clock without a per-party address is a reminder nobody
can act on — which is why this module starts with the address book and not with the draft.

`loan_file_participants` IS THE ADDRESS BOOK, and it already was one. LP-805 built it as the
allowlist the trust decision needs, seeded from the data that existed; the roles for `agent` and
`title` were there from the start with nothing writing them. LP-820 adds `employer`, `cpa` and
`insurer`, and a way for a processor to put an address in — which makes the same table answer both
questions it was always shaped to answer: *may this sender post documents here*, and *where do I
send this request*.

ONE DRAFT PER PARTY, NOT ONE PER NEED. The one-open-draft index is `(loan_file_id, template_key)`,
so each party gets its own key and its own accumulating request — a title company asked for five
documents gets one email, and asking them for a sixth adds a line rather than sending a second.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.documents.catalog import ResponsibleParty, get_guidance
from app.models.communication import Communication
from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.models.loan_file_participant import LoanFileParticipant, ParticipantRole
from app.models.needs_item import NeedsItem, NeedsItemStatus

logger = get_logger(__name__)

#: Which participant role holds a document a given party is responsible for.
#:
#: `PROCESSOR` IS ABSENT, and its absence is the rule rather than an omission: the catalog's own
#: docstring says a processor "orders it themselves and no borrower-facing request should be
#: generated". A party that cannot be written to is different from one that must not be — and
#: mapping `PROCESSOR` to anything would turn "we fetch this" into "we email somebody about it".
PARTY_ROLE: dict[ResponsibleParty, ParticipantRole] = {
    ResponsibleParty.BORROWER: ParticipantRole.BORROWER,
    ResponsibleParty.LENDER: ParticipantRole.UNDERWRITER,
    ResponsibleParty.TITLE: ParticipantRole.TITLE,
    ResponsibleParty.EMPLOYER: ParticipantRole.EMPLOYER,
    ResponsibleParty.CPA: ParticipantRole.CPA,
    ResponsibleParty.AGENT: ParticipantRole.AGENT,
    ResponsibleParty.INSURER: ParticipantRole.INSURER,
}


#: The template key each party's accumulating request uses.
#:
#: ONE PER PARTY, because the one-open-draft index is `(loan_file_id, template_key)`: a single key
#: would make a title request and a CPA request collide, and the second would be refused by the
#: database with an error about a draft the processor cannot see.
def template_key_for(party: ResponsibleParty) -> str:
    return f"document_request_{party.value}"


@dataclass(frozen=True)
class PartyRequest:
    """One party, what they are being asked for, and whether we can reach them."""

    party: ResponsibleParty
    role: ParticipantRole
    #: Where the request would go, or None — which is the whole point of this type existing.
    address: str | None
    #: The participant row, so a caller can show a name beside the address.
    name: str | None
    needs: tuple[NeedsItem, ...]

    @property
    def reachable(self) -> bool:
        return self.address is not None


def party_for(need: NeedsItem) -> ResponsibleParty:
    """Who holds this document.

    AN UNTYPED NEED IS THE BORROWER'S, matching `_is_borrower_facing`'s reasoning exactly: those
    needs were created by a processor clicking "request documents", so the decision to ask the
    borrower has already been made by a person. LP-800's processor default protects against a
    document nobody classified; it must not veto a request somebody made.
    """
    if need.needs_type is None:
        return ResponsibleParty.BORROWER
    return get_guidance(need.needs_type).responsible_party


async def _addresses(
    db: AsyncSession, *, loan_file: LoanFile
) -> dict[ParticipantRole, tuple[str, str | None]]:
    """`{role: (address, name)}` for this file's participants.

    FIRST WINS PER ROLE, ordered by creation. Two title companies on one file is a data problem a
    processor can see and fix; picking arbitrarily between them and sending to one is a problem
    nobody sees at all.
    """
    rows = (
        (
            await db.execute(
                only_active(
                    select(LoanFileParticipant)
                    .where(LoanFileParticipant.loan_file_id == loan_file.id)
                    # `id` BREAKS THE TIE. `created_at` is a Python-side default, so two rows
                    # written in one flush differ by microseconds and the order is stable in
                    # practice — measured. It is not TOTAL, though, and "first wins" is a claim
                    # about a total order. A tie makes the choice undefined, which is exactly the
                    # "problem nobody sees" this docstring is about.
                    .order_by(LoanFileParticipant.created_at, LoanFileParticipant.id),
                    LoanFileParticipant,
                )
            )
        )
        .scalars()
        .all()
    )
    found: dict[ParticipantRole, tuple[str, str | None]] = {}
    for row in rows:
        if row.email and row.role not in found:
            found[row.role] = (row.email, row.name)

    # THE LENDER'S OWN DESK, WHEN NO UNDERWRITER IS ASSIGNED.
    #
    # `PARTY_ROLE` sends the lender party to `UNDERWRITER`, which is right when one is assigned —
    # the underwriter is who a processor corresponds with. But `lenders.contact_email` exists, LP-813
    # built the write path for it precisely because it had none, its docstring says it is "for direct
    # underwriter communication", and LP-805 seeds it as a participant under `OTHER` because the enum
    # has no generic lender role. So the address was on the file, trusted for inbound, and invisible
    # here: a file with a lender contact and no assigned underwriter reported its sixteen
    # lender-party document types as UNREACHABLE — "nothing to do" — with a usable address sitting on
    # it.
    #
    # Read from `Lender` rather than by hunting for the `OTHER` row it was seeded into: which `OTHER`
    # came from the lender is a guess, and the column is not.
    if ParticipantRole.UNDERWRITER not in found and loan_file.lender_id is not None:
        from app.models.lender import Lender

        lender = await db.get(Lender, loan_file.lender_id)
        if lender is not None and lender.deleted_at is None and lender.contact_email:
            found[ParticipantRole.UNDERWRITER] = (lender.contact_email, lender.name)
    return found


async def open_requests(db: AsyncSession, *, loan_file: LoanFile) -> list[PartyRequest]:
    """Everything outstanding on this file, grouped by who has to be asked.

    INCLUDES THE UNREACHABLE ONES, and that is the deliberate part. A party with needs and no
    address is exactly the state this ticket exists to make visible — the build plan's "sit at
    PENDING forever, invisible to LP-814" is what happens when the UI only shows what it can send.
    So the list carries `reachable = False` rather than dropping the row, and the screen asks for an
    address instead of pretending there is nothing to do.

    `PROCESSOR` NEEDS ARE EXCLUDED ENTIRELY. Nobody is emailed about them: the processor orders them.
    Showing them here with "no address" would read as a gap to fill.
    """
    needs = (
        (
            await db.execute(
                only_active(
                    select(NeedsItem).where(
                        NeedsItem.loan_file_id == loan_file.id,
                        NeedsItem.status.in_([NeedsItemStatus.PENDING, NeedsItemStatus.REJECTED]),
                    ),
                    NeedsItem,
                )
            )
        )
        .scalars()
        .all()
    )
    addresses = await _addresses(db, loan_file=loan_file)

    grouped: dict[ResponsibleParty, list[NeedsItem]] = {}
    for need in needs:
        party = party_for(need)
        if party is ResponsibleParty.PROCESSOR:
            continue
        grouped.setdefault(party, []).append(need)

    requests: list[PartyRequest] = []
    for party, items in grouped.items():
        role = PARTY_ROLE[party]
        address, name = addresses.get(role, (None, None))
        requests.append(
            PartyRequest(
                party=party,
                role=role,
                address=address,
                name=name,
                needs=tuple(sorted(items, key=lambda item: item.title)),
            )
        )
    # Reachable first, then by party name — a processor can act on the top of this list, and the
    # unreachable ones below it are a different job (find an address) rather than a failed one.
    requests.sort(key=lambda request: (not request.reachable, request.party.value))
    return requests


async def build_party_draft(
    db: AsyncSession, *, loan_file: LoanFile, party: ResponsibleParty, actor_user_id: UUID
) -> Communication:
    """The accumulating request for one non-borrower party. ``flush`` only; the caller commits.

    A REAL DRAFT ON THE EXISTING SEND PATH, not a parallel one. It carries the same
    `communication_needs_items` join, so LP-811a's `send_draft` calls `request_needs_item` on every
    need in it — which is what stamps `requested_at` and starts LP-814's clock. The build plan's
    complaint was precisely that these needs "never get `requested_at`, and are invisible to
    LP-814"; using the same send path is what fixes that rather than a second one that would have to
    remember to.

    ITS OWN `template_key`, so the one-open-draft index gives each party its own. A single key would
    make a title request and a CPA request collide, and the second would be refused by the database
    with an error about a draft the processor cannot see.

    THE BODY IS THE SAME RENDERER. `render_draft_body` writes to whoever is reading with the
    catalog's guidance per document — which is written for the party that HOLDS the document, so a
    title company reading it gets the instructions meant for them. The greeting is the one thing
    that would be wrong, and it is generic in the template rather than addressed to a borrower.
    """
    from app.models.communication import CommunicationDirection, CommunicationStatus
    from app.models.communication_needs_item import CommunicationNeedsItem
    from app.services.email_draft import render_draft_body

    if party is ResponsibleParty.PROCESSOR:
        raise ValueError("A processor orders these; there is nobody to send a request to.")

    requests = {request.party: request for request in await open_requests(db, loan_file=loan_file)}
    request = requests.get(party)
    if request is None or not request.needs:
        raise ValueError("There is nothing outstanding for that party on this file.")
    if request.address is None:
        # REFUSED, NOT DRAFTED. A draft addressed to nobody is a message that will never be sent and
        # a clock that will never start — the exact state this ticket exists to end.
        raise ValueError("There is no address on this file for that party.")

    key = template_key_for(party)
    draft = (
        await db.execute(
            only_active(
                select(Communication).where(
                    Communication.loan_file_id == loan_file.id,
                    Communication.status == CommunicationStatus.DRAFT,
                    Communication.template_key == key,
                ),
                Communication,
            )
        )
    ).scalar_one_or_none()

    if draft is None:
        draft = Communication(
            loan_file_id=loan_file.id,
            direction=CommunicationDirection.OUTBOUND,
            status=CommunicationStatus.DRAFT,
            recipient=request.address,
            template_key=key,
            initiated_by_user_id=actor_user_id,
        )
        db.add(draft)
        await db.flush()
    else:
        # THE ADDRESS IS REFRESHED on every build. A processor who corrected a typo between opening
        # the draft and sending it must not send to the old one, and the draft is the thing they
        # will press send on.
        draft.recipient = request.address

    existing = set(
        (
            await db.execute(
                select(CommunicationNeedsItem.needs_item_id).where(
                    CommunicationNeedsItem.communication_id == draft.id
                )
            )
        )
        .scalars()
        .all()
    )
    for need in request.needs:
        if need.id not in existing:
            db.add(CommunicationNeedsItem(communication_id=draft.id, needs_item_id=need.id))
            existing.add(need.id)
    await db.flush()

    rendered = render_draft_body(loan_file, list(request.needs), framing=None)
    draft.subject = rendered.subject
    draft.body = rendered.body
    draft.template_version = rendered.version
    await db.flush()
    # A PARTY AND A COUNT. Never the address, never the document titles.
    logger.info(
        "party_draft_built",
        loan_file_id=str(loan_file.id),
        party=party.value,
        needs=len(request.needs),
    )
    return draft


async def add_participant(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    role: ParticipantRole,
    email: str,
    name: str | None = None,
) -> LoanFileParticipant:
    """Record where a party can be reached. ``flush`` only; the caller commits.

    NEVER SETS `is_trusted_sender`, exactly as LP-805's seeding does not. Membership is recognition;
    trust is a separate decision a person makes, and §2.3's default is quarantine. A title company
    a processor typed in is somebody we can write TO — it is not somebody whose attachments should
    bypass review.

    IDEMPOTENT ON THE ADDRESS, so a processor correcting a typo replaces the row rather than leaving
    the old address on the file to be picked by "first wins".
    """
    from app.services.inbound_participants import normalise_address

    normalised = normalise_address(email)
    if normalised is None:
        raise ValueError("That is not an address a request can be sent to.")

    existing = (
        (
            await db.execute(
                only_active(
                    select(LoanFileParticipant).where(
                        LoanFileParticipant.loan_file_id == loan_file.id,
                        LoanFileParticipant.role == role,
                    ),
                    LoanFileParticipant,
                )
            )
        )
        .scalars()
        .all()
    )
    for row in existing:
        if row.email == normalised:
            row.name = name or row.name
            await db.flush()
            return row

    participant = LoanFileParticipant(
        loan_file_id=loan_file.id,
        role=role,
        email=normalised,
        name=name,
        is_trusted_sender=False,
    )
    db.add(participant)
    await db.flush()
    # A ROLE AND A COUNT. Never the address, which identifies a person or a company.
    logger.info("party_address_added", loan_file_id=str(loan_file.id), role=role.value)
    return participant


async def remove_participant(
    db: AsyncSession, *, loan_file: LoanFile, participant_id: UUID
) -> bool:
    """Soft-delete one address. True if there was one to remove.

    The route proves the caller owns the FILE; this proves the participant is on it — the id is a
    path parameter anybody can type.
    """
    from app.models.base import utcnow

    participant = await db.get(LoanFileParticipant, participant_id)
    if (
        participant is None
        or participant.deleted_at is not None
        or participant.loan_file_id != loan_file.id
    ):
        return False
    participant.deleted_at = utcnow()
    await db.flush()
    return True


__all__ = [
    "PARTY_ROLE",
    "PartyRequest",
    "add_participant",
    "build_party_draft",
    "open_requests",
    "party_for",
    "remove_participant",
    "template_key_for",
]

"""One file's history, as one list (LP-812).

THE PROBLEM THIS TICKET EXISTS TO SETTLE. A single inbound arrival writes THREE rows: LP-803's
`inbound_message`, LP-805's `Communication(INBOUND, RECEIVED)`, and LP-805's
`ActivityLog(COMMUNICATION_RECEIVED)`. An outbound send writes two. The build plan noticed that no
ticket had reconciled them and asked this one to decide which is the timeline's row — because a
merge that takes each source on its own terms shows one arrival twice, and looks correct in every
test built from a single source.

**THE `Communication` IS THE TIMELINE'S ROW FOR A MESSAGE.** It already carries direction, status,
subject, recipient and `sent_at`, which is what a message needs to render. The `inbound_message` is
the raw artefact and its manifest; the activity entry is a description OF the Communication.

**THE `ActivityLog` IS THE TIMELINE'S ROW FOR EVERYTHING THAT IS NOT A MESSAGE** — a document
accepted, a need satisfied, a status change.

**SO EVERY `COMMUNICATION_*` ACTIVITY TYPE IS EXCLUDED**, and the exclusion is DERIVED FROM THE ENUM
rather than listed. Three of them exist today; a fourth added next month would otherwise appear
beside the Communication it describes, and the duplicate would look like two events. That is the
same failure the ticket is fixing, arriving later and by a different route.

WHAT THIS IS NOT. It is not an audit log — `activity_logs` remains complete and untouched, and
`phase4.md` §6 requires the communication record to be append-only evidence. This is a READ that
composes them for one screen. Nothing here writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.catalog import ResponsibleParty
from app.models.activity_log import ActivityType
from app.models.communication import (
    Communication,
    CommunicationDirection,
    CommunicationStatus,
)
from app.models.helpers import only_active
from app.models.inbound_attachment import InboundAttachment
from app.models.loan_file import LoanFile

#: Every activity type that DESCRIBES a `Communication` rather than being an event in its own right.
#:
#: DERIVED FROM THE ENUM, NOT LISTED. `COMMUNICATION_SENT`, `COMMUNICATION_RECEIVED` and
#: `COMMUNICATION_FAILED` are the three today. A fourth added later would, if this were a literal
#: tuple, appear on the timeline beside the very Communication it describes — which is exactly the
#: double-count this ticket exists to remove, arriving later and by a different route.
#:
#: The prefix is the contract. A future message-describing type that does NOT start with
#: `COMMUNICATION_` would slip through, which is why `test_every_communication_type_is_excluded`
#: asserts the set is non-empty and covers every member whose name matches — an empty derived set
#: reads exactly like a working one.
#: The activity types that describe a message — DERIVED from the enum, never listed.
#:
#: LP-825 — this is now a claim rather than a filter, and it is the claim the timeline rests on: an
#: activity belongs on a communication timeline only if it is about a message, and every activity
#: type that is about a message already has a `Communication` row carrying the same event. So there
#: is nothing left for an activity row to be, and `build_timeline` does not query the activity log
#: at all. Kept and exported because `test_the_three_message_activity_types_are_still_the_only_ones`
#: asserts it against the live enum: if a thirty-third type ever describes a message without being
#: named for one, that test is where it surfaces.
MESSAGE_ACTIVITY_TYPES: frozenset[ActivityType] = frozenset(
    activity for activity in ActivityType if activity.name.startswith("COMMUNICATION_")
)


class TimelineFilter(StrEnum):
    """`phase4.md` spec 4.3's filter pills."""

    ALL = "all"
    SENT = "sent"
    RECEIVED = "received"
    DRAFTS = "drafts"
    # NO `ACTIVITY` PILL SINCE LP-825. It could only ever match an activity row, and the timeline
    # has none — a pill that always answers "Nothing in activity" is a broken control, not a filter
    # with no results. The activity it named is on the file's Recent activity, where it belongs.


class TimelineKind(StrEnum):
    """What a row IS, so the client renders it without re-deriving the answer.

    ONE MEMBER SINCE LP-825, and it stays an enum rather than collapsing to a literal: the field is
    what a client branches on, and LP-829's message dialog is the next thing to add to it.
    """

    MESSAGE = "message"


@dataclass(frozen=True)
class TimelineAttachment:
    """One file on an inbound message, and what became of it.

    LP-825 REVIEW — THE DISPOSITION TRAVELS WITH THE NAME. The manifest was filenames alone, which
    renders identically whether a document was accepted into the file, kept as correspondence,
    rejected, or is still sitting there waiting for somebody. That gap did not matter while the
    activity log supplied the answer on the same screen: `inbound_triage` writes "A document arrived
    by email and was accepted" for every acceptance. LP-825 stopped the timeline reading activity at
    all, so the sentence went with it and nothing replaced it.

    This is the shape that ticket's own boundary rule asks for — give the event a communication-
    shaped row rather than reinstating the activity query — applied to the one event that needed it.
    """

    name: str
    #: `pending` / `accepted` / `correspondence` / `rejected` — `AttachmentDisposition`'s values.
    disposition: str


@dataclass(frozen=True)
class TimelineEntry:
    """One thing that happened on this file."""

    id: UUID
    kind: TimelineKind
    #: The moment it belongs at. See :func:`_message_at` for why this is not simply `created_at`.
    at: datetime
    summary: str
    #: `inbound` / `outbound` for a message; None for an activity.
    direction: str | None
    status: str | None
    subject: str | None
    counterparty: str | None
    actor_user_id: UUID | None
    #: The inbound message's attachments, each with what became of it. Empty for everything else.
    attachments: tuple[TimelineAttachment, ...]
    #: Flagged by a processor (LP-818). False on an activity, which cannot be flagged.
    is_important: bool
    #: True for an INBOUND message nobody has opened. False for everything else, including outbound
    #: — we wrote those, so "unread" is not a state they can be in.
    unread: bool
    detail: dict[str, Any]
    #: LP-841 — which party's bucket this belongs in (`borrower`, `lender`, `title`, `employer`,
    #: …), or None for anything that is not addressed to a party: an activity, a notification, a
    #: template this build does not recognise. The tabs read this rather than deriving it from the
    #: template key, so the bucket a draft is FILED under and the bucket it is SHOWN in are one
    #: decision made once. Defaulted, because an activity has no party and every caller that builds
    #: one would otherwise have to say so.
    party: str | None = None


async def _party_by_address(
    db: AsyncSession, *, loan_file: LoanFile
) -> dict[str, ResponsibleParty]:
    """`{email: party}` for everybody on this file — how an INBOUND message finds its bucket.

    An outbound message says who it is for in its template key. An inbound one does not: replies all
    arrive at the same per-file inbox address (ADR-397), so the address they came TO says nothing
    about who sent them. The sender address is the only evidence there is, and the participants
    table is where this file records it.
    """
    from app.services.email_draft import primary_borrower
    from app.services.party_requests import PARTY_ROLE, party_addresses

    found: dict[str, ResponsibleParty] = {}
    borrower = await primary_borrower(db, loan_file_id=loan_file.id)
    if borrower and borrower.email:
        found[borrower.email.strip().lower()] = ResponsibleParty.BORROWER
    addresses = await party_addresses(db, loan_file=loan_file)
    for party, role in PARTY_ROLE.items():
        for address in addresses.get(role, ()):
            # A participant with no address on file is real and common (LP-841 allows an empty To).
            # They contribute nothing to a lookup BY address, which is different from contributing
            # nothing at all — their tab still appears, because their drafts carry the template key.
            if not address:
                continue
            # First writer wins, so the borrower's own address stays the borrower's even if they are
            # also recorded in another role on this file.
            found.setdefault(address.strip().lower(), party)
    return found


def _party_of(
    message: Communication,
    *,
    senders: dict[UUID, str | None],
    by_address: dict[str, ResponsibleParty],
) -> str | None:
    """Which party's tab this message belongs in, or None for one that belongs in no tab.

    NONE IS A REAL ANSWER, not a fallback. An inbound message from an address nobody on this file
    recognises — a spam reply, a forward from a third party, a borrower writing from an address we
    were never given — has no party, and filing it under the borrower because that is the common
    case would put a stranger's mail in the borrower's thread. It shows on the unfiltered list,
    which is where something we cannot place belongs.
    """
    if message.direction is CommunicationDirection.INBOUND:
        sender = message.sender or (
            senders.get(message.inbound_message_id) if message.inbound_message_id else None
        )
        party = by_address.get(sender.strip().lower()) if sender else None
        return party.value if party else None
    from app.services.email_draft import party_for_draft_template

    # LP-843 — THE STORED AUDIENCE FIRST. `template_key` answered this until five parties came to
    # share one template, at which point it stopped being able to: a lender draft and a title draft
    # are both `document_request_third_party`, and deriving the bucket from the key would put them
    # in one tab. The key remains the fallback for a draft written before the column existed.
    if message.party:
        return message.party
    party = party_for_draft_template(message.template_key)
    return party.value if party else None


def _message_at(message: Communication) -> datetime:
    """When a message belongs on the timeline.

    `sent_at` WHEN THERE IS ONE, and `created_at` otherwise. A draft composed on Monday and sent on
    Thursday belongs at Thursday — that is when the borrower heard from us, and a timeline ordered by
    composition would put the send before a reminder that actually preceded it.

    An inbound message has no `sent_at` (that column is about outbound; LP-805 says so explicitly and
    declines to reuse it for a received-at), so it falls to `created_at`, which is when we ingested
    it. The message's own `received_at` lives on the `inbound_message` row and is the better answer;
    using it would mean joining that table just to order this list, and the two differ by the ingest
    lag — seconds, except on the nights staging is asleep.
    """
    return message.sent_at or message.created_at


def _summarise(message: Communication) -> str:
    """One line describing a message, in a processor's words.

    NEVER THE BODY. `phase4.md`'s standing rule is that message content stays out of anything that
    is not the message itself; a timeline is a list of what happened, and the subject is already
    more than most rows need.
    """
    if message.direction is CommunicationDirection.INBOUND:
        return "A message arrived"
    if message.status is CommunicationStatus.DRAFT:
        return "A document request is being prepared"
    if message.status is CommunicationStatus.QUEUED:
        return "An automatic reply is queued"
    if message.status is CommunicationStatus.FAILED:
        return "A message could not be delivered"
    return "A message was sent"


async def _inbound_senders(db: AsyncSession, message_ids: list[UUID]) -> dict[UUID, str | None]:
    """`{inbound_message_id: from_address}` for the rows that have one.

    THE COMMUNICATION CARRIES NO SENDER, DELIBERATELY. LP-805 declined to copy it: "NO subject, NO
    body, NO sender. They are on the inbound_message row, which the readonly view already drops;
    copying them here would put borrower prose in a second place with its own exposure decisions."

    That decision is right and it left the timeline saying "A message arrived" with no From — which
    LP-818 could not live with, because a processor cannot decide whether to reply to something
    without knowing who sent it. Read here, from the row that already holds it, rather than
    denormalised into a second copy.
    """
    if not message_ids:
        return {}
    from app.models.inbound_message import InboundMessage

    rows = (
        (
            await db.execute(
                only_active(
                    select(InboundMessage).where(InboundMessage.id.in_(message_ids)),
                    InboundMessage,
                )
            )
        )
        .scalars()
        .all()
    )
    return {row.id: row.from_address for row in rows}


async def _attachment_manifest(
    db: AsyncSession, message_ids: list[UUID]
) -> dict[UUID, tuple[TimelineAttachment, ...]]:
    """`{inbound_message_id: attachments}` for the manifest, in one query.

    ONE QUERY FOR THE WHOLE PAGE rather than one per row: a timeline is a list, and a per-row lookup
    is the N+1 that turns a fast screen into a slow one as a file accumulates history.

    `filename_original` — what the SENDER called it. The same deliberate exception LP-806's schema
    documents: a processor scanning a timeline recognises "March statement.pdf" and does not
    recognise its normalised form. Rendered as text, never as markup.
    """
    if not message_ids:
        return {}
    rows = (
        (
            await db.execute(
                only_active(
                    select(InboundAttachment).where(
                        InboundAttachment.inbound_message_id.in_(message_ids)
                    ),
                    InboundAttachment,
                )
            )
        )
        .scalars()
        .all()
    )
    grouped: dict[UUID, list[TimelineAttachment]] = {}
    for row in rows:
        name = row.filename_original or row.filename_normalized
        if name:
            grouped.setdefault(row.inbound_message_id, []).append(
                TimelineAttachment(name=name, disposition=row.disposition.value)
            )
    return {key: tuple(value) for key, value in grouped.items()}


def _matches(entry: TimelineEntry, wanted: TimelineFilter) -> bool:
    """Whether a row survives a filter pill.

    `DRAFTS` INCLUDES QUEUED. A queued automatic reply is a message not yet gone, which is what a
    processor means by looking at drafts — and it is the one state nobody else's pill would show, so
    excluding it here would make it invisible on every view.
    """
    if wanted is TimelineFilter.ALL:
        return True
    if wanted is TimelineFilter.RECEIVED:
        return entry.direction == CommunicationDirection.INBOUND.value
    if wanted is TimelineFilter.DRAFTS:
        return entry.status in {
            CommunicationStatus.DRAFT.value,
            CommunicationStatus.QUEUED.value,
        }
    # SENT: outbound and gone. A draft is outbound and has not gone, and showing it under "sent"
    # would tell a processor they had already asked for something they have not.
    return entry.direction == CommunicationDirection.OUTBOUND.value and entry.status in {
        CommunicationStatus.SENT.value,
        CommunicationStatus.DELIVERED.value,
        CommunicationStatus.FAILED.value,
    }


async def build_timeline(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    wanted: TimelineFilter = TimelineFilter.ALL,
    limit: int = 200,
) -> tuple[list[TimelineEntry], bool]:
    """This file's MESSAGES, newest first, with each event appearing once.

    LP-825 — NO ACTIVITY ROWS, AND THAT IS DERIVED RATHER THAN CHOSEN. A processor reported the
    Communication page carrying the whole file's history: on LF-JR4T, ten of eleven recent rows were
    document classifications, DTI overrides and field reviews. The cause was that this query said
    ``notin_(MESSAGE_ACTIVITY_TYPES)`` — written as "drop the three duplicates", meaning "keep the
    other twenty-nine".

    The fix is not a longer exclusion list and not an allow-list either. Both are enumerations, and
    an enumeration goes stale the moment somebody adds an `ActivityType`. The derivation is already
    here: an activity belongs on a COMMUNICATION timeline only if it is about a message;
    ``MESSAGE_ACTIVITY_TYPES`` is exactly the set of activity types about messages, derived from the
    enum; and every one of those is excluded because the ``Communication`` row is already the entry.
    Nothing is left. So the timeline is messages, and a thirty-third activity type inherits that by
    construction rather than by being remembered.

    The rest of the history has a home: the file's Recent activity, which is what it always
    described.

    Returns the entries AND whether the cap bit. A truncated timeline that does not say so is the
    wrong failure: it reads as a complete history, and the entries it drops are the OLDEST — so a
    processor looking for the message that started a thread finds a page that looks whole and does
    not contain it. Until this is paginated, the screen at least has to be able to say that there
    is more.

    THE FILTER IS APPLIED AFTER THE MERGE, not inside each query. Two filtered queries would each
    have to know which rows the other was responsible for, and the pill definitions would then live
    in two places that can disagree — which is how a "sent" pill starts showing drafts.
    """
    messages = (
        (
            await db.execute(
                only_active(
                    select(Communication).where(Communication.loan_file_id == loan_file.id),
                    Communication,
                )
            )
        )
        .scalars()
        .all()
    )
    inbound_ids = [m.inbound_message_id for m in messages if m.inbound_message_id is not None]
    manifests = await _attachment_manifest(db, inbound_ids)
    senders = await _inbound_senders(db, inbound_ids)
    by_address = await _party_by_address(db, loan_file=loan_file)

    entries: list[TimelineEntry] = [
        TimelineEntry(
            id=message.id,
            kind=TimelineKind.MESSAGE,
            at=_message_at(message),
            summary=_summarise(message),
            direction=message.direction.value,
            status=message.status.value,
            subject=message.subject,
            counterparty=(
                # INBOUND: read from the stored message, because the Communication has no sender by
                # LP-805's deliberate choice. `message.sender` is tried first anyway, so a future
                # writer of that column is not silently ignored.
                (
                    message.sender
                    or (
                        senders.get(message.inbound_message_id)
                        if message.inbound_message_id
                        else None
                    )
                )
                if message.direction is CommunicationDirection.INBOUND
                else message.recipient
            ),
            actor_user_id=message.initiated_by_user_id,
            attachments=(
                manifests.get(message.inbound_message_id, ()) if message.inbound_message_id else ()
            ),
            is_important=message.is_important,
            unread=(
                message.direction is CommunicationDirection.INBOUND and message.read_at is None
            ),
            party=_party_of(message, senders=senders, by_address=by_address),
            detail={
                "template_key": message.template_key,
                "template_version": message.template_version,
                "error_detail": message.error_detail,
            },
        )
        for message in messages
    ]

    entries.sort(key=lambda entry: entry.at, reverse=True)
    matched = [entry for entry in entries if _matches(entry, wanted)]
    return matched[:limit], len(matched) > limit


__all__ = [
    "MESSAGE_ACTIVITY_TYPES",
    "TimelineEntry",
    "TimelineFilter",
    "TimelineKind",
    "build_timeline",
]

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

from app.models.activity_log import ActivityLog, ActivityType
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
MESSAGE_ACTIVITY_TYPES: frozenset[ActivityType] = frozenset(
    activity for activity in ActivityType if activity.name.startswith("COMMUNICATION_")
)


class TimelineFilter(StrEnum):
    """`phase4.md` spec 4.3's filter pills."""

    ALL = "all"
    SENT = "sent"
    RECEIVED = "received"
    DRAFTS = "drafts"
    ACTIVITY = "activity"


class TimelineKind(StrEnum):
    """What a row IS, so the client renders it without re-deriving the answer."""

    MESSAGE = "message"
    ACTIVITY = "activity"


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
    #: Filenames on an inbound message, for the manifest. Empty for everything else.
    attachments: tuple[str, ...]
    detail: dict[str, Any]


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


async def _attachment_names(
    db: AsyncSession, message_ids: list[UUID]
) -> dict[UUID, tuple[str, ...]]:
    """`{inbound_message_id: filenames}` for the manifest, in one query.

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
    grouped: dict[UUID, list[str]] = {}
    for row in rows:
        name = row.filename_original or row.filename_normalized
        if name:
            grouped.setdefault(row.inbound_message_id, []).append(name)
    return {key: tuple(value) for key, value in grouped.items()}


def _matches(entry: TimelineEntry, wanted: TimelineFilter) -> bool:
    """Whether a row survives a filter pill.

    `DRAFTS` INCLUDES QUEUED. A queued automatic reply is a message not yet gone, which is what a
    processor means by looking at drafts — and it is the one state nobody else's pill would show, so
    excluding it here would make it invisible on every view.
    """
    if wanted is TimelineFilter.ALL:
        return True
    if wanted is TimelineFilter.ACTIVITY:
        return entry.kind is TimelineKind.ACTIVITY
    if entry.kind is not TimelineKind.MESSAGE:
        return False
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
) -> list[TimelineEntry]:
    """This file's messages and activity, newest first, with each event appearing once.

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
    activities = (
        (
            await db.execute(
                only_active(
                    select(ActivityLog).where(
                        ActivityLog.loan_file_id == loan_file.id,
                        # THE RECONCILIATION, in one clause. Every activity that describes a
                        # Communication is dropped, because that Communication is already a row.
                        ActivityLog.activity_type.notin_(MESSAGE_ACTIVITY_TYPES),
                    ),
                    ActivityLog,
                )
            )
        )
        .scalars()
        .all()
    )

    manifests = await _attachment_names(
        db, [m.inbound_message_id for m in messages if m.inbound_message_id is not None]
    )

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
                message.sender
                if message.direction is CommunicationDirection.INBOUND
                else message.recipient
            ),
            actor_user_id=message.initiated_by_user_id,
            attachments=(
                manifests.get(message.inbound_message_id, ()) if message.inbound_message_id else ()
            ),
            detail={
                "template_key": message.template_key,
                "template_version": message.template_version,
                "error_detail": message.error_detail,
            },
        )
        for message in messages
    ] + [
        TimelineEntry(
            id=activity.id,
            kind=TimelineKind.ACTIVITY,
            at=activity.created_at,
            summary=activity.summary,
            direction=None,
            status=None,
            subject=None,
            counterparty=None,
            actor_user_id=activity.actor_user_id,
            attachments=(),
            detail=dict(activity.detail or {}),
        )
        for activity in activities
    ]

    entries.sort(key=lambda entry: entry.at, reverse=True)
    return [entry for entry in entries if _matches(entry, wanted)][:limit]


__all__ = [
    "MESSAGE_ACTIVITY_TYPES",
    "TimelineEntry",
    "TimelineFilter",
    "TimelineKind",
    "build_timeline",
]

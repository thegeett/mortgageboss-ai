"""Reminder suggestions (LP-814) — three rules, and the clock each of them reads.

IT SUGGESTS AND NEVER SENDS. `phase4.md` spec 4.5 says so in those words, and it is the same rule
ADR-388 states for findings: flag, never close. Nothing in this module writes a message, queues one,
or moves a need — it produces a list a processor acts on.

THE CLOCK IS `requested_at`, AND THAT IS THE WHOLE DESIGN. §1.4: *"A reminder keyed on `created_at`
would nag about documents nobody has asked for yet."* `request_needs_item` had existed since LP-19
with zero callers until LP-811a, so `requested_at` was NULL on every row that had ever existed and
every rule here would have been a query over an empty set — green, silent, and unable to fire.

AND THE TRAP RUNS THE OTHER WAY TOO. LP-819 UNWINDS `requested_at` on a hard bounce: the borrower
never received the request, the need goes back to `PENDING`, and the stamp is cleared. That is
correct, and it means a bounced request correctly has **no clock**. A rule that fell back to
`created_at` when `requested_at` was NULL — which looks like tolerance — would nag hardest about
exactly the requests that never arrived, against a mailbox that does not exist, and every nudge
would bounce too. So the rules read `requested_at` and nothing else, and a need with no stamp
produces no suggestion.

WHY THERE IS NO CELERY BEAT. The plan says "Celery beat over `requested_at`". A beat that computes
suggestions and writes them changes nothing a read cannot do — it suggests only, so it has no side
effect worth scheduling — and it would be a table going stale the moment a document arrives, nudging
about something that turned up an hour ago. What a beat WOULD serve is reaching a processor who is
not looking, and that is a notification channel this product does not have yet. Recorded in the
ticket rather than built as a task nothing drains.

The cross-file read is what makes rule 3 possible at all: "this file has gone quiet" is by definition
about a file nobody is opening, so a per-file endpoint could never surface it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import ActivityLog
from app.models.base import utcnow
from app.models.communication import (
    Communication,
    CommunicationDirection,
    CommunicationStatus,
)
from app.models.helpers import only_active
from app.models.loan_file import LoanFile, LoanFileStatus
from app.models.needs_item import NeedsItem, NeedsItemStatus
from app.models.reminder_snooze import ReminderKind, ReminderSnooze

#: Spec 4.5's three thresholds, named rather than inlined so a later decision changes one place.
#:
#: BUSINESS DAYS ARE NOT USED, and that is worth stating because "3 days" reads like it should mean
#: them. A borrower's weekend is not a working day for them either — the clock is about how long
#: somebody has been waiting, not about how much work time has passed — and a business-day count
#: needs a holiday calendar per jurisdiction, which is a real dependency for a threshold nobody has
#: calibrated.
PENDING_AFTER = timedelta(days=3)
NO_REPLY_AFTER = timedelta(days=5)
UNTOUCHED_AFTER = timedelta(days=7)

#: Files these rules never fire on. A submitted or withdrawn file is not one somebody has forgotten
#: about — it is one that is finished, and nudging about it teaches a processor to ignore the list.
_CLOSED = frozenset({LoanFileStatus.SUBMITTED, LoanFileStatus.WITHDRAWN})


@dataclass(frozen=True)
class Suggestion:
    """One thing worth doing, and why it is being suggested."""

    loan_file_id: UUID
    display_id: str
    kind: ReminderKind
    #: The need or message it is about; None for a rule about the file.
    subject_id: UUID | None
    #: What a processor reads. Written by us, never composed and never a borrower's words.
    summary: str
    #: How long the thing has been true, in whole days. Shown so the list can be triaged by age.
    days: int
    #: The moment the clock started, so a card can say when rather than only how long ago.
    since: datetime


def _days(since: datetime, now: datetime) -> int:
    return max(0, (now - since).days)


async def _snoozes(db: AsyncSession, *, loan_file_ids: list[UUID]) -> list[ReminderSnooze]:
    if not loan_file_ids:
        return []
    return list(
        (
            await db.execute(
                select(ReminderSnooze).where(ReminderSnooze.loan_file_id.in_(loan_file_ids))
            )
        )
        .scalars()
        .all()
    )


async def _open_files(
    db: AsyncSession, *, company_id: UUID, loan_file: LoanFile | None
) -> list[LoanFile]:
    """The files these rules run over.

    COMPANY-SCOPED ALWAYS, even when one file is named: the caller passes a file that a scoped route
    already resolved, and re-checking costs one comparison against the alternative of a suggestion
    list built from a file somebody else owns.
    """
    if loan_file is not None:
        return [loan_file] if loan_file.company_id == company_id else []
    stmt = select(LoanFile).where(LoanFile.company_id == company_id)
    return list((await db.execute(only_active(stmt, LoanFile))).scalars().all())


async def _pending_needs(
    db: AsyncSession, *, file_ids: list[UUID], now: datetime
) -> list[tuple[UUID, UUID, str, datetime]]:
    """`(loan_file_id, needs_item_id, title, requested_at)` for needs asked for and not answered.

    `requested_at` IS THE WHOLE RULE. A need with no stamp has not been asked for — or was asked for
    and bounced, which LP-819 unwinds to exactly the same state, deliberately. Falling back to
    `created_at` would nag hardest about the requests that never arrived.

    THE `IS NOT NULL` CLAUSE STATES THE INTENT AND DOES NOT CHANGE THE ANSWER, which is worth saying
    rather than letting it read as load-bearing: SQL's three-valued logic already makes
    `NULL < timestamp` unknown, so the comparison below excludes an unstamped row on its own.
    Measured — removing the clause changes no test. It stays because a reader deciding whether this
    rule can fire on a bounced request should not have to know that.

    `status == REQUESTED` as well as the stamp, because a need that has since been satisfied by a
    document arriving another way keeps its `requested_at` and is not waiting for anything.
    """
    if not file_ids:
        return []
    rows = (
        (
            await db.execute(
                only_active(
                    select(NeedsItem).where(
                        NeedsItem.loan_file_id.in_(file_ids),
                        NeedsItem.status == NeedsItemStatus.REQUESTED,
                        NeedsItem.requested_at.is_not(None),
                        NeedsItem.requested_at < now - PENDING_AFTER,
                    ),
                    NeedsItem,
                )
            )
        )
        .scalars()
        .all()
    )
    return [
        (row.loan_file_id, row.id, row.title, row.requested_at)
        for row in rows
        if row.requested_at is not None
    ]


async def _unanswered_sends(
    db: AsyncSession, *, file_ids: list[UUID], now: datetime
) -> list[tuple[UUID, UUID, datetime]]:
    """`(loan_file_id, communication_id, sent_at)` for the last send on a file with nothing since.

    ONE PER FILE, not one per message. A processor who sent three requests and heard nothing has one
    problem, and three cards for it is a list they stop reading.

    "NOTHING SINCE" MEANS NOTHING INBOUND AFTER THE SEND — not "no inbound at all". A borrower who
    replied last month and has gone quiet since Tuesday's request is exactly the case this rule is
    for, and a query asking whether the file has ever received anything would miss it.
    """
    if not file_ids:
        return []
    latest_sends = (
        (
            await db.execute(
                only_active(
                    select(Communication).where(
                        Communication.loan_file_id.in_(file_ids),
                        Communication.direction == CommunicationDirection.OUTBOUND,
                        Communication.status.in_(
                            [CommunicationStatus.SENT, CommunicationStatus.DELIVERED]
                        ),
                        Communication.sent_at.is_not(None),
                        Communication.sent_at < now - NO_REPLY_AFTER,
                    ),
                    Communication,
                )
            )
        )
        .scalars()
        .all()
    )
    by_file: dict[UUID, Communication] = {}
    for row in latest_sends:
        current = by_file.get(row.loan_file_id)
        if current is None or (row.sent_at and current.sent_at and row.sent_at > current.sent_at):
            by_file[row.loan_file_id] = row
    if not by_file:
        return []

    replies = (
        (
            await db.execute(
                only_active(
                    select(Communication).where(
                        Communication.loan_file_id.in_(list(by_file)),
                        Communication.direction == CommunicationDirection.INBOUND,
                    ),
                    Communication,
                )
            )
        )
        .scalars()
        .all()
    )
    newest_inbound: dict[UUID, datetime] = {}
    for reply in replies:
        seen = newest_inbound.get(reply.loan_file_id)
        if seen is None or reply.created_at > seen:
            newest_inbound[reply.loan_file_id] = reply.created_at

    result: list[tuple[UUID, UUID, datetime]] = []
    for file_id, send in by_file.items():
        assert send.sent_at is not None  # filtered above
        answered_at = newest_inbound.get(file_id)
        if answered_at is not None and answered_at > send.sent_at:
            continue
        result.append((file_id, send.id, send.sent_at))
    return result


async def _untouched(
    db: AsyncSession, *, files: list[LoanFile], now: datetime
) -> list[tuple[UUID, datetime]]:
    """`(loan_file_id, last_activity_at)` for files where nothing at all has happened.

    THE ACTIVITY LOG IS THE CLOCK, not `loan_files.updated_at`. That column moves when anything on
    the row changes — including a status a background job wrote — so a file nobody has touched for a
    fortnight can look fresh because something recalculated. The activity log records what a person
    or a pipeline DID, which is the question.

    A FILE WITH NO ACTIVITY AT ALL falls back to when it was created. It is genuinely untouched, and
    skipping it would hide the newest files, which are the ones most likely to have been forgotten.
    """
    if not files:
        return []
    by_file = {loan_file.id: loan_file for loan_file in files}
    rows = (
        await db.execute(
            select(ActivityLog.loan_file_id, func.max(ActivityLog.created_at))
            .where(ActivityLog.loan_file_id.in_(list(by_file)))
            .group_by(ActivityLog.loan_file_id)
        )
    ).all()
    latest = {row[0]: row[1] for row in rows}

    result: list[tuple[UUID, datetime]] = []
    for file_id, loan_file in by_file.items():
        touched = latest.get(file_id) or loan_file.created_at
        if touched < now - UNTOUCHED_AFTER:
            result.append((file_id, touched))
    return result


async def build_suggestions(
    db: AsyncSession,
    *,
    company_id: UUID,
    loan_file: LoanFile | None = None,
    now: datetime | None = None,
) -> list[Suggestion]:
    """Everything worth a nudge, oldest problem first.

    COMPUTED ON EVERY READ. Nothing is stored but the decisions a processor made about them — see
    `models/reminder_snooze`. A materialised list goes stale the moment a document arrives, and a
    suggestion about something that turned up an hour ago is how a processor learns to ignore the
    whole list.
    """
    moment = now or utcnow()
    files = await _open_files(db, company_id=company_id, loan_file=loan_file)
    files = [f for f in files if f.status not in _CLOSED]
    if not files:
        return []
    file_ids = [f.id for f in files]
    display = {f.id: f.display_id for f in files}

    suggestions: list[Suggestion] = []

    for file_id, needs_id, title, requested_at in await _pending_needs(
        db, file_ids=file_ids, now=moment
    ):
        suggestions.append(
            Suggestion(
                loan_file_id=file_id,
                display_id=display[file_id],
                kind=ReminderKind.NEEDS_ITEM_PENDING,
                subject_id=needs_id,
                # THE NEED'S TITLE, which we wrote — it comes from the needs template or a
                # processor, never from a borrower's message.
                summary=f"{title} was requested {_days(requested_at, moment)} days ago",
                days=_days(requested_at, moment),
                since=requested_at,
            )
        )

    for file_id, communication_id, sent_at in await _unanswered_sends(
        db, file_ids=file_ids, now=moment
    ):
        suggestions.append(
            Suggestion(
                loan_file_id=file_id,
                display_id=display[file_id],
                kind=ReminderKind.NO_REPLY,
                subject_id=communication_id,
                summary=f"No reply since a message {_days(sent_at, moment)} days ago",
                days=_days(sent_at, moment),
                since=sent_at,
            )
        )

    for file_id, touched in await _untouched(db, files=files, now=moment):
        suggestions.append(
            Suggestion(
                loan_file_id=file_id,
                display_id=display[file_id],
                kind=ReminderKind.FILE_UNTOUCHED,
                subject_id=None,
                summary=f"Nothing has happened on this file for {_days(touched, moment)} days",
                days=_days(touched, moment),
                since=touched,
            )
        )

    suppressed = {
        (snooze.loan_file_id, snooze.kind, snooze.subject_id)
        for snooze in await _snoozes(db, loan_file_ids=file_ids)
        if snooze.suppresses(now=moment)
    }
    remaining = [
        suggestion
        for suggestion in suggestions
        if (suggestion.loan_file_id, suggestion.kind, suggestion.subject_id) not in suppressed
    ]
    # OLDEST FIRST. A list ordered by anything else buries the thing that has been waiting longest,
    # which is the one the rule exists to surface.
    remaining.sort(key=lambda suggestion: suggestion.since)
    return remaining


async def snooze(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    kind: ReminderKind,
    subject_id: UUID | None,
    until: datetime | None,
    note: str | None = None,
) -> ReminderSnooze:
    """Put a suggestion off, or refuse it outright with ``until=None``. ``flush`` only.

    IDEMPOTENT ON THE SUBJECT. Snoozing twice moves the date rather than raising — the unique index
    makes that structural, and a second click on a card is an ordinary thing a person does.
    """
    existing = (
        await db.execute(
            select(ReminderSnooze).where(
                ReminderSnooze.loan_file_id == loan_file.id,
                ReminderSnooze.kind == kind,
                ReminderSnooze.subject_id.is_(None)
                if subject_id is None
                else ReminderSnooze.subject_id == subject_id,
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.snoozed_until = until
        existing.note = note
        # UN-DELETED, not left soft-deleted. A row somebody previously un-snoozed and is now
        # snoozing again must take effect, and `suppresses` returns False while `deleted_at` is set.
        existing.deleted_at = None
        await db.flush()
        return existing

    row = ReminderSnooze(
        loan_file_id=loan_file.id,
        kind=kind,
        subject_id=subject_id,
        snoozed_until=until,
        note=note,
    )
    db.add(row)
    await db.flush()
    return row


async def unsnooze(
    db: AsyncSession, *, loan_file: LoanFile, kind: ReminderKind, subject_id: UUID | None
) -> bool:
    """Bring a suggestion back. True if there was one to bring back.

    SOFT-DELETES THE DECISION rather than hard-deleting it: the record that somebody put this off,
    and when, is the kind of thing a processor is asked about later.
    """
    existing = (
        await db.execute(
            select(ReminderSnooze).where(
                ReminderSnooze.loan_file_id == loan_file.id,
                ReminderSnooze.kind == kind,
                ReminderSnooze.subject_id.is_(None)
                if subject_id is None
                else ReminderSnooze.subject_id == subject_id,
            )
        )
    ).scalar_one_or_none()
    if existing is None or existing.deleted_at is not None:
        return False
    existing.deleted_at = utcnow()
    await db.flush()
    return True


__all__ = [
    "NO_REPLY_AFTER",
    "PENDING_AFTER",
    "UNTOUCHED_AFTER",
    "Suggestion",
    "build_suggestions",
    "snooze",
    "unsnooze",
]

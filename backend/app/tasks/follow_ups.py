"""LP-1013 — the job that sends automatic follow-up reminders, every 15 minutes.

Beat, every 15 minutes. Picks the original emails whose follow-up is `on` and whose due moment has
passed (`services.follow_ups.due_moment`: her time of day in her time zone, a weekend moved to
Monday), earliest first, at most `DUE_CAP` per run, each row locked `FOR UPDATE SKIP LOCKED`, and for
each asks `services.follow_ups.evaluate`:

- `finish` / `stop` → the status is set and nothing is sent;
- `due` → if the recipient has replied since the clock started, it pauses instead; otherwise the
  reminder is created and queued through `send_draft(transmit=True)`, from the original's sender,
  and handed to the worker after the commit, like any Send.

A refusal (`CannotSendError`) leaves the counts alone and the next run tries again; a blocked
recipient (`suppressed`) stops it. One summary log line per run, counts only.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from uuid import UUID

import structlog
from sqlalchemy import Select, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utcnow
from app.models.communication import (
    Communication,
    CommunicationDirection,
    CommunicationStatus,
    FollowUpStatus,
)
from app.models.company_mail_domain import CompanyMailDomain, MailDomainStatus
from app.models.loan_file import LoanFile
from app.services.email_send import CannotSendError
from app.services.follow_ups import (
    Decision,
    due_moment_sql,
    evaluate,
    has_reply_since,
    original_sender,
    send_reminder,
)
from app.tasks.base import BaseTask, run_async, task_session
from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)

#: At most this many emails per run; the rest wait for the next run, 15 minutes later.
DUE_CAP = 50


def candidates_stmt(now: datetime) -> Select[tuple[Communication]]:
    """Originals with follow-up `on`, the due moment reached and the count not reached, earliest due
    first, at most `DUE_CAP`, each locked; a row another run holds is skipped.

    ONLY WHAT CAN BE SENT NOW (review finding 2). A refused or skipped email is left as it is, so it
    stays the earliest due and is picked again every run; 50 of them would fill every run and no
    other company's reminder would go. So the query leaves out an original that has not gone out (it
    waits, still `queued` or `sending`; `failed` is picked, to be stopped), a file that is deleted, and
    a company that cannot send (`company_send_blocker`'s company half: no `active` domain, or sending switched
    off). Those emails wait, still due, and go on the first run after the company can send again.
    """
    due = due_moment_sql()
    company_can_send = exists().where(
        CompanyMailDomain.company_id == LoanFile.company_id,
        CompanyMailDomain.status == MailDomainStatus.ACTIVE,
        CompanyMailDomain.sending_enabled.is_(True),
    )
    return (
        select(Communication)
        .join(LoanFile, LoanFile.id == Communication.loan_file_id)
        .where(
            LoanFile.deleted_at.is_(None),
            Communication.status.in_(
                [
                    CommunicationStatus.SENT,
                    CommunicationStatus.DELIVERED,
                    CommunicationStatus.FAILED,
                ]
            ),
            company_can_send,
            Communication.direction == CommunicationDirection.OUTBOUND,
            Communication.follow_up_of_id.is_(None),
            Communication.send_requested_at.is_not(None),
            Communication.deleted_at.is_(None),
            Communication.follow_up_status == FollowUpStatus.ON,
            Communication.follow_up_auto_sent < Communication.follow_up_max_auto,
            Communication.follow_up_clock_at.is_not(None),
            Communication.follow_up_time.is_not(None),
            Communication.follow_up_tz.is_not(None),
            due <= now,
        )
        .order_by(due, Communication.id)
        .limit(DUE_CAP)
        .with_for_update(skip_locked=True, of=Communication)
    )


async def _one(db: AsyncSession, row: Communication, now: datetime) -> tuple[str, UUID | None]:
    """Handle one original. Returns the outcome code and the queued reminder's id, if any."""
    decision = await evaluate(db, row, now=now)
    if decision is Decision.FINISH:
        row.follow_up_status = FollowUpStatus.FINISHED
        return "finished", None
    if decision is Decision.STOP:
        row.follow_up_status = FollowUpStatus.STOPPED
        return "stopped_failed", None
    if decision is not Decision.DUE:
        return "not_due", None
    if await has_reply_since(db, row):
        row.follow_up_status = FollowUpStatus.PAUSED
        row.follow_up_paused_at = now
        return "paused_reply", None
    loan_file = await db.get(LoanFile, row.loan_file_id)
    assert loan_file is not None  # the query joins it
    sender = await original_sender(db, row)
    if sender is None:
        # Nothing records who sent it, and nothing will: stopped, or it is picked every run.
        row.follow_up_status = FollowUpStatus.STOPPED
        return "stopped_no_sender", None
    try:
        reminder = await send_reminder(
            db, loan_file=loan_file, original=row, sender=sender, automatic=True
        )
    except CannotSendError as exc:
        logger.info("follow_up_refused", communication_id=str(row.id), error_code=exc.code)
        if exc.code == "suppressed":
            row.follow_up_status = FollowUpStatus.STOPPED
            return "stopped_suppressed", None
        return f"refused_{exc.code}", None
    row.follow_up_auto_sent += 1
    row.follow_up_clock_at = now
    return "sent", reminder.id


async def send_follow_ups(db: AsyncSession, *, now: datetime | None = None) -> Counter[str]:
    """One run. ``now`` is for tests and the dev check; the job passes nothing."""
    from app.services.mail_sender import get_mail_sender

    moment = now or utcnow()
    outcomes: Counter[str] = Counter()
    if get_mail_sender() is None:  # no mail set up on this server: nothing could go
        logger.info("follow_ups_run", no_sender=1)
        return outcomes
    queued: list[UUID] = []
    for row in (await db.execute(candidates_stmt(moment))).scalars().all():
        try:
            async with db.begin_nested():
                code, reminder_id = await _one(db, row, moment)
        except Exception as exc:  # one bad row must not stop the rest
            logger.warning(
                "follow_up_failed", communication_id=str(row.id), error=type(exc).__name__
            )
            outcomes["error"] += 1
            continue
        outcomes[code] += 1
        if reminder_id is not None:
            queued.append(reminder_id)
    await db.commit()
    _enqueue(queued)
    logger.info("follow_ups_run", **dict(outcomes))
    return outcomes


def _enqueue(ids: list[UUID]) -> None:
    """After the commit, like the API's Send. A broker that is down leaves them to
    `communications.requeue_stale`."""
    from app.tasks.outbound import send_communication

    for pk in ids:
        try:
            send_communication.delay(str(pk))
        except Exception:
            logger.warning("send_enqueue_failed", communication_id=str(pk))


async def _run() -> dict[str, int]:
    async with task_session() as db:
        return dict(await send_follow_ups(db))


@celery_app.task(base=BaseTask, name="communications.send_follow_ups")  # type: ignore[untyped-decorator]
def send_follow_ups_task() -> dict[str, int]:
    """Beat, every 15 minutes: send the automatic follow-up reminders that are due (LP-1013)."""
    return run_async(_run())


__all__ = ["DUE_CAP", "candidates_stmt", "send_follow_ups", "send_follow_ups_task"]

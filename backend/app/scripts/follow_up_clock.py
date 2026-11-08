"""Move one email's follow-up conversation back N days, as if N days had passed (LP-1015).

Usage::

    python -m app.scripts.follow_up_clock <communication_id> --days N

For testing follow-ups without waiting. On the ORIGINAL email (never a reminder) it moves back by N
days every timestamp the follow-up job and the rate limit read:

- the original's follow-up clock (`follow_up_clock_at`) and, if paused, `follow_up_paused_at`;
- the send times (`send_requested_at`, `sent_at`) of the original and of each of its reminders,
  which the rate limit counts;
- the replies from the original's recipient on that file (`InboundMessage.created_at`, and the
  file's `Communication` row for each), so "a reply since the clock" keeps its order.

Nothing else: other emails to the same address keep their times, so the 5-minute and 3-a-day
limits still count them. The next reminder then goes on the job's next run (every 15 minutes).

DEVELOPMENT AND STAGING ONLY. It rewrites history on a real file; refused anywhere else, before the
database is touched. Prints each changed row, before and after, and the new `next_reminder_at`.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session_maker
from app.models.communication import Communication, CommunicationDirection
from app.models.inbound_message import InboundMessage
from app.services.follow_ups import follow_up_view

ALLOWED_ENVIRONMENTS = ("development", "staging")


class Refused(Exception):
    """The command will not move this email; the message says why."""


@dataclass
class Moved:
    what: str
    row_id: UUID
    field: str
    before: datetime
    after: datetime


@dataclass
class Report:
    moved: list[Moved] = field(default_factory=list)
    status: str = ""
    #: As the screen shows it: None unless the follow-up is `on` with reminders left.
    next_reminder_at: datetime | None = None


def _shift(report: Report, what: str, row: object, names: tuple[str, ...], by: timedelta) -> None:
    for name in names:
        before = getattr(row, name)
        if before is None:
            continue
        setattr(row, name, before - by)
        report.moved.append(Moved(what, row.id, name, before, before - by))  # type: ignore[attr-defined]


async def move_back(db: AsyncSession, communication_id: UUID, days: int) -> Report:
    """Move the conversation back; ``flush`` only, the caller commits."""
    if days < 1:
        raise Refused("--days must be 1 or more.")
    original = await db.get(Communication, communication_id)
    if original is None or original.deleted_at is not None:
        raise Refused("No such email.")
    if original.follow_up_of_id is not None:
        raise Refused(
            f"This is a reminder; pass the email it follows up ({original.follow_up_of_id})."
        )
    if (
        original.direction is not CommunicationDirection.OUTBOUND
        or original.send_requested_at is None
    ):
        raise Refused("This is not an email sent from the app, so it has no follow-up to move.")

    by = timedelta(days=days)
    report = Report()
    _shift(report, "original", original, ("follow_up_clock_at", "follow_up_paused_at"), by)
    _shift(report, "original", original, ("send_requested_at", "sent_at"), by)
    reminders = (
        await db.execute(
            select(Communication)
            .where(Communication.follow_up_of_id == original.id)
            .order_by(Communication.created_at)
        )
    ).scalars()
    for reminder in reminders:
        _shift(report, "reminder", reminder, ("send_requested_at", "sent_at"), by)

    mailbox = (original.recipient or "").strip().lower()
    if mailbox:
        replies = (
            await db.execute(
                select(InboundMessage).where(
                    InboundMessage.loan_file_id == original.loan_file_id,
                    func.lower(func.trim(InboundMessage.from_address)) == mailbox,
                )
            )
        ).scalars()
        for reply in replies:
            _shift(report, "reply", reply, ("created_at",), by)
            rows = (
                await db.execute(
                    select(Communication).where(Communication.inbound_message_id == reply.id)
                )
            ).scalars()
            for row in rows:
                _shift(report, "reply (on file)", row, ("created_at",), by)

    await db.flush()
    view = await follow_up_view(db, original)
    report.status = original.follow_up_status.value
    report.next_reminder_at = view.next_reminder_at if view else None
    return report


async def _main(args: argparse.Namespace) -> int:
    if settings.environment not in ALLOWED_ENVIRONMENTS:
        print(
            f"Refused: this rewrites an email's history and runs only in development or staging "
            f"(ENVIRONMENT is {settings.environment!r}).",
            file=sys.stderr,
        )
        return 1
    async with async_session_maker() as db:
        try:
            report = await move_back(db, UUID(args.communication_id), args.days)
        except Refused as refused:
            print(f"Refused: {refused}", file=sys.stderr)
            return 1
        await db.commit()
    for moved in report.moved:
        print(
            f"{moved.what:16} {moved.row_id} {moved.field:20} "
            f"{moved.before.isoformat()} -> {moved.after.isoformat()}"
        )
    print(
        f"moved {len(report.moved)} timestamp(s) back {args.days} day(s); "
        f"follow-up {report.status}; next_reminder_at = "
        f"{report.next_reminder_at.isoformat() if report.next_reminder_at else 'none'}"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("communication_id", help="the ORIGINAL email's id (not a reminder)")
    parser.add_argument("--days", type=int, required=True, help="how many days to move back")
    sys.exit(asyncio.run(_main(parser.parse_args())))


if __name__ == "__main__":
    main()

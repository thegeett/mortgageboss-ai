"""Apply a made-up SES delivery event to one sent email, in dev (LP-995).

Usage::

    uv run python -m app.scripts.inject_delivery_event --communication <id> \\
        --type delivery|bounce|bounce-suppressed|bounce-transient|complaint|reject

Builds the event SES would publish for that email (its `external_message_id`, its recipient) in the
shape of a configuration-set event with raw delivery, and calls `apply_delivery_event` directly, as
the queue job does. No SQS. Refuses an email with no `external_message_id`: SES never took it, so no
event could name it.

DEVELOPMENT ONLY. A made-up complaint permanently blocks a real borrower's address and writes "marked
as spam" on the file; a made-up bounce fails the email and puts its needs back to pending. Refused
in any other environment, before the database is touched.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.core.database import async_session_maker
from app.models.communication import Communication
from app.services.delivery_events import apply_delivery_event

KINDS = ("delivery", "bounce", "bounce-suppressed", "bounce-transient", "complaint", "reject")


def build_event(kind: str, *, message_id: str, recipient: str) -> dict[str, Any]:
    """An SES configuration-set event for one recipient, as AWS documents the shapes."""
    now = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    mail = {
        "timestamp": now,
        "source": "lf-dev@mb-mail.localhost",
        "sendingAccountId": "000000000000",
        "messageId": message_id,
        "destination": [recipient],
        "headersTruncated": False,
        "tags": {"ses:configuration-set": ["dev"]},
    }
    if kind == "delivery":
        return {
            "eventType": "Delivery",
            "mail": mail,
            "delivery": {
                "timestamp": now,
                "processingTimeMillis": 512,
                "recipients": [recipient],
                "smtpResponse": "250 2.6.0 Message received",
                "reportingMTA": "a8-1.smtp-out.amazonses.com",
            },
        }
    if kind in ("bounce", "bounce-suppressed", "bounce-transient"):
        bounced: dict[str, Any] = {"emailAddress": recipient, "action": "failed"}
        if kind == "bounce":
            bounce_type, sub_type = "Permanent", "General"
            bounced |= {"status": "5.1.1", "diagnosticCode": "smtp; 550 5.1.1 user unknown"}
        elif kind == "bounce-transient":
            bounce_type, sub_type = "Transient", "MailboxFull"
            bounced |= {"status": "4.2.2", "diagnosticCode": "smtp; 452 4.2.2 Mailbox full"}
        else:
            bounce_type, sub_type = "Permanent", "OnAccountSuppressionList"
            bounced["diagnosticCode"] = (
                "Amazon SES did not send the message to this address because it is on the "
                "suppression list for your account."
            )
        return {
            "eventType": "Bounce",
            "mail": mail,
            "bounce": {
                "bounceType": bounce_type,
                "bounceSubType": sub_type,
                "bouncedRecipients": [bounced],
                "timestamp": now,
                "feedbackId": "dev-feedback-id",
                "reportingMTA": "dns; amazonses.com",
            },
        }
    if kind == "complaint":
        return {
            "eventType": "Complaint",
            "mail": mail,
            "complaint": {
                "complainedRecipients": [{"emailAddress": recipient}],
                "timestamp": now,
                "feedbackId": "dev-feedback-id",
                "complaintFeedbackType": "abuse",
            },
        }
    if kind == "reject":
        return {"eventType": "Reject", "mail": mail, "reject": {"reason": "Bad content"}}
    raise ValueError(f"unknown kind {kind!r}")


async def _main(args: argparse.Namespace) -> int:
    if not settings.is_development:
        print(
            f"Refused: this injects made-up events and runs only in development "
            f"(ENVIRONMENT is {settings.environment!r}).",
            file=sys.stderr,
        )
        return 1
    async with async_session_maker() as db:
        row = await db.get(Communication, UUID(args.communication))
        if row is None:
            print("Refused: no such communication.", file=sys.stderr)
            return 1
        if not row.external_message_id:
            print("Refused: this email has no external_message_id (never sent).", file=sys.stderr)
            return 1
        event = build_event(
            args.type, message_id=row.external_message_id, recipient=row.recipient or ""
        )
        outcome = await apply_delivery_event(db, event)
        await db.commit()
        await db.refresh(row)
        print(f"{outcome}: status={row.status.value} error_detail={row.error_detail!r}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--communication", required=True, help="the communication id")
    parser.add_argument("--type", required=True, choices=KINDS)
    sys.exit(asyncio.run(_main(parser.parse_args())))


if __name__ == "__main__":
    main()

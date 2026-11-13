"""The processor's copy of an incoming email (LP-1010).

When an email is routed to a file at ingest, the last person who sent from the app on that file gets a
copy in her own inbox, unless she already has it. Decision 11-04, "Who gets the copy" and
"Attachments in the processor's copy".

- **From** `"<sender> via <company>" <file address>`, **To** her, **Reply-To** the sender and the file
  address, so a plain Reply reaches both the borrower and the file. Subject unchanged.
- **Plain text**: one line saying who replied on which file with a link, the email's own text, and how
  many attachments are on the file. **No attachments**: outbound mail carries none (LP-815), and she
  previews and accepts them in the app.
- **`X-MortgageBoss-Copy: 1`**, so a copy that comes back to a file address is never copied again, and
  the auto-reply suppression headers, so her out-of-office does not answer it: its Reply-To would
  reach the borrower.

SENT FROM THE WORKER (rule 8), after the ingest commit, so the message is safe first. No outbound
`Communication` row and no `send_draft`: one activity entry on the file records it. No retry: a copy
that fails says so on the file, and the email is on the file either way.

NOTHING HERE LOGS AN ADDRESS, A SUBJECT OR A BODY. Skips and failures log a code and ids.
"""

from __future__ import annotations

import asyncio
from email import policy
from email.message import Message
from email.parser import BytesHeaderParser
from email.utils import getaddresses
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.activity_log import ActivityType
from app.models.communication import Communication, CommunicationDirection
from app.models.communication_evidence import CommunicationEvidence, EvidenceEvent
from app.models.company import Company
from app.models.inbound_attachment import InboundAttachment
from app.models.inbound_message import InboundMessage, InboundRoutingState
from app.models.loan_file import LoanFile
from app.models.loan_team import LoanTeamMember
from app.models.user import User
from app.services.inbound_mime import decoded_header, one_line

logger = get_logger(__name__)

#: On every copy. Ingest-side, a message carrying it is never copied: a copy forwarded or bounced back
#: to a file address would otherwise copy itself to the same person forever.
COPY_MARKER_HEADER = "X-MortgageBoss-Copy"

SENT = "sent"
FAILED = "failed"


async def copy_recipient(db: AsyncSession, loan_file: LoanFile) -> User | None:
    """The approver of the most recent email a person sent with Send on this file, or None.

    Send sets `send_requested_at`; "I've sent it" does not, so a message she sent from her own mail
    app doesn't count. The approver is on the evidence record `send_draft` writes (LP-821, as the
    worker reads it in `tasks/outbound.py`). A deleted or inactive user, or one of another company,
    is passed over for the next most recent sender.

    UNDER "RESTRICT LOAN FILES TO THEIR TEAM" (LP-MB-Admin-06) a sender who is no longer on the
    file's team is passed over too: the copy is the file's mail, and they can no longer open the
    file. Nobody on the team → None, and one log line naming the file only.
    """
    stmt = (
        select(User)
        .join(CommunicationEvidence, CommunicationEvidence.approver_user_id == User.id)
        .join(Communication, Communication.id == CommunicationEvidence.communication_id)
        .where(
            Communication.loan_file_id == loan_file.id,
            Communication.direction == CommunicationDirection.OUTBOUND,
            Communication.send_requested_at.is_not(None),
            Communication.deleted_at.is_(None),
            CommunicationEvidence.event == EvidenceEvent.SENT,
            User.company_id == loan_file.company_id,
            User.is_active.is_(True),
            User.deleted_at.is_(None),
        )
        .order_by(Communication.send_requested_at.desc())
        .limit(1)
    )
    company = await db.get(Company, loan_file.company_id)
    restricted = company is not None and company.settings_model.restrict_loans_to_team
    if restricted:
        stmt = stmt.where(
            User.id.in_(
                select(LoanTeamMember.user_id).where(
                    LoanTeamMember.loan_file_id == loan_file.id,
                    LoanTeamMember.deleted_at.is_(None),
                )
            )
        )
    recipient: User | None = (await db.execute(stmt)).scalar_one_or_none()
    if recipient is None and restricted:
        logger.info("processor_copy_no_team_sender", loan_file_id=str(loan_file.id))
    return recipient


def _normalised(address: str) -> str:
    return address.strip().lower()


def _header_addresses(headers: Message, *names: str) -> set[str]:
    values: list[str] = []
    for name in names:
        values.extend(str(value) for value in headers.get_all(name, []))
    return {_normalised(address) for _, address in getaddresses(values) if address}


def _sender_name(headers: Message) -> str | None:
    """The From display name, decoded and on one line, or None."""
    names = [name for name, _ in getaddresses([str(v) for v in headers.get_all("From", [])])]
    if not names or not names[0].strip():
        return None
    return decoded_header(names[0]) or None


def copy_body(*, sender: str, display_id: str, link: str, text: str, attachment_count: int) -> str:
    """The copy's plain-text body."""
    parts = [
        f"Reply from {sender} on {display_id}. Reply normally, or open the file: {link}",
        text.strip() or "(This email has no text.)",
    ]
    if attachment_count == 1:
        parts.append(f"1 attachment is on the file: {link}")
    elif attachment_count > 1:
        parts.append(f"{attachment_count} attachments are on the file: {link}")
    return "\n\n".join(parts) + "\n"


def _skip_reason(message: InboundMessage, loan_file: LoanFile | None) -> str | None:
    """The first rule that stops a copy which the row alone can answer, or None."""
    if loan_file is None:
        return "not_routed"
    if loan_file.deleted_at is not None:
        return "file_deleted"
    if message.routing_state is InboundRoutingState.REJECTED:
        return "rejected"
    if message.routing_state is not InboundRoutingState.ROUTED:
        return "not_routed"
    if message.is_auto_reply:
        return "auto_reply"
    if message.is_dsn:
        return "delivery_notice"
    if message.is_bulk:
        return "bulk"
    if not message.from_address:
        return "no_sender_address"
    return None


async def send_processor_copy(
    db: AsyncSession, *, message_id: UUID, raw: bytes | None = None
) -> str:
    """Email the copy for this message if every rule allows it. Returns `SENT`, `FAILED`, or the skip
    reason code. ``flush`` only; the caller commits the activity entry.

    Call it once, after the FIRST insert of a message routed at ingest. It does not know whether a
    copy went out before, so a redelivery or a Move to file must not call it.

    `raw` is the message as stored, when the caller already has it (the ingest task does); otherwise
    it is read back from mail storage.
    """
    from app.services.bounce_handling import is_suppressed
    from app.services.email_send import AUTO_REPLY_SUPPRESSION_HEADERS, company_send_blocker
    from app.services.inbound_mime import body_text
    from app.services.inbound_triage import raw_message
    from app.services.mail_domain import file_address_and_sending
    from app.services.mail_sender import get_mail_sender
    from app.services.outbound_mime import build_mime
    from app.services.upload_links import LinkOriginNotConfigured, usable_link_origin

    message = await db.get(InboundMessage, message_id)
    if message is None:
        return _skipped("no_message", message_id)
    loan_file = await db.get(LoanFile, message.loan_file_id) if message.loan_file_id else None
    reason = _skip_reason(message, loan_file)
    if reason is not None or loan_file is None:
        return _skipped(reason or "not_routed", message_id)

    # THE HEADERS ARE READ INSIDE THIS `try`, with the lenient parser (compat32), which keeps a header
    # as written instead of refusing one with a line break in it (LP-1011). Anything that still fails
    # here is logged as `raw_unreadable`, never lost.
    try:
        raw = raw if raw is not None else await raw_message(message)
        headers = BytesHeaderParser(policy=policy.compat32).parsebytes(raw)
        is_our_copy = headers.get(COPY_MARKER_HEADER) is not None
        to_and_cc = _header_addresses(headers, "To", "Cc")
        display_name = _sender_name(headers)
    except Exception as exc:
        logger.warning(
            "processor_copy_raw_unreadable",
            inbound_message_id=str(message_id),
            error_type=type(exc).__name__,
        )
        return _skipped("raw_unreadable", message_id)
    if is_our_copy:
        return _skipped("our_copy", message_id)

    recipient = await copy_recipient(db, loan_file)
    if recipient is None:
        return _skipped("no_recipient", message_id)
    her_address = _normalised(recipient.email)
    if her_address == _normalised(message.from_address or ""):
        return _skipped("she_sent_it", message_id)
    # A Bcc'd processor is in no header, and NOT in `envelope_recipients` either: SES only receives for
    # the company mail domains, so her own mailbox's copy of a Bcc never passes through SES. A Bcc
    # cannot be seen, and she gets a second copy (LP-1011, Open).
    if her_address in to_and_cc:
        return _skipped("already_has_it", message_id)
    if await is_suppressed(db, company_id=loan_file.company_id, address=her_address):
        return _skipped("suppressed", message_id)

    address_and_sending = await file_address_and_sending(db, loan_file)
    blocker = await company_send_blocker(
        db, loan_file=loan_file, address_and_sending=address_and_sending
    )
    file_address = address_and_sending[0]
    sender = get_mail_sender()
    if blocker is not None or file_address is None or sender is None:
        return _skipped(blocker or "no_sender", message_id)
    try:
        origin = usable_link_origin()
    except LinkOriginNotConfigured:
        return _skipped("no_link_origin", message_id)

    company = await db.get(Company, loan_file.company_id)
    attachment_count = (
        await db.scalar(
            select(func.count(InboundAttachment.id)).where(
                InboundAttachment.inbound_message_id == message.id,
                InboundAttachment.deleted_at.is_(None),
            )
        )
    ) or 0
    sender_address = message.from_address or ""
    sender_label = display_name or sender_address
    link = f"{origin}/loan-files/{loan_file.display_id}/communication"
    detail: dict[str, Any] = {
        "kind": "processor_copy",
        "inbound_message_id": str(message.id),
        "recipient_user_id": str(recipient.id),
    }
    try:
        email = build_mime(
            # LP-1011 — THE ADDRESS, NOT THE DISPLAY NAME: a sender chooses their name, and this
            # email is signed by our domain. The body's first line keeps the name, as plain text.
            from_name=one_line(f"{sender_address} via {company.name if company else ''}"),
            from_address=file_address,
            to=recipient.email,
            reply_to=[sender_address, file_address],
            subject=decoded_header(message.subject or "") or "(no subject)",
            body=copy_body(
                sender=sender_label,
                display_id=loan_file.display_id,
                link=link,
                text=body_text(raw),
                attachment_count=attachment_count,
            ),
            html=False,
            headers={COPY_MARKER_HEADER: "1", **AUTO_REPLY_SUPPRESSION_HEADERS},
        )
        provider_message_id = await asyncio.to_thread(sender.send, email)
    except Exception as exc:  # broad: any failure is recorded on the file, never retried
        code = str(getattr(exc, "code", None) or type(exc).__name__)
        logger.warning("processor_copy_failed", inbound_message_id=str(message_id), error_code=code)
        await _record(
            db,
            loan_file=loan_file,
            activity_type=ActivityType.COMMUNICATION_FAILED,
            summary=f"Could not email a copy to {recipient.full_name}",
            detail={**detail, "error_code": code},
        )
        return FAILED

    logger.info("processor_copy_sent", inbound_message_id=str(message_id))
    await _record(
        db,
        loan_file=loan_file,
        activity_type=ActivityType.COMMUNICATION_SENT,
        summary=f"A copy was emailed to {recipient.full_name}",
        detail={**detail, "provider_message_id": provider_message_id},
    )
    return SENT


def _skipped(reason: str, message_id: UUID) -> str:
    logger.info("processor_copy_skipped", inbound_message_id=str(message_id), reason=reason)
    return reason


async def _record(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    activity_type: ActivityType,
    summary: str,
    detail: dict[str, Any],
) -> None:
    """One activity entry. COMMUNICATION_SENT / _FAILED with `kind: processor_copy`, not a new type:
    a new value needs a constraint-swap migration, and this ticket adds none. Its detail has no
    `communication_id`, so nothing that reads those types for an outbound email picks it up."""
    from app.services.activity_log import log_activity

    await log_activity(
        db,
        loan_file_id=loan_file.id,
        activity_type=activity_type,
        summary=summary,
        detail=detail,
    )
    await db.flush()


__all__ = [
    "COPY_MARKER_HEADER",
    "FAILED",
    "SENT",
    "copy_body",
    "copy_recipient",
    "send_processor_copy",
]

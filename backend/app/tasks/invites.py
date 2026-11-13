"""LP-MB-Admin-04 — the invitation email.

`send_invite_email` builds a plain-text system email from `settings.smtp_from_email` and hands it to
`get_mail_sender()` (the sender is sync, so it runs here and not in the request). With no transport it
does nothing: the admin was given the link in the API response instead.

It sends only the CURRENT token: a resend issues a new one, and an older message still queued would
otherwise go out with a link that no longer works. LOGS CARRY THE INVITE ID ONLY: never the token, the
address or the link.
"""

import asyncio
from email.message import EmailMessage
from email.utils import formataddr
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.tokens import hash_token, tokens_match
from app.models.company import Company
from app.models.user import User
from app.models.user_invite import INVITE_VALID_DAYS, UserInvite
from app.services.invites import accept_url, roles_in_words
from app.services.mail_sender import SendError, get_mail_sender
from app.services.upload_links import LinkOriginNotConfigured
from app.tasks.base import BaseTask, run_async, task_session
from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)


def build_invite_email(
    *, to: str, company_name: str, inviter_name: str, roles: list[str], token: str
) -> EmailMessage:
    """The invitation, plain text. No file address, no thread headers, no follow-up."""
    message = EmailMessage()
    message["From"] = formataddr((settings.smtp_from_name, settings.smtp_from_email))
    message["To"] = to
    message["Subject"] = f"You've been invited to {company_name} on MortgageBoss"
    message.set_content(
        f"{inviter_name} has invited you to join {company_name} on MortgageBoss "
        f"as {roles_in_words(roles)}.\n\n"
        f"Set your name and password here:\n{accept_url(token)}\n\n"
        f"This link works once and expires in {INVITE_VALID_DAYS} days.\n"
    )
    return message


async def _send(db: AsyncSession, invite_id: UUID, token: str) -> str:
    sender = get_mail_sender()
    if sender is None:
        logger.info("invite_email_skipped", invite_id=str(invite_id), reason="no_sender")
        return "skipped"
    invite = await db.get(UserInvite, invite_id)
    if (
        invite is None
        or not invite.is_open
        or not tokens_match(invite.token_hash, hash_token(token))
    ):
        # Cancelled, accepted, expired, or resent since this message was queued.
        logger.info("invite_email_skipped", invite_id=str(invite_id), reason="not_current")
        return "skipped"
    company = await db.get(Company, invite.company_id)
    inviter = await db.get(User, invite.invited_by_user_id) if invite.invited_by_user_id else None
    try:
        message = build_invite_email(
            to=invite.email,
            company_name=company.name if company else "your company",
            inviter_name=inviter.full_name if inviter else "Your administrator",
            roles=invite.roles,
            token=token,
        )
    except LinkOriginNotConfigured:
        # A misconfigured origin is a failed send, logged like one (review finding 4), not a crash.
        logger.warning(
            "invite_email_failed", invite_id=str(invite_id), error_code="link_origin_not_configured"
        )
        return "failed"
    try:
        await asyncio.to_thread(sender.send, message)
    except SendError as exc:
        # The admin sees no delivery state yet (bounces are out of scope); Resend or the link is the
        # way on. Only the code is logged: a provider message can quote the recipient.
        logger.warning("invite_email_failed", invite_id=str(invite_id), error_code=exc.code)
        return "failed"
    logger.info("invite_email_sent", invite_id=str(invite_id))
    return "sent"


async def _run(invite_id: str, token: str) -> str:
    async with task_session() as db:
        return await _send(db, UUID(invite_id), token)


@celery_app.task(base=BaseTask, name="invites.send_invite_email")  # type: ignore[untyped-decorator]
def send_invite_email(invite_id: str, token: str) -> str:
    """Email one invitation. The token is an argument, not a column: it exists nowhere else."""
    return run_async(_run(invite_id, token))

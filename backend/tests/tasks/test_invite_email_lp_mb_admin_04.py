"""The invitation email task (LP-MB-Admin-04): one message, the right To, the current link only."""

from datetime import timedelta
from email.message import EmailMessage
from uuid import uuid4

import pytest
import structlog
from app.core.tokens import generate_token, hash_token
from app.models import Company, User, UserInvite, UserRole
from app.models.base import utcnow
from app.services.mail_sender import MailSender, SendError
from app.tasks import invites as task
from sqlalchemy.ext.asyncio import AsyncSession
from tests.user_factory import make_user


class FakeSender(MailSender):
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[EmailMessage] = []
        self.fail = fail

    def send(self, message: EmailMessage) -> str:
        if self.fail:
            raise SendError("MessageRejected")
        self.sent.append(message)
        return "provider-id"


async def _open_invite(db: AsyncSession) -> tuple[UserInvite, str]:
    company = Company(name="Summit Mortgage Processing", slug=f"summit-{uuid4().hex[:6]}")
    db.add(company)
    await db.flush()
    inviter = make_user(
        company_id=company.id,
        email=f"priya-{uuid4().hex[:6]}@summit.com",
        hashed_password="x",  # pragma: allowlist secret
        first_name="Priya",
        last_name="Desai",
        roles=[UserRole.ADMIN],
    )
    db.add(inviter)
    await db.flush()
    token = generate_token()
    now = utcnow()
    invite = UserInvite(
        company_id=company.id,
        email="sam@summit.com",
        roles=["admin", "processor"],
        token_hash=hash_token(token),
        expires_at=now + timedelta(days=7),
        last_sent_at=now,
        send_count=1,
        invited_by_user_id=inviter.id,
    )
    db.add(invite)
    await db.flush()
    return invite, token


async def test_one_message_to_the_invitee_with_the_link(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    sender = FakeSender()
    monkeypatch.setattr(task, "get_mail_sender", lambda: sender)
    invite, token = await _open_invite(db_session)

    with structlog.testing.capture_logs() as logs:
        outcome = await task._send(db_session, invite.id, token)

    assert outcome == "sent"
    assert len(sender.sent) == 1
    message = sender.sent[0]
    assert message["To"] == "sam@summit.com"
    assert message["Subject"] == "You've been invited to Summit Mortgage Processing on MortgageBoss"
    body = message.get_content()
    assert f"/accept-invite#{token}" in body
    assert "Priya Desai" in body and "Admin, Processor" in body
    assert "This link works once and expires in 7 days." in body
    assert "noreply@mortgageboss.ai" in message["From"]
    assert token not in str(logs) and "sam@summit.com" not in str(logs)


async def test_nothing_is_sent_without_a_transport(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(task, "get_mail_sender", lambda: None)
    invite, token = await _open_invite(db_session)
    assert await task._send(db_session, invite.id, token) == "skipped"


@pytest.mark.parametrize("why", ["resent", "revoked", "expired"])
async def test_a_link_that_is_no_longer_current_is_not_sent(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, why: str
) -> None:
    sender = FakeSender()
    monkeypatch.setattr(task, "get_mail_sender", lambda: sender)
    invite, token = await _open_invite(db_session)
    if why == "resent":
        invite.token_hash = hash_token(generate_token())
    elif why == "revoked":
        invite.revoked_at = utcnow()
    else:
        invite.expires_at = utcnow() - timedelta(seconds=1)
    await db_session.flush()

    assert await task._send(db_session, invite.id, token) == "skipped"
    assert sender.sent == []


async def test_a_refused_send_is_logged_by_code_only(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(task, "get_mail_sender", lambda: FakeSender(fail=True))
    invite, token = await _open_invite(db_session)

    with structlog.testing.capture_logs() as logs:
        outcome = await task._send(db_session, invite.id, token)

    assert outcome == "failed"
    assert any(log.get("error_code") == "MessageRejected" for log in logs)
    assert token not in str(logs) and "sam@summit.com" not in str(logs)


def test_the_task_is_registered() -> None:
    from app.tasks.celery_app import celery_app

    assert "invites.send_invite_email" in celery_app.tasks


async def test_the_user_model_is_not_touched(db_session: AsyncSession) -> None:
    """A guard on the fixture: the invitee is not a user."""
    invite, _ = await _open_invite(db_session)
    from sqlalchemy import select

    assert await db_session.scalar(select(User.id).where(User.email == invite.email)) is None


async def test_a_misconfigured_link_origin_is_a_logged_failure_not_a_crash(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review finding 4."""
    from app.services import invites as invite_service
    from app.services.upload_links import LinkOriginNotConfigured

    def _refuse() -> str:
        raise LinkOriginNotConfigured("misconfigured")

    sender = FakeSender()
    monkeypatch.setattr(task, "get_mail_sender", lambda: sender)
    monkeypatch.setattr(invite_service, "usable_link_origin", _refuse)
    invite, token = await _open_invite(db_session)

    with structlog.testing.capture_logs() as logs:
        outcome = await task._send(db_session, invite.id, token)

    assert outcome == "failed"
    assert sender.sent == []
    assert any(log.get("error_code") == "link_origin_not_configured" for log in logs)

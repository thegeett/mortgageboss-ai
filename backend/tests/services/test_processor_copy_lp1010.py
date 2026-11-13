"""LP-1010 — the processor's copy of an incoming email."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import timedelta
from email.message import EmailMessage
from email.policy import default as email_policy
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from app.core.config import settings
from app.core.file_scope import FileScope
from app.models import Company, LoanProgram, User, UserRole
from app.models.activity_log import ActivityLog, ActivityType
from app.models.base import utcnow
from app.models.communication import (
    Communication,
    CommunicationDirection,
    CommunicationStatus,
)
from app.models.company_mail_domain import CompanyMailDomain, MailDomainStatus
from app.models.inbound_message import InboundMessage, InboundRoutingState
from app.models.loan_file import LoanFile
from app.services import mail_sender as mail_sender_module
from app.services.bounce_handling import suppress_address
from app.services.evidence import record_sent
from app.services.inbound_ingest import IngestResult, process_raw_message
from app.services.loan_files import create_loan_file
from app.services.mail_domain import set_company_mail_domain
from app.services.mail_sender import MailSender, SendError
from app.services.outbound_mime import build_mime
from app.services.processor_copy import (
    COPY_MARKER_HEADER,
    FAILED,
    SENT,
    copy_recipient,
    send_processor_copy,
)
from app.storage import get_storage_backend
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs
from tests.user_factory import make_user

_PDF = (Path(__file__).resolve().parents[1] / "fixtures" / "attachments" / "clean.pdf").read_bytes()
_ORIGIN = "https://app.example.test"


class _FakeSender(MailSender):
    def __init__(self, fail: Exception | None = None) -> None:
        self.sent: list[EmailMessage] = []
        self.fail = fail

    def send(self, message: EmailMessage) -> str:
        if self.fail is not None:
            raise self.fail
        self.sent.append(message)
        return f"provider-{len(self.sent)}"


@pytest.fixture(autouse=True)
def _settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "storage_local_path", str(tmp_path / "storage"))
    monkeypatch.setattr(settings, "upload_link_base_url", _ORIGIN)
    get_storage_backend.cache_clear()
    yield
    get_storage_backend.cache_clear()


@pytest.fixture
def sender(monkeypatch: pytest.MonkeyPatch) -> _FakeSender:
    fake = _FakeSender()
    monkeypatch.setattr(mail_sender_module, "get_mail_sender", lambda: fake)
    return fake


class _File:
    def __init__(self, company: Company, loan_file: LoanFile, domain: str, processor: User):
        self.company = company
        self.loan_file = loan_file
        self.domain = domain
        self.processor = processor

    @property
    def address(self) -> str:
        return f"{self.loan_file.display_id.lower()}@{self.domain}"


async def _user(db: AsyncSession, company: Company, first: str) -> User:
    user = make_user(
        company_id=company.id,
        email=f"{first.lower()}-{uuid4().hex[:6]}@summit.example.test",
        hashed_password="x",  # pragma: allowlist secret
        first_name=first,
        last_name="Processor",
        roles=[UserRole.PROCESSOR],
    )
    db.add(user)
    await db.flush()
    return user


async def _sent_from_app(
    db: AsyncSession,
    loan_file: LoanFile,
    approver: User,
    *,
    minutes_ago: int = 0,
    send: bool = True,
) -> Communication:
    """An email a person sent: with Send (`send_requested_at`) or "I've sent it" (`send=False`)."""
    at = utcnow() - timedelta(minutes=minutes_ago)
    row = Communication(
        loan_file_id=loan_file.id,
        direction=CommunicationDirection.OUTBOUND,
        status=CommunicationStatus.SENT,
        recipient="jane@borrower.example",
        subject="Documents",
        body="Please send.",
        sent_at=at,
        send_requested_at=at if send else None,
    )
    db.add(row)
    await db.flush()
    await record_sent(db, loan_file=loan_file, communication=row, approver_user_id=approver.id)
    return row


@pytest_asyncio.fixture
async def file(db_session: AsyncSession) -> AsyncIterator[_File]:
    company = Company(name="Summit Lending", slug=f"summit-{uuid4().hex[:8]}")
    db_session.add(company)
    await db_session.flush()
    domain = f"mb-{uuid4().hex[:8]}.example.test"
    await set_company_mail_domain(db_session, company_id=company.id, domain=domain)
    row = await db_session.scalar(
        select(CompanyMailDomain).where(CompanyMailDomain.company_id == company.id)
    )
    assert row is not None and row.status is MailDomainStatus.ACTIVE
    row.sending_enabled = True
    loan_file = await create_loan_file(
        db_session, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    processor = await _user(db_session, company, "Priya")
    await _sent_from_app(db_session, loan_file, processor)
    await db_session.flush()
    yield _File(company, loan_file, domain, processor)


def _raw(
    to: str,
    *,
    cc: str | None = None,
    sender: str = '"Jane Sample" <jane@borrower.example>',
    attachments: int = 2,
    text: str = "Here are the documents.",
    headers: dict[str, str] | None = None,
) -> bytes:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    if cc:
        message["Cc"] = cc
    message["Subject"] = "Re: Documents"
    message["Message-ID"] = f"<{uuid4().hex}@borrower.example>"
    message["Date"] = "Tue, 03 Nov 2026 10:00:00 +0000"
    for name, value in (headers or {}).items():
        message[name] = value
    message.set_content(text)
    for n in range(attachments):
        # Different bytes per attachment: identical parts are stored once.
        message.add_attachment(
            _PDF + f"%{n}\n".encode(),
            maintype="application",
            subtype="pdf",
            filename=f"statement-{n}.pdf",
        )
    return message.as_bytes(policy=email_policy)


async def _arrive(
    db: AsyncSession, raw: bytes, recipients: list[str], *, virus: str = "PASS"
) -> InboundMessage:
    result = await process_raw_message(
        db,
        raw=raw,
        raw_storage_path=None,
        store_raw=True,
        receipt={
            "recipients": recipients,
            "dmarcVerdict": {"status": "PASS"},
            "virusVerdict": {"status": virus},
        },
    )
    message = await db.get(InboundMessage, UUID(result.message_id))
    assert message is not None
    return message


async def _copy(db: AsyncSession, f: _File, raw: bytes | None = None, **kwargs: Any) -> str:
    message = await _arrive(db, raw or _raw(f.address), [f.address], **kwargs)
    return await send_processor_copy(db, message_id=message.id)


async def _activities(db: AsyncSession, f: _File) -> list[ActivityLog]:
    return list(
        (
            await db.execute(
                select(ActivityLog)
                .where(
                    ActivityLog.loan_file_id == f.loan_file.id,
                    ActivityLog.detail["kind"].as_string() == "processor_copy",
                )
                .order_by(ActivityLog.created_at)
            )
        ).scalars()
    )


# --------------------------------------------------------------------------------------------- #
# Who gets it
# --------------------------------------------------------------------------------------------- #
async def test_the_last_app_sender_gets_it_and_an_older_one_does_not(
    db_session: AsyncSession, file: _File
) -> None:
    older = await _user(db_session, file.company, "Olivia")
    await _sent_from_app(db_session, file.loan_file, older, minutes_ago=60)
    assert await copy_recipient(db_session, file.loan_file) == file.processor

    newer = await _user(db_session, file.company, "Nina")
    await _sent_from_app(db_session, file.loan_file, newer, minutes_ago=-1)
    assert await copy_recipient(db_session, file.loan_file) == newer


async def test_ive_sent_it_does_not_count(db_session: AsyncSession, file: _File) -> None:
    marker = await _user(db_session, file.company, "Mark")
    await _sent_from_app(db_session, file.loan_file, marker, minutes_ago=-1, send=False)
    assert await copy_recipient(db_session, file.loan_file) == file.processor


async def test_an_inactive_or_deleted_sender_is_passed_over(
    db_session: AsyncSession, file: _File
) -> None:
    gone = await _user(db_session, file.company, "Gina")
    await _sent_from_app(db_session, file.loan_file, gone, minutes_ago=-1)
    gone.is_active = False
    await db_session.flush()
    assert await copy_recipient(db_session, file.loan_file) == file.processor

    gone.is_active = True
    gone.deleted_at = utcnow()
    await db_session.flush()
    assert await copy_recipient(db_session, file.loan_file) == file.processor


async def test_no_app_sender_means_no_copy(db_session: AsyncSession, sender: _FakeSender) -> None:
    company = Company(name="Quiet Co", slug=f"quiet-{uuid4().hex[:8]}")
    db_session.add(company)
    await db_session.flush()
    domain = f"mb-{uuid4().hex[:8]}.example.test"
    await set_company_mail_domain(db_session, company_id=company.id, domain=domain)
    loan_file = await create_loan_file(
        db_session, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    address = f"{loan_file.display_id.lower()}@{domain}"
    message = await _arrive(db_session, _raw(address), [address])

    assert await copy_recipient(db_session, loan_file) is None
    assert await send_processor_copy(db_session, message_id=message.id) == "no_recipient"
    assert sender.sent == []


# --------------------------------------------------------------------------------------------- #
# The email
# --------------------------------------------------------------------------------------------- #
async def test_the_copy(db_session: AsyncSession, file: _File, sender: _FakeSender) -> None:
    assert await _copy(db_session, file) == SENT

    [copy] = sender.sent
    display = file.loan_file.display_id
    link = f"{_ORIGIN}/loan-files/{display}/communication"
    [sender_header] = copy["From"].addresses
    assert sender_header.display_name == "jane@borrower.example via Summit Lending"
    assert sender_header.addr_spec == file.address
    assert str(copy["To"]) == file.processor.email
    assert [a.addr_spec for a in copy["Reply-To"].addresses] == [
        "jane@borrower.example",
        file.address,
    ]
    assert str(copy["Subject"]) == "Re: Documents"
    assert copy[COPY_MARKER_HEADER] == "1"
    assert copy["Auto-Submitted"] == "auto-generated"
    assert copy["X-Auto-Response-Suppress"] == "All"
    assert copy["Precedence"] == "bulk"
    assert copy.get("Cc") is None
    assert not copy.is_multipart()
    assert list(copy.iter_attachments()) == []
    assert copy.get_content() == (
        f"Reply from Jane Sample on {display}. Reply normally, or open the file: {link}\n\n"
        "Here are the documents.\n\n"
        f"2 attachments are on the file: {link}\n"
    )


async def test_no_text_and_no_attachments(
    db_session: AsyncSession, file: _File, sender: _FakeSender
) -> None:
    raw = _raw(file.address, text="", attachments=0, sender="jane@borrower.example")
    assert await _copy(db_session, file, raw) == SENT
    body = sender.sent[0].get_content()
    assert body.startswith("Reply from jane@borrower.example on ")
    assert "(This email has no text.)" in body
    assert "attachment" not in body


async def test_success_is_recorded_on_the_file(
    db_session: AsyncSession, file: _File, sender: _FakeSender
) -> None:
    await _copy(db_session, file)
    [entry] = await _activities(db_session, file)
    assert entry.activity_type is ActivityType.COMMUNICATION_SENT
    assert entry.summary == "A copy was emailed to Priya Processor"
    assert entry.detail["provider_message_id"] == "provider-1"


async def test_lp1011_the_from_name_is_the_address_whatever_the_display_name_says(
    db_session: AsyncSession, file: _File, sender: _FakeSender
) -> None:
    raw = _raw(file.address, sender='"Summit IT Support - Password Reset" <x@evil.example>')
    assert await _copy(db_session, file, raw) == SENT
    [copy] = sender.sent
    assert copy["From"].addresses[0].display_name == "x@evil.example via Summit Lending"
    assert "Password Reset" not in str(copy["From"])
    # The body's first line keeps the name, as plain text.
    assert copy.get_content().startswith("Reply from Summit IT Support - Password Reset on ")


def _raw_with_line_breaks(to: str) -> bytes:
    """An encoded subject and display name that decode to text with a line break in it."""
    return (
        b"From: =?utf-8?q?Jane=0ASample?= <jane@borrower.example>\r\n"
        + f"To: {to}\r\n".encode()
        + b"Subject: =?utf-8?q?Statements=0D=0Aattached?=\r\n"
        + f"Message-ID: <{uuid4().hex}@borrower.example>\r\n".encode()
        + b"Content-Type: text/plain; charset=utf-8\r\n\r\nHere they are.\r\n"
    )


async def test_lp1011_line_breaks_in_the_subject_and_name_become_spaces(
    db_session: AsyncSession, file: _File, sender: _FakeSender
) -> None:
    assert await _copy(db_session, file, _raw_with_line_breaks(file.address)) == SENT
    [copy] = sender.sent
    assert str(copy["Subject"]) == "Statements attached"
    assert copy.get_content().startswith("Reply from Jane Sample on ")


async def test_lp1011_a_deleted_file_gets_no_copy(
    db_session: AsyncSession, file: _File, sender: _FakeSender
) -> None:
    message = await _arrive(db_session, _raw(file.address), [file.address])
    file.loan_file.deleted_at = utcnow()
    await db_session.flush()
    assert await send_processor_copy(db_session, message_id=message.id) == "file_deleted"
    assert sender.sent == []


# --------------------------------------------------------------------------------------------- #
# Skips
# --------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("headers", "reason"),
    [
        ({"Auto-Submitted": "auto-replied"}, "auto_reply"),
        ({"Precedence": "bulk"}, "bulk"),
        ({COPY_MARKER_HEADER: "1"}, "our_copy"),
    ],
)
async def test_machine_mail_and_our_own_copies_are_skipped(
    db_session: AsyncSession,
    file: _File,
    sender: _FakeSender,
    headers: dict[str, str],
    reason: str,
) -> None:
    assert await _copy(db_session, file, _raw(file.address, headers=headers)) == reason
    assert sender.sent == []
    assert await _activities(db_session, file) == []


async def test_a_delivery_notice_is_skipped(
    db_session: AsyncSession, file: _File, sender: _FakeSender
) -> None:
    raw = _raw(
        file.address,
        sender="MAILER-DAEMON@mx.example",
        attachments=0,
        headers={"Return-Path": "<>"},
    )
    message = await _arrive(db_session, raw, [file.address])
    assert message.is_dsn
    assert await send_processor_copy(db_session, message_id=message.id) == "delivery_notice"
    assert sender.sent == []


async def test_a_rejected_message_is_skipped(
    db_session: AsyncSession, file: _File, sender: _FakeSender
) -> None:
    message = await _arrive(db_session, _raw(file.address), [file.address], virus="FAIL")
    assert message.routing_state is InboundRoutingState.REJECTED
    assert await send_processor_copy(db_session, message_id=message.id) == "rejected"
    assert sender.sent == []


async def test_she_is_the_sender(
    db_session: AsyncSession, file: _File, sender: _FakeSender
) -> None:
    raw = _raw(file.address, sender=file.processor.email.upper())
    assert await _copy(db_session, file, raw) == "she_sent_it"
    assert sender.sent == []


async def test_she_is_in_to(db_session: AsyncSession, file: _File, sender: _FakeSender) -> None:
    raw = _raw(f"{file.address}, {file.processor.email}")
    assert await _copy(db_session, file, raw) == "already_has_it"
    assert sender.sent == []


async def test_she_is_in_cc(db_session: AsyncSession, file: _File, sender: _FakeSender) -> None:
    raw = _raw(file.address, cc=f"  {file.processor.email.upper()} ")
    assert await _copy(db_session, file, raw) == "already_has_it"
    assert sender.sent == []


async def test_she_is_suppressed(
    db_session: AsyncSession, file: _File, sender: _FakeSender
) -> None:
    from app.models.suppressed_address import SuppressionReason

    await suppress_address(
        db_session,
        company_id=file.company.id,
        address=file.processor.email,
        reason=SuppressionReason.HARD_BOUNCE,
    )
    assert await _copy(db_session, file) == "suppressed"
    assert sender.sent == []


async def test_domain_problem(db_session: AsyncSession, file: _File, sender: _FakeSender) -> None:
    row = await db_session.scalar(
        select(CompanyMailDomain).where(CompanyMailDomain.company_id == file.company.id)
    )
    assert row is not None
    row.status = MailDomainStatus.PROBLEM
    await db_session.flush()
    assert await _copy(db_session, file) == "domain_problem"
    assert sender.sent == []


async def test_sending_off(db_session: AsyncSession, file: _File, sender: _FakeSender) -> None:
    row = await db_session.scalar(
        select(CompanyMailDomain).where(CompanyMailDomain.company_id == file.company.id)
    )
    assert row is not None
    row.sending_enabled = False
    await db_session.flush()
    assert await _copy(db_session, file) == "sending_off"
    assert sender.sent == []


async def test_no_mail_sender(
    db_session: AsyncSession, file: _File, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mail_sender_module, "get_mail_sender", lambda: None)
    assert await _copy(db_session, file) == "no_sender"
    assert await _activities(db_session, file) == []


# --------------------------------------------------------------------------------------------- #
# Failure
# --------------------------------------------------------------------------------------------- #
async def test_a_send_failure_is_recorded_and_the_message_stays(
    db_session: AsyncSession,
    file: _File,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failing = _FakeSender(fail=SendError("MessageRejected"))
    monkeypatch.setattr(mail_sender_module, "get_mail_sender", lambda: failing)
    message = await _arrive(db_session, _raw(file.address), [file.address])

    with capture_logs() as logs:
        assert await send_processor_copy(db_session, message_id=message.id) == FAILED
    [entry] = await _activities(db_session, file)
    assert entry.activity_type is ActivityType.COMMUNICATION_FAILED
    assert entry.summary == "Could not email a copy to Priya Processor"
    assert entry.detail["error_code"] == "MessageRejected"
    await db_session.refresh(message)
    assert message.loan_file_id == file.loan_file.id
    assert message.routing_state is InboundRoutingState.ROUTED

    _assert_codes_only(logs, file, "processor_copy_failed")


async def test_nothing_is_logged_beyond_codes_on_success(
    db_session: AsyncSession, file: _File, sender: _FakeSender
) -> None:
    with capture_logs() as logs:
        await _copy(db_session, file)
    _assert_codes_only(logs, file, "processor_copy_sent")


def _assert_codes_only(logs: list[dict[str, Any]], f: _File, event: str) -> None:
    """The expected line is there (so the capture worked), and no line carries a person's words."""
    assert event in [entry["event"] for entry in logs]
    text = repr(logs)
    for secret in (f.processor.email, "jane@borrower.example", "Re: Documents", "Here are"):
        assert secret not in text


# --------------------------------------------------------------------------------------------- #
# Only on the first insert at ingest
# --------------------------------------------------------------------------------------------- #
class _Session:
    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def commit(self) -> None:
        return None


@pytest.mark.parametrize(("created", "copies"), [(True, 1), (False, 0)])
def test_ingest_copies_on_the_first_insert_only(
    monkeypatch: pytest.MonkeyPatch, created: bool, copies: int
) -> None:
    from app.services import inbound_ingest
    from app.storage.s3 import S3StorageBackend
    from app.tasks import inbound
    from app.tasks.base import run_async

    calls: list[tuple[str, bytes | None]] = []

    async def fake_read(_self: S3StorageBackend, _key: str) -> bytes:
        return b"raw"

    async def fake_process(_db: Any, **_: Any) -> IngestResult:
        return IngestResult(message_id=str(uuid4()), created=created, ingest_key="k")

    async def fake_copy(message_id: str, *, raw: bytes | None = None) -> None:
        calls.append((message_id, raw))

    monkeypatch.setattr(S3StorageBackend, "read", fake_read)
    monkeypatch.setattr(inbound_ingest, "process_raw_message", fake_process)
    monkeypatch.setattr(inbound, "task_session", _Session)
    monkeypatch.setattr(inbound, "_copy_to_processor", fake_copy)

    run_async(inbound._ingest_message(bucket="b", key="inbound/x", receipt=None))
    assert len(calls) == copies
    if copies:
        assert calls[0][1] == b"raw"


def test_a_failing_copy_never_fails_the_ingest(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import processor_copy
    from app.tasks import inbound
    from app.tasks.base import run_async

    async def boom(*_: Any, **__: Any) -> str:
        raise RuntimeError("down")

    monkeypatch.setattr(inbound, "task_session", _Session)
    monkeypatch.setattr(processor_copy, "send_processor_copy", boom)
    run_async(inbound._copy_to_processor(str(uuid4())))


def test_running_out_of_time_during_the_copy_still_stops_the_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import processor_copy
    from app.tasks import inbound
    from app.tasks.base import run_async
    from celery.exceptions import SoftTimeLimitExceeded

    async def out_of_time(*_: Any, **__: Any) -> str:
        raise SoftTimeLimitExceeded

    monkeypatch.setattr(inbound, "task_session", _Session)
    monkeypatch.setattr(processor_copy, "send_processor_copy", out_of_time)
    with pytest.raises(SoftTimeLimitExceeded):
        run_async(inbound._copy_to_processor(str(uuid4())))


async def test_move_to_file_sends_no_copy(
    db_session: AsyncSession, file: _File, sender: _FakeSender
) -> None:
    from app.services.inbound_triage import move_unrouted_message

    typo = f"lf-typo@{file.domain}"
    message = await _arrive(db_session, _raw(typo), [typo])
    assert message.routing_state is InboundRoutingState.UNROUTED
    # Positive control: the same message, sent through the copy now, would be refused as unrouted.
    assert await send_processor_copy(db_session, message_id=message.id) == "not_routed"

    moved = await move_unrouted_message(
        db_session,
        scope=FileScope.system(file.company.id),
        message_id=message.id,
        file_identifier=file.loan_file.display_id,
        actor_user_id=file.processor.id,
    )
    assert moved is not None and moved.loan_file_id == file.loan_file.id
    assert sender.sent == []
    assert await _activities(db_session, file) == []


# --------------------------------------------------------------------------------------------- #
# build_mime: several Reply-To addresses
# --------------------------------------------------------------------------------------------- #
def _mime(reply_to: Any) -> EmailMessage:
    return build_mime(
        from_name="A",
        from_address="lf-a@mb.example.test",
        to="p@example.test",
        reply_to=reply_to,
        subject="s",
        body="b",
        html=False,
    )


def test_reply_to_takes_a_list() -> None:
    message = _mime(["jane@borrower.example", "lf-a@mb.example.test"])
    assert [a.addr_spec for a in message["Reply-To"].addresses] == [
        "jane@borrower.example",
        "lf-a@mb.example.test",
    ]
    assert [a.addr_spec for a in _mime("lf-a@mb.example.test")["Reply-To"].addresses] == [
        "lf-a@mb.example.test"
    ]
    assert _mime(None).get("Reply-To") is None


@pytest.mark.parametrize(
    "bad",
    [
        "a@x.example, b@y.example",
        "Jane <jane@borrower.example>",
        "not-an-address",
        "jane@borrower.example\r\nBcc: x@evil.example",
    ],
)
def test_reply_to_refuses_a_bad_item(bad: str) -> None:
    with pytest.raises(ValueError):
        _mime(["lf-a@mb.example.test", bad])

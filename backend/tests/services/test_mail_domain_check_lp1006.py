"""LP-1006 — the hourly check of customer mail domains.

- `delegation_state` and `dkim_state`: a clear answer vs a hiccup.
- `check_mail_domain`: every transition; a hiccup moves nothing; hand-linked rows are never touched.
- The lock, on two real connections: the check and the command skip a row someone else holds.
- A `problem` domain: the file keeps its address, Send is refused on the screen, in the API, and by the
  worker.
- The job: only rows with a zone, one summary line, the fake refused outside development.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import dns.exception
import dns.resolver
import pytest
import pytest_asyncio
from app.core.config import settings
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.main import app
from app.models.communication import CommunicationStatus
from app.models.company import Company
from app.models.company_mail_domain import CompanyMailDomain, MailDomainStatus
from app.scripts import set_up_mail_domain as command
from app.services.domain_provider import (
    DomainSetupError,
    FakeDomainProvider,
    Route53DomainProvider,
)
from app.services.email_send import CannotSendError, send_draft
from app.services.mail_domain import (
    MAIL_DOMAIN_PAUSED,
    MailDomainError,
    check_mail_domain,
    file_address,
    lock_mail_domain,
    set_email_sending,
)
from app.services.message_detail import message_detail
from app.tasks import mail_domains as job
from app.tasks import outbound
from app.tasks.celery_app import celery_app
from botocore.stub import Stubber
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from structlog.testing import capture_logs
from tests.mail_address import link_mail_domain
from tests.outbound_send import FakeSender, FakeStorage, Ready, ready_to_send

SUB = "mb-mail.abcmortgage.test"
NS = ["ns-1.awsdns-01.org", "ns-2.awsdns-02.co.uk", "ns-3.awsdns-03.com", "ns-4.awsdns-04.net"]
TO = "borrower@example.test"


@pytest.fixture(autouse=True)
def _aws(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setattr(settings, "s3_region", "us-east-1")


@pytest_asyncio.fixture
async def db(test_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """`check_mail_domain` commits and rolls back, as `task_session` does: savepoints keep it in."""
    connection = await test_engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(
        bind=connection,
        expire_on_commit=False,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


# --------------------------------------------------------------------------------------------- #
# The provider: a clear answer vs a hiccup
# --------------------------------------------------------------------------------------------- #
class _Target:
    def __init__(self, name: str) -> None:
        self.target = name


class _Resolver:
    def __init__(self, answer: list[str] | Exception) -> None:
        self.answer = answer

    def resolve(self, name: str, kind: str) -> list[_Target]:
        assert kind == "NS"
        if isinstance(self.answer, Exception):
            raise self.answer
        return [_Target(item) for item in self.answer]


def _provider(answer: list[str] | Exception = NS) -> Route53DomainProvider:
    return Route53DomainProvider(resolver=_Resolver(answer))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("answer", "state"),
    [
        ([f"{name.upper()}." for name in reversed(NS)], "ok"),
        (["ns-1.other.example", "ns-2.other.example"], "wrong"),
        (NS[:3], "wrong"),
        ([*NS, "ns-5.other.example"], "wrong"),
        (dns.resolver.NXDOMAIN(), "wrong"),
        (dns.resolver.NoAnswer(), "wrong"),
        (dns.exception.Timeout(), "unknown"),
        (dns.resolver.NoNameservers(), "unknown"),  # how dnspython reports SERVFAIL
        (dns.exception.DNSException(), "unknown"),
    ],
)
def test_delegation_state(answer: list[str] | Exception, state: str) -> None:
    provider = _provider(answer)
    assert provider.delegation_state(SUB, NS) == state
    assert provider.is_delegated(SUB, NS) is (state == "ok")


@pytest.mark.parametrize(
    ("dkim", "verified", "state"),
    [
        ("SUCCESS", True, "ok"),
        ("SUCCESS", False, "unknown"),
        ("FAILED", False, "failed"),
        ("PENDING", False, "unknown"),
        ("TEMPORARY_FAILURE", False, "unknown"),
        ("NOT_STARTED", False, "unknown"),
    ],
)
def test_dkim_state(dkim: str, verified: bool, state: str) -> None:
    provider = _provider()
    with Stubber(provider._sesv2) as stub:
        stub.add_response(
            "get_email_identity",
            {"DkimAttributes": {"Status": dkim}, "VerifiedForSendingStatus": verified},
            expected_params={"EmailIdentity": SUB},
        )
        assert provider.dkim_state(SUB) == state


@pytest.mark.parametrize("code", ["TooManyRequestsException", "AccessDeniedException"])
def test_an_aws_error_is_unknown(code: str) -> None:
    provider = _provider()
    with Stubber(provider._sesv2) as stub:
        stub.add_client_error("get_email_identity", service_error_code=code)
        assert provider.dkim_state(SUB) == "unknown"


def test_the_fake_says_ok() -> None:
    fake = FakeDomainProvider()
    assert (fake.delegation_state(SUB, NS), fake.dkim_state(SUB)) == ("ok", "ok")


# --------------------------------------------------------------------------------------------- #
# check_mail_domain
# --------------------------------------------------------------------------------------------- #
class Steered(FakeDomainProvider):
    """The fake, with each answer set by the test, and every call recorded."""

    def __init__(self, delegation: str = "ok", dkim: str = "ok") -> None:
        self.delegation = delegation
        self.dkim = dkim
        self.delegated = True
        self.verified = True
        self.setup_error: Exception | None = None
        self.calls: list[str] = []

    def delegation_state(self, subdomain: str, nameservers: list[str]) -> Any:
        self.calls.append(f"delegation_state {subdomain}")
        if self.setup_error is not None and not isinstance(self.setup_error, DomainSetupError):
            raise self.setup_error
        return self.delegation

    def dkim_state(self, subdomain: str) -> Any:
        self.calls.append(f"dkim_state {subdomain}")
        return self.dkim

    def is_delegated(self, subdomain: str, nameservers: list[str]) -> bool:
        self.calls.append(f"is_delegated {subdomain}")
        return self.delegated

    def is_verified(self, subdomain: str) -> bool:
        self.calls.append(f"is_verified {subdomain}")
        if isinstance(self.setup_error, DomainSetupError):
            raise self.setup_error
        return self.verified

    def set_up_identity_and_records(self, subdomain: str, zone_id: str) -> None:
        self.calls.append(f"set_up {subdomain}")
        if isinstance(self.setup_error, DomainSetupError):
            raise self.setup_error


async def _row(
    db: AsyncSession, status: MailDomainStatus, *, sending: bool = False
) -> tuple[Ready, CompanyMailDomain]:
    """A domain set up by the command: it has a zone."""
    ready = await ready_to_send(db, with_domain=False)
    row = CompanyMailDomain(
        company_id=ready.company.id,
        domain=f"mb-mail.c{uuid4().hex[:8]}.example.test",
        status=status,
        zone_id="ZTEST",
        nameservers=NS,
        sending_enabled=sending,
    )
    db.add(row)
    # Committed, as a real row is: `check_mail_domain` rolls back on an AWS error.
    await db.commit()
    return ready, row


async def _status(db: AsyncSession, row: CompanyMailDomain) -> MailDomainStatus:
    await db.refresh(row)
    return row.status


async def test_pending_ns_advances(db: AsyncSession) -> None:
    _, row = await _row(db, MailDomainStatus.PENDING_NS)
    provider = Steered()
    assert await check_mail_domain(db, row, provider) == "verifying"
    assert await _status(db, row) is MailDomainStatus.VERIFYING
    assert provider.calls == [f"is_delegated {row.domain}", f"set_up {row.domain}"]


async def test_pending_ns_waits_for_the_ns_record(db: AsyncSession) -> None:
    _, row = await _row(db, MailDomainStatus.PENDING_NS)
    provider = Steered()
    provider.delegated = False
    assert await check_mail_domain(db, row, provider) == "pending_ns"
    assert await _status(db, row) is MailDomainStatus.PENDING_NS


async def test_verifying_advances_and_switches_sending_on(db: AsyncSession) -> None:
    _, row = await _row(db, MailDomainStatus.VERIFYING)
    assert await check_mail_domain(db, row, Steered()) == "active"
    assert await _status(db, row) is MailDomainStatus.ACTIVE
    assert row.sending_enabled is True


@pytest.mark.parametrize(
    ("delegation", "dkim", "outcome", "status"),
    [
        ("ok", "ok", "unchanged", MailDomainStatus.ACTIVE),
        ("wrong", "ok", "problem", MailDomainStatus.PROBLEM),
        ("ok", "failed", "problem", MailDomainStatus.PROBLEM),
        ("wrong", "failed", "problem", MailDomainStatus.PROBLEM),
        ("wrong", "unknown", "problem", MailDomainStatus.PROBLEM),
        ("unknown", "failed", "problem", MailDomainStatus.PROBLEM),
        ("unknown", "ok", "unchanged", MailDomainStatus.ACTIVE),
        ("ok", "unknown", "unchanged", MailDomainStatus.ACTIVE),
        ("unknown", "unknown", "unchanged", MailDomainStatus.ACTIVE),
    ],
)
async def test_active(
    db: AsyncSession, delegation: str, dkim: str, outcome: str, status: MailDomainStatus
) -> None:
    _, row = await _row(db, MailDomainStatus.ACTIVE, sending=True)
    assert await check_mail_domain(db, row, Steered(delegation, dkim)) == outcome
    assert await _status(db, row) is status
    assert row.sending_enabled is True


@pytest.mark.parametrize(
    ("delegation", "dkim", "outcome", "status"),
    [
        ("ok", "ok", "active", MailDomainStatus.ACTIVE),
        ("wrong", "ok", "unchanged", MailDomainStatus.PROBLEM),
        ("ok", "failed", "unchanged", MailDomainStatus.PROBLEM),
        ("unknown", "ok", "unchanged", MailDomainStatus.PROBLEM),
        ("ok", "unknown", "unchanged", MailDomainStatus.PROBLEM),
    ],
)
async def test_problem(
    db: AsyncSession, delegation: str, dkim: str, outcome: str, status: MailDomainStatus
) -> None:
    _, row = await _row(db, MailDomainStatus.PROBLEM)
    assert await check_mail_domain(db, row, Steered(delegation, dkim)) == outcome
    assert await _status(db, row) is status


@pytest.mark.parametrize("sending", [True, False])
async def test_recovery_leaves_the_sending_switch_as_it_was(
    db: AsyncSession, sending: bool
) -> None:
    """Someone may have switched it off on purpose during the problem."""
    _, row = await _row(db, MailDomainStatus.PROBLEM, sending=sending)
    assert await check_mail_domain(db, row, Steered()) == "active"
    await db.refresh(row)
    assert row.sending_enabled is sending


@pytest.mark.parametrize("status", list(MailDomainStatus))
async def test_a_hand_linked_row_is_skipped_in_every_state(
    db: AsyncSession, status: MailDomainStatus
) -> None:
    ready = await ready_to_send(db, with_domain=False)
    await link_mail_domain(db, ready.company.id)
    row = await db.scalar(
        select(CompanyMailDomain).where(CompanyMailDomain.company_id == ready.company.id)
    )
    assert row is not None and row.zone_id is None
    row.status = status
    await db.flush()
    provider = Steered("wrong", "failed")
    assert await check_mail_domain(db, row, provider) == "skipped"
    assert await _status(db, row) is status
    assert provider.calls == []


async def test_inactive_is_skipped(db: AsyncSession) -> None:
    _, row = await _row(db, MailDomainStatus.INACTIVE)
    provider = Steered("ok", "ok")
    assert await check_mail_domain(db, row, provider) == "skipped"
    assert await _status(db, row) is MailDomainStatus.INACTIVE
    assert provider.calls == []


@pytest.mark.parametrize("status", [MailDomainStatus.PENDING_NS, MailDomainStatus.VERIFYING])
async def test_a_setup_error_changes_nothing(db: AsyncSession, status: MailDomainStatus) -> None:
    _, row = await _row(db, status)
    domain = row.domain
    provider = Steered()
    provider.setup_error = DomainSetupError("Throttling", domain, retryable=True)
    with capture_logs() as logs:
        assert await check_mail_domain(db, row, provider) == "error"
    assert await _status(db, row) is status
    assert row.sending_enabled is False
    assert [log for log in logs if log["event"] == "mail_domain_check_failed"] == [
        {
            "event": "mail_domain_check_failed",
            "domain": domain,
            "error_code": "Throttling",
            "log_level": "warning",
        }
    ]


# --------------------------------------------------------------------------------------------- #
# The lock, on two real connections. These commit, so they clean up after themselves.
# --------------------------------------------------------------------------------------------- #
@pytest_asyncio.fixture
async def committed_row(test_engine: AsyncEngine) -> AsyncIterator[tuple[Company, Any]]:
    async with AsyncSession(test_engine, expire_on_commit=False) as session:
        company = Company(name=f"Lock Co {uuid4().hex[:8]}", slug=f"lock-{uuid4().hex[:8]}")
        session.add(company)
        await session.flush()
        row = CompanyMailDomain(
            company_id=company.id,
            domain=f"mb-mail.lock-{uuid4().hex[:8]}.example.test",
            status=MailDomainStatus.ACTIVE,
            zone_id="ZLOCK",
            nameservers=NS,
        )
        session.add(row)
        await session.commit()
        try:
            yield company, row.id
        finally:
            await session.rollback()
            await session.delete(row)
            await session.flush()
            await session.delete(company)
            await session.commit()


async def test_the_check_skips_a_row_someone_else_holds(
    test_engine: AsyncEngine, committed_row: tuple[Company, Any]
) -> None:
    _, row_id = committed_row
    async with (
        AsyncSession(test_engine, expire_on_commit=False) as holder,
        AsyncSession(test_engine, expire_on_commit=False) as checker,
    ):
        assert await lock_mail_domain(holder, row_id) is not None
        row = await checker.get(CompanyMailDomain, row_id)
        assert row is not None
        provider = Steered("wrong", "ok")
        assert await check_mail_domain(checker, row, provider) == "locked"
        assert provider.calls == []

        # The control: once it is released, the same check does its work.
        await holder.commit()
        assert await check_mail_domain(checker, row, provider) == "problem"
        await checker.refresh(row)
        assert row.status is MailDomainStatus.PROBLEM
        row.status = MailDomainStatus.ACTIVE
        await checker.commit()


async def test_the_command_stops_on_a_row_someone_else_holds(
    test_engine: AsyncEngine, committed_row: tuple[Company, Any]
) -> None:
    company, row_id = committed_row
    async with (
        AsyncSession(test_engine, expire_on_commit=False) as holder,
        AsyncSession(test_engine, expire_on_commit=False) as session,
    ):
        row = await lock_mail_domain(holder, row_id)
        assert row is not None
        domain = row.domain
        with pytest.raises(MailDomainError, match="hourly check is working on"):
            await command.run(
                session, company_ref=str(company.id), subdomain=domain, provider=Steered()
            )
        await session.rollback()

        # The control: once it is released, the command goes on.
        await holder.commit()
        _, found, _, _ = await command.run(
            session, company_ref=str(company.id), subdomain=domain, provider=Steered()
        )
        assert found.status is MailDomainStatus.ACTIVE


async def _make_pending(session: AsyncSession, row_id: Any) -> CompanyMailDomain:
    row = await session.get(CompanyMailDomain, row_id)
    assert row is not None
    row.status = MailDomainStatus.PENDING_NS
    await session.commit()
    return row


async def test_replace_stops_on_a_row_someone_else_holds(
    test_engine: AsyncEngine, committed_row: tuple[Company, Any]
) -> None:
    company, row_id = committed_row
    async with (
        AsyncSession(test_engine, expire_on_commit=False) as holder,
        AsyncSession(test_engine, expire_on_commit=False) as session,
    ):
        row = await _make_pending(holder, row_id)
        domain = row.domain
        assert await lock_mail_domain(holder, row_id) is not None
        # So a command that writes without asking for the lock fails here, instead of waiting forever
        # on a holder this same test would release only afterwards.
        await session.execute(text("SET LOCAL lock_timeout = '2s'"))
        with pytest.raises(MailDomainError, match="hourly check is working on"):
            await command.run(
                session,
                company_ref=str(company.id),
                subdomain=SUB,
                provider=Steered(),
                replace=True,
            )
        await session.rollback()
        await holder.rollback()
        await holder.refresh(row)
        assert (row.domain, row.status, row.zone_id) == (
            domain,
            MailDomainStatus.PENDING_NS,
            "ZLOCK",
        )


async def test_replace_sees_that_the_job_moved_the_row_on(
    test_engine: AsyncEngine,
    committed_row: tuple[Company, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The review's race: the command reads `pending_ns`, the job moves it to `verifying`, then the
    command replaces. Without a fresh read, that left `verifying` with no zone, which nothing can
    pick up: the job skips it and both commands refuse it."""
    company, row_id = committed_row
    async with (
        AsyncSession(test_engine, expire_on_commit=False) as job_session,
        AsyncSession(test_engine, expire_on_commit=False) as session,
    ):
        row = await _make_pending(job_session, row_id)
        domain = row.domain
        real_lock = command.lock_mail_domain

        async def job_runs_first(db: AsyncSession, locked_id: Any) -> Any:
            fresh = await job_session.get(CompanyMailDomain, locked_id, populate_existing=True)
            assert fresh is not None
            assert await check_mail_domain(job_session, fresh, Steered()) == "verifying"
            return await real_lock(db, locked_id)

        monkeypatch.setattr(command, "lock_mail_domain", job_runs_first)
        with pytest.raises(MailDomainError, match="past pending_ns is manual"):
            await command.run(
                session,
                company_ref=str(company.id),
                subdomain=SUB,
                provider=Steered(),
                replace=True,
            )
        await session.rollback()
        await job_session.refresh(row)
        assert (row.domain, row.status, row.zone_id) == (
            domain,
            MailDomainStatus.VERIFYING,
            "ZLOCK",
        )


# --------------------------------------------------------------------------------------------- #
# The emergency off, during a problem
# --------------------------------------------------------------------------------------------- #
async def test_switched_off_during_a_problem_it_stays_off_after_recovery(db: AsyncSession) -> None:
    ready, row = await _row(db, MailDomainStatus.PROBLEM, sending=True)
    await set_email_sending(db, company_id=ready.company.id, enabled=False)
    await db.commit()
    assert await check_mail_domain(db, row, Steered()) == "active"
    await db.refresh(row)
    assert (row.status, row.sending_enabled) == (MailDomainStatus.ACTIVE, False)


async def test_a_problem_domain_cannot_be_switched_on(db: AsyncSession) -> None:
    ready, row = await _row(db, MailDomainStatus.PROBLEM)
    with pytest.raises(MailDomainError) as refused:
        await set_email_sending(db, company_id=ready.company.id, enabled=True)
    assert str(refused.value) == MAIL_DOMAIN_PAUSED
    assert row.sending_enabled is False


@pytest.mark.parametrize(
    "status", [MailDomainStatus.PENDING_NS, MailDomainStatus.VERIFYING, MailDomainStatus.INACTIVE]
)
@pytest.mark.parametrize("enabled", [True, False])
async def test_other_states_are_still_refused(
    db: AsyncSession, status: MailDomainStatus, enabled: bool
) -> None:
    ready, _ = await _row(db, status)
    with pytest.raises(MailDomainError, match="no active mail domain"):
        await set_email_sending(db, company_id=ready.company.id, enabled=enabled)


# --------------------------------------------------------------------------------------------- #
# A problem domain: keeps its addresses, doesn't send
# --------------------------------------------------------------------------------------------- #
@pytest.fixture
def can_send(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mail_transport", "smtp")


async def _paused(db: AsyncSession) -> tuple[Ready, CompanyMailDomain]:
    ready = await ready_to_send(db)
    row = await db.scalar(
        select(CompanyMailDomain).where(CompanyMailDomain.company_id == ready.company.id)
    )
    assert row is not None and row.sending_enabled is True
    return ready, row


async def _detail_can_send(db: AsyncSession, ready: Ready) -> bool:
    detail = await message_detail(
        db, loan_file=ready.loan_file, communication_id=ready.draft.id, reader=ready.user
    )
    assert detail is not None
    return detail.can_send


@pytest.mark.usefixtures("can_send")
async def test_a_problem_domain_keeps_its_address_and_send_is_hidden_and_refused(
    db: AsyncSession,
) -> None:
    ready, row = await _paused(db)
    address = f"{ready.loan_file.display_id.lower()}@{row.domain}"
    # The control: all of this works while the domain is active.
    assert await file_address(db, ready.loan_file) == address
    assert await _detail_can_send(db, ready) is True

    row.status = MailDomainStatus.PROBLEM
    await db.flush()

    assert await file_address(db, ready.loan_file) == address
    assert await _detail_can_send(db, ready) is False
    with pytest.raises(CannotSendError) as refused:
        await send_draft(
            db,
            loan_file=ready.loan_file,
            draft_id=ready.draft.id,
            recipient=TO,
            body="Please send your bank statements.",
            approver_user_id=ready.user.id,
            transmit=True,
        )
    assert str(refused.value) == MAIL_DOMAIN_PAUSED
    assert MAIL_DOMAIN_PAUSED == (
        "Email for this company is paused: its DNS setup changed. Contact support."
    )


@pytest.mark.usefixtures("can_send")
async def test_the_send_endpoint_refuses_with_the_reason(db: AsyncSession) -> None:
    ready, row = await _paused(db)
    row.status = MailDomainStatus.PROBLEM
    await db.commit()

    async def _get_db() -> AsyncIterator[AsyncSession]:
        yield db

    app.dependency_overrides[get_db] = _get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/loan-files/{ready.loan_file.display_id}"
                f"/outbound/draft/{ready.draft.id}/send",
                headers={"Authorization": f"Bearer {create_access_token(ready.user.id)}"},
                json={"recipient": TO, "body": "Please send.", "transmit": True},
            )
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert response.status_code == 409
    assert MAIL_DOMAIN_PAUSED in response.text, response.text


@pytest.mark.usefixtures("can_send")
async def test_an_email_queued_before_the_problem_is_not_sent(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The address alone no longer says it may send, so the worker has to ask."""
    sender = FakeSender()
    storage = FakeStorage()
    monkeypatch.setattr(outbound, "get_mail_sender", lambda: sender)
    monkeypatch.setattr(outbound, "get_mail_storage", lambda: storage)
    ready, row = await _paused(db)
    await send_draft(
        db,
        loan_file=ready.loan_file,
        draft_id=ready.draft.id,
        recipient=TO,
        body="Please send your bank statements.",
        approver_user_id=ready.user.id,
        transmit=True,
    )
    await db.commit()
    assert ready.draft.status is CommunicationStatus.QUEUED

    row.status = MailDomainStatus.PROBLEM
    await db.commit()
    assert await outbound._send_communication(db, str(ready.draft.id)) == "failed"
    assert sender.sent == [] and storage.saved == {}
    await db.refresh(ready.draft)
    assert ready.draft.status is CommunicationStatus.FAILED
    assert ready.draft.error_detail == f"Not sent: {MAIL_DOMAIN_PAUSED}"


# --------------------------------------------------------------------------------------------- #
# The job
# --------------------------------------------------------------------------------------------- #
async def test_the_job_checks_only_rows_with_a_zone_and_logs_one_summary(db: AsyncSession) -> None:
    _, pending = await _row(db, MailDomainStatus.PENDING_NS)
    _, active = await _row(db, MailDomainStatus.ACTIVE, sending=True)
    _, broken = await _row(db, MailDomainStatus.ACTIVE, sending=True)
    _, inactive = await _row(db, MailDomainStatus.INACTIVE)
    hand = await ready_to_send(db)
    hand_row = await db.scalar(
        select(CompanyMailDomain).where(CompanyMailDomain.company_id == hand.company.id)
    )
    assert hand_row is not None
    await db.commit()

    class OneBroken(Steered):
        def delegation_state(self, subdomain: str, nameservers: list[str]) -> Any:
            super().delegation_state(subdomain, nameservers)
            return "wrong" if subdomain == broken.domain else "ok"

    provider = OneBroken()
    provider.delegated = False
    with capture_logs() as logs:
        assert await job._check_all(db, provider) == {
            "pending_ns": 1,
            "unchanged": 1,
            "problem": 1,
        }
    called = " ".join(provider.calls)
    assert pending.domain in called and active.domain in called and broken.domain in called
    assert inactive.domain not in called and hand_row.domain not in called

    summaries = [log for log in logs if log["event"] == "mail_domains_checked"]
    assert summaries == [
        {
            "event": "mail_domains_checked",
            "total": 3,
            "pending_ns": 1,
            "unchanged": 1,
            "problem": 1,
            "log_level": "info",
        }
    ]
    assert await _status(db, broken) is MailDomainStatus.PROBLEM


async def test_one_domain_crashing_does_not_stop_the_others(db: AsyncSession) -> None:
    _, first = await _row(db, MailDomainStatus.ACTIVE)
    await _row(db, MailDomainStatus.ACTIVE)
    crashes_on = first.domain

    class CrashesOnFirst(Steered):
        def delegation_state(self, subdomain: str, nameservers: list[str]) -> Any:
            if subdomain == crashes_on:
                raise RuntimeError("boom")
            return super().delegation_state(subdomain, nameservers)

    assert await job._check_all(db, CrashesOnFirst()) == {"error": 1, "unchanged": 1}


def test_the_job_is_scheduled_hourly_and_registered() -> None:
    entry = celery_app.conf.beat_schedule["check-mail-domains"]
    assert entry["task"] == "mail_domains.check_all" == job.check_all.name
    assert entry["task"] in celery_app.tasks
    assert entry["schedule"] == 3600.0
    assert entry["options"]["expires"] == 3600


def test_the_fake_outside_development_logs_once_and_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ran: list[bool] = []

    def run_async(coroutine: Any) -> dict[str, int]:
        coroutine.close()
        ran.append(True)
        return {"unchanged": 1}

    monkeypatch.setattr(job, "run_async", run_async)
    monkeypatch.setattr(settings, "domain_provider", "fake")
    monkeypatch.setattr(settings, "environment", "staging")
    with capture_logs() as logs:
        assert job.check_all() == {}
    assert ran == []
    not_run = [log for log in logs if log["event"] == "mail_domains_check_not_run"]
    assert len(not_run) == 1
    assert "Set DOMAIN_PROVIDER=route53" in str(not_run[0]["reason"])
    assert [log["event"] for log in logs if "mail_domain" in str(log["event"])] == [
        "mail_domains_check_not_run"
    ]

    # The control: in development the job goes on to the domains.
    monkeypatch.setattr(settings, "environment", "development")
    assert job.check_all() == {"unchanged": 1}
    assert ran == [True]

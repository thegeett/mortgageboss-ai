"""LP-994 — `send_draft(transmit=...)`: Send queues for the worker; "I've sent it" only records.

The worker itself is tested in `tests/tasks/test_outbound_send_lp994.py`.
"""

from __future__ import annotations

import ast
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models.base import utcnow
from app.models.communication import Communication, CommunicationDirection, CommunicationStatus
from app.models.communication_evidence import CommunicationEvidence, EvidenceEvent
from app.models.company_mail_domain import MailDomainStatus
from app.models.needs_item import NeedsItemStatus
from app.models.suppressed_address import SuppressionReason
from app.services.bounce_handling import suppress_address
from app.services.email_draft import _mark_sent
from app.services.email_send import CannotSendError, send_draft
from app.services.mail_domain import set_company_mail_domain
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from tests.outbound_send import Ready, ready_to_send

TO = "borrower@example.test"


@pytest.fixture(autouse=True)
def _can_send(file_addresses_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mail_transport", "smtp")


async def _send(db: AsyncSession, ready: Ready, *, transmit: bool, to: str = TO) -> Communication:
    return await send_draft(
        db,
        loan_file=ready.loan_file,
        draft_id=ready.draft.id,
        recipient=to,
        body="Please send your bank statements.",
        approver_user_id=ready.user.id,
        transmit=transmit,
    )


# --------------------------------------------------------------------------------------------- #
# transmit=False: today's behaviour, for every existing caller
# --------------------------------------------------------------------------------------------- #
async def test_record_only_send_is_sent_and_never_queued(db_session: AsyncSession) -> None:
    ready = await ready_to_send(db_session)
    sent = await _send(db_session, ready, transmit=False)
    assert sent.status is CommunicationStatus.SENT
    assert sent.sent_at is not None
    assert sent.send_requested_at is None


async def test_ive_sent_it_never_queues(db_session: AsyncSession) -> None:
    """`_mark_sent` is "I've sent it": the processor sent it herself. It must not reach the worker."""
    ready = await ready_to_send(db_session)
    ready.draft.recipient = TO
    await _mark_sent(
        db_session, loan_file=ready.loan_file, draft=ready.draft, actor_user_id=ready.user.id
    )
    assert ready.draft.status is CommunicationStatus.SENT
    assert ready.draft.send_requested_at is None


def _send_draft_calls() -> list[tuple[str, ast.Call]]:
    calls = []
    for path in sorted(Path("app").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "send_draft"
            ):
                calls.append((str(path), node))
    return calls


def test_only_the_send_endpoint_can_ask_to_transmit() -> None:
    """Every caller of `send_draft` but the endpoint is record-only ("I've sent it", condition
    drafts). Read from the source, so a new caller that passes `transmit` fails here."""
    calls = _send_draft_calls()
    files = {path for path, _ in calls}
    # Positive control: the three known callers are found, so an empty scan cannot pass.
    assert {
        "app/api/communications.py",
        "app/services/email_draft.py",
        "app/services/condition_drafts.py",
    } <= files
    transmitting = [
        (path, ast.unparse(kw.value))
        for path, call in calls
        for kw in call.keywords
        if kw.arg == "transmit"
    ]
    assert transmitting == [("app/api/communications.py", "payload.transmit")]


# --------------------------------------------------------------------------------------------- #
# transmit=True: refusals
# --------------------------------------------------------------------------------------------- #
async def test_refused_without_an_active_domain(db_session: AsyncSession) -> None:
    ready = await ready_to_send(db_session, with_domain=False)
    with pytest.raises(CannotSendError, match="can't send email from the app yet"):
        await _send(db_session, ready, transmit=True)
    assert ready.draft.status is CommunicationStatus.DRAFT


async def test_refused_when_the_domain_is_switched_off(db_session: AsyncSession) -> None:
    ready = await ready_to_send(db_session)
    await set_company_mail_domain(
        db_session,
        company_id=ready.company.id,
        domain=ready.domain,
        status=MailDomainStatus.INACTIVE,
    )
    with pytest.raises(CannotSendError, match="can't send email from the app yet"):
        await _send(db_session, ready, transmit=True)


async def test_refused_without_a_sender(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "mail_transport", None)
    ready = await ready_to_send(db_session)
    with pytest.raises(CannotSendError, match="not set up"):
        await _send(db_session, ready, transmit=True)


@pytest.mark.parametrize(
    "to", ["", "   ", "not-an-address", "a@x.test, b@y.test", "Pat <a@x.test>", "a@b@c.test"]
)
async def test_refused_unless_exactly_one_address(db_session: AsyncSession, to: str) -> None:
    ready = await ready_to_send(db_session)
    with pytest.raises(CannotSendError, match="recipient"):
        await _send(db_session, ready, transmit=True, to=to)
    assert ready.draft.status is CommunicationStatus.DRAFT


async def test_refused_for_a_suppressed_address(db_session: AsyncSession) -> None:
    ready = await ready_to_send(db_session)
    await suppress_address(
        db_session,
        company_id=ready.company.id,
        address=TO,
        reason=SuppressionReason.HARD_BOUNCE,
    )
    with pytest.raises(CannotSendError, match="is blocked"):
        await _send(db_session, ready, transmit=True)


# --------------------------------------------------------------------------------------------- #
# transmit=True: what is recorded
# --------------------------------------------------------------------------------------------- #
async def test_transmit_queues_and_records_everything_but_sent_at(
    db_session: AsyncSession,
) -> None:
    ready = await ready_to_send(db_session)
    before = utcnow()
    queued = await _send(db_session, ready, transmit=True)

    assert queued.status is CommunicationStatus.QUEUED
    assert queued.send_requested_at is not None and queued.send_requested_at >= before
    assert queued.sent_at is None
    assert queued.recipient == TO
    assert ready.need.status is NeedsItemStatus.REQUESTED
    assert ready.need.requested_at is not None
    evidence = await db_session.scalar(
        select(CommunicationEvidence).where(CommunicationEvidence.communication_id == queued.id)
    )
    assert evidence is not None
    assert evidence.event is EvidenceEvent.SENT
    assert evidence.approver_user_id == ready.user.id


# --------------------------------------------------------------------------------------------- #
# The rate limit counts what has not gone yet
# --------------------------------------------------------------------------------------------- #
async def test_a_second_quick_transmit_send_to_one_address_is_refused(
    db_session: AsyncSession,
) -> None:
    """The first Send is still `queued` (no `sent_at`). Counting only `sent` let this through."""
    first = await ready_to_send(db_session)
    await _send(db_session, first, transmit=True)
    second = await ready_to_send(db_session)
    second.loan_file.company_id = first.company.id
    await db_session.flush()
    with pytest.raises(CannotSendError, match="less than 5 minutes ago"):
        await _send(db_session, second, transmit=True)


async def _outbound(
    db: AsyncSession, ready: Ready, status: CommunicationStatus, **when: Any
) -> None:
    db.add(
        Communication(
            loan_file_id=ready.loan_file.id,
            direction=CommunicationDirection.OUTBOUND,
            status=status,
            recipient=TO,
            **when,
        )
    )
    await db.flush()


@pytest.mark.parametrize(
    ("status", "when"),
    [
        (CommunicationStatus.QUEUED, "send_requested_at"),
        (CommunicationStatus.SENDING, "send_requested_at"),
        (CommunicationStatus.SENT, "sent_at"),
        (CommunicationStatus.DELIVERED, "sent_at"),
    ],
)
async def test_each_counted_status_blocks_a_send_within_five_minutes(
    db_session: AsyncSession, status: CommunicationStatus, when: str
) -> None:
    ready = await ready_to_send(db_session)
    await _outbound(db_session, ready, status, **{when: utcnow()})
    with pytest.raises(CannotSendError, match="less than 5 minutes ago"):
        await _send(db_session, ready, transmit=True)


async def test_the_daily_limit_counts_delivered_and_queued(db_session: AsyncSession) -> None:
    from datetime import timedelta

    ready = await ready_to_send(db_session)
    earlier = utcnow() - timedelta(hours=2)
    await _outbound(db_session, ready, CommunicationStatus.DELIVERED, sent_at=earlier)
    await _outbound(db_session, ready, CommunicationStatus.SENT, sent_at=earlier)
    await _outbound(db_session, ready, CommunicationStatus.QUEUED, send_requested_at=earlier)
    with pytest.raises(CannotSendError, match="3 times today"):
        await _send(db_session, ready, transmit=True)


async def test_failed_and_auto_reply_rows_do_not_count(db_session: AsyncSession) -> None:
    """Control for the two above: a clean failure sent nothing, and an LP-815 automatic reply
    (`queued`, no `send_requested_at`) has no time to count by."""
    ready = await ready_to_send(db_session)
    await _outbound(db_session, ready, CommunicationStatus.FAILED, send_requested_at=utcnow())
    await _outbound(db_session, ready, CommunicationStatus.QUEUED)
    queued = await _send(db_session, ready, transmit=True)
    assert queued.status is CommunicationStatus.QUEUED


# --------------------------------------------------------------------------------------------- #
# The endpoint
# --------------------------------------------------------------------------------------------- #
@pytest_asyncio.fixture
async def db(test_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    connection = await test_engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


@pytest_asyncio.fixture
async def client(db: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_db, None)


def _headers(ready: Ready) -> dict[str, str]:
    from app.core.jwt import create_access_token

    return {"Authorization": f"Bearer {create_access_token(ready.user.id)}"}


@pytest.fixture
def events(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Order of commit and enqueue, so "enqueued after the commit" is checked, not assumed."""
    from app.tasks import outbound

    seen: list[str] = []
    real_commit = db.commit

    async def commit() -> None:
        seen.append("commit")
        await real_commit()

    monkeypatch.setattr(db, "commit", commit)
    monkeypatch.setattr(outbound.send_communication, "delay", lambda pk: seen.append(f"delay:{pk}"))
    return seen


async def _post(client: AsyncClient, ready: Ready, **extra: Any) -> Any:
    return await client.post(
        f"/api/v1/loan-files/{ready.loan_file.display_id}/outbound/draft/{ready.draft.id}/send",
        json={"recipient": TO, "body": "Please send your bank statements.", **extra},
        headers=_headers(ready),
    )


async def test_endpoint_default_records_only_and_enqueues_nothing(
    db: AsyncSession, client: AsyncClient, events: list[str]
) -> None:
    ready = await ready_to_send(db)
    response = await _post(client, ready)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "sent"
    assert events == ["commit"]
    assert ready.draft.send_requested_at is None


async def test_endpoint_transmit_queues_then_enqueues_after_the_commit(
    db: AsyncSession, client: AsyncClient, events: list[str]
) -> None:
    ready = await ready_to_send(db)
    response = await _post(client, ready, transmit=True)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "queued"
    assert body["sent_at"] is None
    assert events == ["commit", f"delay:{ready.draft.id}"]


async def test_endpoint_succeeds_when_the_broker_is_down(
    db: AsyncSession, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The row is committed `queued`; `requeue_stale` picks it up later."""
    from app.tasks import outbound

    def broker_down(_pk: str) -> None:
        raise ConnectionError("redis down")

    monkeypatch.setattr(outbound.send_communication, "delay", broker_down)
    ready = await ready_to_send(db)
    response = await _post(client, ready, transmit=True)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "queued"
    await db.refresh(ready.draft)
    assert ready.draft.status is CommunicationStatus.QUEUED


async def test_endpoint_refusal_is_a_409_with_the_reason(
    db: AsyncSession, client: AsyncClient, events: list[str]
) -> None:
    ready = await ready_to_send(db, with_domain=False)
    response = await _post(client, ready, transmit=True)
    assert response.status_code == 409
    # The app's error envelope, not `detail` (see `test_communications_lp811a`).
    assert "can't send email from the app yet" in response.text
    assert not [e for e in events if e.startswith("delay")]


# --------------------------------------------------------------------------------------------- #
# Review #3 — one mailbox however it is typed
# --------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "typed", ["Borrower@Example.TEST", "  borrower@example.test", "borrower@example.test  "]
)
async def test_the_rate_limit_sees_one_mailbox_however_it_is_typed(
    db_session: AsyncSession, typed: str
) -> None:
    ready = await ready_to_send(db_session)
    await _outbound(db_session, ready, CommunicationStatus.SENT, sent_at=utcnow())
    with pytest.raises(CannotSendError, match="less than 5 minutes ago"):
        await _send(db_session, ready, transmit=True, to=typed)


async def test_the_daily_limit_sees_one_mailbox_however_it_was_stored(
    db_session: AsyncSession,
) -> None:
    from datetime import timedelta

    ready = await ready_to_send(db_session)
    earlier = utcnow() - timedelta(hours=2)
    for stored in ("BORROWER@example.test", " borrower@example.test", "borrower@EXAMPLE.test "):
        db_session.add(
            Communication(
                loan_file_id=ready.loan_file.id,
                direction=CommunicationDirection.OUTBOUND,
                status=CommunicationStatus.SENT,
                recipient=stored,
                sent_at=earlier,
            )
        )
    await db_session.flush()
    with pytest.raises(CannotSendError, match="3 times today"):
        await _send(db_session, ready, transmit=True)


async def test_two_blank_recipients_are_still_not_one_mailbox(db_session: AsyncSession) -> None:
    """LP-847's rule, kept under the new comparison: a blank address is no address, and "  " now
    trims to the same "" every other blank-recipient send has."""
    first = await ready_to_send(db_session)
    await _send(db_session, first, transmit=False, to="")
    second = await ready_to_send(db_session)
    second.loan_file.company_id = first.company.id
    await db_session.flush()
    sent = await _send(db_session, second, transmit=False, to="   ")
    assert sent.status is CommunicationStatus.SENT

"""LP-1009 — unmatched mail's company, opening a message, the document label, Move to file."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from email.message import EmailMessage
from email.policy import default as email_policy
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from app.core.config import settings
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.main import app
from app.models import Company, LoanProgram, User, UserRole
from app.models.activity_log import ActivityLog, ActivityType
from app.models.communication import Communication, CommunicationDirection
from app.models.company_mail_domain import CompanyMailDomain, MailDomainStatus
from app.models.inbound_attachment import InboundAttachment
from app.models.inbound_message import InboundMessage, InboundRoutingState
from app.models.loan_file import LoanFile
from app.services.inbound_ingest import process_raw_message
from app.services.inbound_routing import apply_routing
from app.services.loan_files import create_loan_file
from app.services.mail_domain import set_company_mail_domain
from app.storage import get_storage_backend
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_PDF = (Path(__file__).resolve().parents[1] / "fixtures" / "attachments" / "clean.pdf").read_bytes()


@pytest.fixture(autouse=True)
def _storage_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "storage_local_path", str(tmp_path / "storage"))
    get_storage_backend.cache_clear()
    yield
    get_storage_backend.cache_clear()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_db, None)


class _Company:
    def __init__(self, company: Company, auth: dict[str, str], domain: str, files: list[LoanFile]):
        self.company = company
        self.auth = auth
        self.domain = domain
        self.files = files

    def address(self, index: int = 0) -> str:
        return f"{self.files[index].display_id.lower()}@{self.domain}"


async def _company(db: AsyncSession, slug: str, *, domain: bool = True) -> _Company:
    company = Company(name=slug.title(), slug=f"{slug}-{uuid4().hex[:8]}")
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id,
        email=f"u-{uuid4().hex[:6]}@example.test",
        hashed_password="x",  # pragma: allowlist secret
        first_name="Pat",
        last_name="Processor",
        role=UserRole.PROCESSOR,
    )
    db.add(user)
    name = f"mb-{uuid4().hex[:8]}.example.test"
    if domain:
        await set_company_mail_domain(db, company_id=company.id, domain=name)
    files = [
        await create_loan_file(db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL)
        for _ in range(2)
    ]
    await db.flush()
    return _Company(
        company, {"Authorization": f"Bearer {create_access_token(user.id)}"}, name, files
    )


async def _set_status(db: AsyncSession, company: Company, status: MailDomainStatus) -> None:
    row = await db.scalar(
        select(CompanyMailDomain).where(CompanyMailDomain.company_id == company.id)
    )
    assert row is not None
    row.status = status
    await db.flush()


async def _arrive(
    db: AsyncSession, recipients: list[str], *, dmarc: str = "PASS", virus: str = "PASS"
) -> InboundMessage:
    message = EmailMessage()
    message["From"] = "jane@borrower.example"
    message["To"] = recipients[0] if recipients else "x@example.test"
    message["Subject"] = "Documents"
    message["Message-ID"] = f"<{uuid4().hex}@borrower.example>"
    message["Date"] = "Tue, 03 Nov 2026 10:00:00 +0000"
    message.set_content("attached")
    message.add_attachment(_PDF, maintype="application", subtype="pdf", filename="March.pdf")
    result = await process_raw_message(
        db,
        raw=message.as_bytes(policy=email_policy),
        raw_storage_path=None,
        store_raw=True,
        receipt={
            "recipients": recipients,
            "dmarcVerdict": {"status": dmarc},
            "virusVerdict": {"status": virus},
        },
    )
    row = await db.get(InboundMessage, UUID(result.message_id))
    assert row is not None
    return row


async def _attachment(db: AsyncSession, message: InboundMessage) -> InboundAttachment:
    return (
        await db.execute(
            select(InboundAttachment).where(InboundAttachment.inbound_message_id == message.id)
        )
    ).scalar_one()


async def _communication(db: AsyncSession, message: InboundMessage) -> Communication:
    return (
        await db.execute(
            select(Communication).where(Communication.inbound_message_id == message.id)
        )
    ).scalar_one()


# --------------------------------------------------------------------------------------------- #
# 0. The company of unmatched mail
# --------------------------------------------------------------------------------------------- #
async def test_a_typo_on_a_company_domain_goes_to_that_company(db_session: AsyncSession) -> None:
    a = await _company(db_session, "a")
    await _company(db_session, "b")
    message = await _arrive(db_session, [f"lf-typo@{a.domain}"])
    assert message.company_id == a.company.id
    assert message.routing_state is InboundRoutingState.UNROUTED
    assert message.loan_file_id is None


async def test_two_files_in_one_company_go_to_that_company(db_session: AsyncSession) -> None:
    a = await _company(db_session, "a")
    message = await _arrive(db_session, [a.address(0), a.address(1)])
    assert message.company_id == a.company.id
    assert message.routing_state is InboundRoutingState.UNROUTED


async def test_two_companies_go_to_no_company(db_session: AsyncSession) -> None:
    a = await _company(db_session, "a")
    b = await _company(db_session, "b")
    message = await _arrive(db_session, [a.address(), b.address()])
    assert message.company_id is None


async def test_a_typo_on_each_of_two_companies_goes_to_no_company(db_session: AsyncSession) -> None:
    a = await _company(db_session, "a")
    b = await _company(db_session, "b")
    message = await _arrive(db_session, [f"x@{a.domain}", f"y@{b.domain}"])
    assert message.company_id is None


async def test_a_domain_with_no_row_goes_to_no_company(db_session: AsyncSession) -> None:
    await _company(db_session, "a")
    message = await _arrive(db_session, ["lf-abcd@nobody.example.test"])
    assert message.company_id is None


async def test_one_known_and_one_unknown_domain_goes_to_no_company(
    db_session: AsyncSession,
) -> None:
    a = await _company(db_session, "a")
    message = await _arrive(db_session, [f"x@{a.domain}", "y@nobody.example.test"])
    assert message.company_id is None


async def test_no_recipients_goes_to_no_company(db_session: AsyncSession) -> None:
    await _company(db_session, "a")
    message = await _arrive(db_session, [])
    assert message.company_id is None


@pytest.mark.parametrize(
    ("status", "owned"),
    [
        (MailDomainStatus.ACTIVE, True),
        (MailDomainStatus.PROBLEM, True),
        (MailDomainStatus.VERIFYING, False),
        (MailDomainStatus.PENDING_NS, False),
        (MailDomainStatus.INACTIVE, False),
    ],
)
async def test_only_receiving_statuses_name_the_company(
    db_session: AsyncSession, status: MailDomainStatus, owned: bool
) -> None:
    a = await _company(db_session, "a")
    await _set_status(db_session, a.company, status)
    message = await _arrive(db_session, [f"x@{a.domain}"])
    assert (message.company_id == a.company.id) is owned


async def test_a_virus_is_still_rejected_with_no_company(db_session: AsyncSession) -> None:
    a = await _company(db_session, "a")
    message = await _arrive(db_session, [f"x@{a.domain}"], virus="FAIL")
    assert message.routing_state is InboundRoutingState.REJECTED
    assert message.company_id is None


async def test_the_sender_and_headers_name_no_company(db_session: AsyncSession) -> None:
    """To names company A's domain and the sender uses it. The envelope is the only input."""
    a = await _company(db_session, "a")
    message = InboundMessage(
        ingest_key=f"key-{uuid4().hex}",
        from_address=f"someone@{a.domain}",
        to_addresses=[f"x@{a.domain}"],
        envelope_recipients=["x@nobody.example.test"],
    )
    db_session.add(message)
    await db_session.flush()
    await apply_routing(db_session, message=message)
    assert message.company_id is None


async def test_its_own_company_sees_it_with_the_sender_and_no_other_does(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a = await _company(db_session, "a")
    b = await _company(db_session, "b")
    message = await _arrive(db_session, [f"lf-typo@{a.domain}"])
    await db_session.commit()

    own = (await client.get("/api/v1/inbound/queue", headers=a.auth)).json()
    other = (await client.get("/api/v1/inbound/queue", headers=b.auth)).json()

    assert [row["id"] for row in own] == [str(message.id)]
    assert own[0]["from_address"] == "jane@borrower.example"
    assert own[0]["attachments"][0]["filename_original"] == "March.pdf"
    assert own[0]["communication_id"] is None
    assert other == []


# --------------------------------------------------------------------------------------------- #
# 1. Capabilities
# --------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("status", "inbox"),
    [
        (MailDomainStatus.ACTIVE, True),
        (MailDomainStatus.PROBLEM, True),
        (MailDomainStatus.VERIFYING, False),
        (MailDomainStatus.PENDING_NS, False),
        (MailDomainStatus.INACTIVE, False),
    ],
)
async def test_inbox_follows_the_companys_domain(
    client: AsyncClient, db_session: AsyncSession, status: MailDomainStatus, inbox: bool
) -> None:
    a = await _company(db_session, "a")
    await _set_status(db_session, a.company, status)
    body = (await client.get("/api/v1/capabilities", headers=a.auth)).json()
    assert body["inbox"] is inbox


async def test_no_domain_means_no_inbox_even_with_another_company_on(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _company(db_session, "on")
    off = await _company(db_session, "off", domain=False)
    body = (await client.get("/api/v1/capabilities", headers=off.auth)).json()
    assert body["inbox"] is False


@pytest.mark.parametrize("enabled", [True, False])
async def test_upload_links_follow_the_global_setting_not_the_domain(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, enabled: bool
) -> None:
    monkeypatch.setattr(settings, "receiving_enabled", enabled)
    a = await _company(db_session, "a")
    body = (await client.get("/api/v1/capabilities", headers=a.auth)).json()
    assert body["receiving"] is enabled
    assert body["inbox"] is True


# --------------------------------------------------------------------------------------------- #
# 2. Opening a message
# --------------------------------------------------------------------------------------------- #
async def test_opening_a_message_sets_read_once_and_the_list_shows_it(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a = await _company(db_session, "a")
    message = await _arrive(db_session, [a.address()])
    communication = await _communication(db_session, message)
    await db_session.commit()
    file_id = a.files[0].id
    messages_url = f"/api/v1/loan-files/{file_id}/inbound/messages"

    before = (await client.get(messages_url, headers=a.auth)).json()
    assert before[0]["unread"] is True
    assert before[0]["communication_id"] == str(communication.id)

    detail_url = f"/api/v1/loan-files/{file_id}/messages/{communication.id}"
    first = (await client.get(detail_url, headers=a.auth)).json()
    assert first["read_at"] is not None
    second = (await client.get(detail_url, headers=a.auth)).json()
    assert second["read_at"] == first["read_at"]

    after = (await client.get(messages_url, headers=a.auth)).json()
    assert after[0]["unread"] is False


async def test_opening_a_message_shows_its_subject_and_text(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a = await _company(db_session, "a")
    message = await _arrive(db_session, [a.address()])
    communication = await _communication(db_session, message)
    await db_session.commit()

    detail = (
        await client.get(
            f"/api/v1/loan-files/{a.files[0].id}/messages/{communication.id}", headers=a.auth
        )
    ).json()
    assert detail["subject"] == "Documents"
    assert detail["body"] == "attached"
    assert detail["body_format"] == "plain"
    assert detail["body_unavailable"] is False


async def test_a_missing_original_says_so_and_still_opens(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a = await _company(db_session, "a")
    message = await _arrive(db_session, [a.address()])
    communication = await _communication(db_session, message)
    message.raw_storage_path = "s3://another-bucket/inbound/x"
    await db_session.commit()

    response = await client.get(
        f"/api/v1/loan-files/{a.files[0].id}/messages/{communication.id}", headers=a.auth
    )
    assert response.status_code == 200
    detail = response.json()
    assert detail["subject"] == "Documents"
    assert detail["body"] == ""
    assert detail["body_unavailable"] is True
    assert detail["attachments"]


async def test_an_unparseable_original_says_so_and_still_opens(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import inbound_mime

    def _broken(raw: bytes) -> str:
        raise ValueError("malformed")

    monkeypatch.setattr(inbound_mime, "body_text", _broken)
    a = await _company(db_session, "a")
    message = await _arrive(db_session, [a.address()])
    communication = await _communication(db_session, message)
    await db_session.commit()

    response = await client.get(
        f"/api/v1/loan-files/{a.files[0].id}/messages/{communication.id}", headers=a.auth
    )
    assert response.status_code == 200
    assert response.json()["body_unavailable"] is True


async def test_a_storage_failure_of_any_kind_still_opens(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import inbound_triage

    async def _broken(message: InboundMessage) -> bytes:
        raise TimeoutError

    monkeypatch.setattr(inbound_triage, "raw_message", _broken)
    a = await _company(db_session, "a")
    message = await _arrive(db_session, [a.address()])
    communication = await _communication(db_session, message)
    await db_session.commit()

    response = await client.get(
        f"/api/v1/loan-files/{a.files[0].id}/messages/{communication.id}", headers=a.auth
    )
    assert response.status_code == 200
    assert response.json()["body_unavailable"] is True


async def test_a_row_with_its_own_body_keeps_it(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a = await _company(db_session, "a")
    message = await _arrive(db_session, [a.address()])
    communication = await _communication(db_session, message)
    communication.subject = "Row subject"
    communication.body = "Row body"
    await db_session.commit()

    detail = (
        await client.get(
            f"/api/v1/loan-files/{a.files[0].id}/messages/{communication.id}", headers=a.auth
        )
    ).json()
    assert detail["subject"] == "Row subject"
    assert detail["body"] == "Row body"


async def test_the_email_text_is_reported_as_plain_whatever_the_column_says(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models.communication import BodyFormat

    a = await _company(db_session, "a")
    message = await _arrive(db_session, [a.address()])
    communication = await _communication(db_session, message)
    communication.body_format = BodyFormat.HTML
    await db_session.commit()

    detail = (
        await client.get(
            f"/api/v1/loan-files/{a.files[0].id}/messages/{communication.id}", headers=a.auth
        )
    ).json()
    assert detail["body"] == "attached"
    assert detail["body_format"] == "plain"


async def test_only_the_open_that_marks_it_read_says_so(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a = await _company(db_session, "a")
    message = await _arrive(db_session, [a.address()])
    communication = await _communication(db_session, message)
    await db_session.commit()
    url = f"/api/v1/loan-files/{a.files[0].id}/messages/{communication.id}"

    assert (await client.get(url, headers=a.auth)).json()["marked_read"] is True
    assert (await client.get(url, headers=a.auth)).json()["marked_read"] is False


async def test_the_inbox_lists_in_the_same_number_of_queries_however_many_emails(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from sqlalchemy import event

    a = await _company(db_session, "a")
    await _arrive(db_session, [f"typo-1@{a.domain}"])
    await db_session.commit()
    engine = db_session.bind.sync_engine  # type: ignore[union-attr]
    statements: list[str] = []

    def _count(*args: Any) -> None:
        statements.append(args[2])

    async def _queries() -> int:
        statements.clear()
        event.listen(engine, "before_cursor_execute", _count)
        try:
            response = await client.get("/api/v1/inbound/queue", headers=a.auth)
        finally:
            event.remove(engine, "before_cursor_execute", _count)
        assert response.status_code == 200
        return len(statements)

    one = await _queries()
    for n in range(2, 6):
        await _arrive(db_session, [f"typo-{n}@{a.domain}"])
    await db_session.commit()
    five = await _queries()
    assert len((await client.get("/api/v1/inbound/queue", headers=a.auth)).json()) == 5
    assert five == one


def _text_of(build: Any) -> str:
    from app.services.inbound_mime import body_text

    message = EmailMessage()
    build(message)
    return body_text(message.as_bytes(policy=email_policy))


def test_html_only_mail_becomes_plain_text_without_markup_or_script() -> None:
    text = _text_of(
        lambda m: m.set_content("<p>Hi <b>there</b></p><script>alert(1)</script>", subtype="html")
    )
    assert text == "Hi there"


def test_the_plain_part_wins_over_the_html_one() -> None:
    def build(m: EmailMessage) -> None:
        m.set_content("plain words")
        m.add_alternative("<p>html words</p>", subtype="html")

    assert _text_of(build) == "plain words"


def test_a_forward_shows_the_senders_words_not_the_forwarded_mail() -> None:
    inner = EmailMessage()
    inner.set_content("inner words")

    def build(m: EmailMessage) -> None:
        m.set_content("my note")
        m.add_attachment(inner)

    assert _text_of(build) == "my note"


def test_attachments_only_is_no_text() -> None:
    def build(m: EmailMessage) -> None:
        m.make_mixed()
        m.add_attachment(_PDF, maintype="application", subtype="pdf", filename="a.pdf")

    assert _text_of(build) == ""


async def test_opening_an_outbound_draft_sets_nothing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models.communication import CommunicationStatus

    a = await _company(db_session, "a")
    draft = Communication(
        loan_file_id=a.files[0].id,
        direction=CommunicationDirection.OUTBOUND,
        status=CommunicationStatus.DRAFT,
        body="hello",
    )
    db_session.add(draft)
    await db_session.commit()
    body = (
        await client.get(f"/api/v1/loan-files/{a.files[0].id}/messages/{draft.id}", headers=a.auth)
    ).json()
    assert body["read_at"] is None


# --------------------------------------------------------------------------------------------- #
# 3. What the document label needs
# --------------------------------------------------------------------------------------------- #
async def test_an_accepted_attachment_carries_its_email_in_list_and_detail(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a = await _company(db_session, "a")
    message = await _arrive(db_session, [a.address()])
    attachment = await _attachment(db_session, message)
    await db_session.commit()
    file_id = a.files[0].id

    accepted = await client.post(
        f"/api/v1/loan-files/{file_id}/inbound/attachments/{attachment.id}/accept",
        headers=a.auth,
        json={},
    )
    assert accepted.status_code == 200, accepted.text
    document_id = accepted.json()["document_id"]

    # The panel can link to the document it made.
    panel = (
        await client.get(f"/api/v1/loan-files/{file_id}/inbound/messages", headers=a.auth)
    ).json()
    assert panel[0]["attachments"][0]["document_id"] == document_id

    listed = (await client.get(f"/api/v1/loan-files/{file_id}/documents", headers=a.auth)).json()
    detail = (await client.get(f"/api/v1/documents/{document_id}", headers=a.auth)).json()
    for body in (listed[0], detail):
        assert body["upload_source"] == "borrower_inbox"
        origin = body["email_origin"]
        assert origin["from_address"] == "jane@borrower.example"
        assert origin["inbound_message_id"] == str(message.id)
        # LP-1011 — when we received it, not the email's `Date` header (3 Nov 2026 10:00).
        assert origin["received_at"] == message.created_at.isoformat().replace("+00:00", "Z")


async def test_a_manual_upload_has_no_email_origin(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a = await _company(db_session, "a")
    uploaded = await client.post(
        f"/api/v1/loan-files/{a.files[0].id}/documents",
        headers=a.auth,
        files={"files": ("a.pdf", _PDF, "application/pdf")},
    )
    assert uploaded.status_code == 201, uploaded.text
    assert uploaded.json()[0]["upload_source"] == "user_upload"
    assert uploaded.json()[0]["email_origin"] is None


# --------------------------------------------------------------------------------------------- #
# 4. Move to file
# --------------------------------------------------------------------------------------------- #
def _move_url(message: InboundMessage) -> str:
    return f"/api/v1/inbound/messages/{message.id}/move"


async def test_moving_puts_it_on_the_file_the_same_way_routing_does(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a = await _company(db_session, "a")
    message = await _arrive(db_session, [f"lf-typo@{a.domain}"])
    await db_session.commit()
    target = a.files[1]

    moved = await client.post(
        _move_url(message), headers=a.auth, json={"file_identifier": target.display_id}
    )

    assert moved.status_code == 200, moved.text
    await db_session.refresh(message)
    assert message.loan_file_id == target.id
    assert message.routing_state is InboundRoutingState.ROUTED
    assert message.routing_signal == "manual"
    assert message.company_id == a.company.id

    communication = await _communication(db_session, message)
    assert communication.loan_file_id == target.id
    assert communication.direction is CommunicationDirection.INBOUND
    assert communication.read_at is None

    activity = (
        await db_session.execute(
            select(ActivityLog).where(
                ActivityLog.loan_file_id == target.id,
                ActivityLog.activity_type == ActivityType.COMMUNICATION_RECEIVED,
            )
        )
    ).scalar_one()
    assert activity.actor_user_id is not None
    assert activity.detail["inbound_message_id"] == str(message.id)
    assert activity.detail["routing_signal"] == "manual"

    # It is now usable on that file.
    attachment = await _attachment(db_session, message)
    accepted = await client.post(
        f"/api/v1/loan-files/{target.id}/inbound/attachments/{attachment.id}/accept",
        headers=a.auth,
        json={},
    )
    assert accepted.status_code == 200, accepted.text


async def test_another_companys_message_is_a_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a = await _company(db_session, "a")
    b = await _company(db_session, "b")
    message = await _arrive(db_session, [f"lf-typo@{a.domain}"])
    await db_session.commit()

    moved = await client.post(
        _move_url(message), headers=b.auth, json={"file_identifier": b.files[0].display_id}
    )

    assert moved.status_code == 404
    await db_session.refresh(message)
    assert message.loan_file_id is None


async def test_another_companys_file_is_a_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a = await _company(db_session, "a")
    b = await _company(db_session, "b")
    message = await _arrive(db_session, [f"lf-typo@{a.domain}"])
    await db_session.commit()

    moved = await client.post(
        _move_url(message), headers=a.auth, json={"file_identifier": b.files[0].display_id}
    )

    assert moved.status_code == 404
    await db_session.refresh(message)
    assert message.loan_file_id is None
    assert message.routing_state is InboundRoutingState.UNROUTED


async def test_a_message_with_no_company_is_a_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a = await _company(db_session, "a")
    message = await _arrive(db_session, ["x@nobody.example.test"])
    await db_session.commit()
    moved = await client.post(
        _move_url(message), headers=a.auth, json={"file_identifier": a.files[0].display_id}
    )
    assert moved.status_code == 404


async def test_a_message_already_on_a_file_is_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a = await _company(db_session, "a")
    message = await _arrive(db_session, [a.address(0)])
    await db_session.commit()
    moved = await client.post(
        _move_url(message), headers=a.auth, json={"file_identifier": a.files[1].display_id}
    )
    assert moved.status_code == 409
    await db_session.refresh(message)
    assert message.loan_file_id == a.files[0].id


# --------------------------------------------------------------------------------------------- #
# 5. The paused reason
# --------------------------------------------------------------------------------------------- #
async def _draft_detail(
    client: AsyncClient, db: AsyncSession, a: _Company, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    from app.models.communication import CommunicationStatus

    draft = Communication(
        loan_file_id=a.files[0].id,
        direction=CommunicationDirection.OUTBOUND,
        status=CommunicationStatus.DRAFT,
        body="hello",
    )
    db.add(draft)
    await db.commit()
    response = await client.get(
        f"/api/v1/loan-files/{a.files[0].id}/messages/{draft.id}", headers=a.auth
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (MailDomainStatus.PROBLEM, True),
        (MailDomainStatus.ACTIVE, False),
        (MailDomainStatus.INACTIVE, False),
    ],
)
async def test_the_reason_is_returned_only_when_paused(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    status: MailDomainStatus,
    reason: bool,
) -> None:
    from app.services.mail_domain import MAIL_DOMAIN_PAUSED

    a = await _company(db_session, "a")
    await _set_status(db_session, a.company, status)
    body = await _draft_detail(client, db_session, a, monkeypatch)
    assert body["can_send"] is False  # sending is off in every case here
    assert body["send_blocked_reason"] == (MAIL_DOMAIN_PAUSED if reason else None)


# --------------------------------------------------------------------------------------------- #
# LP-1011 — Dismiss, and the arrival time
# --------------------------------------------------------------------------------------------- #
def _dismiss_url(message: InboundMessage) -> str:
    return f"/api/v1/inbound/messages/{message.id}/dismiss"


async def test_lp1011_dismiss_takes_it_off_the_inbox_and_keeps_the_row(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a = await _company(db_session, "a")
    message = await _arrive(db_session, [f"lf-typo@{a.domain}"])
    kept = await _arrive(db_session, [f"lf-other@{a.domain}"])
    await db_session.commit()
    queue = "/api/v1/inbound/queue"
    assert {m["id"] for m in (await client.get(queue, headers=a.auth)).json()} == {
        str(message.id),
        str(kept.id),
    }

    dismissed = await client.post(_dismiss_url(message), headers=a.auth)

    assert dismissed.status_code == 200, dismissed.text
    assert [m["id"] for m in (await client.get(queue, headers=a.auth)).json()] == [str(kept.id)]
    await db_session.refresh(message)
    assert message.routing_state is InboundRoutingState.REJECTED
    assert message.company_id == a.company.id
    assert message.deleted_at is None


async def test_lp1011_another_companys_message_cannot_be_dismissed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a = await _company(db_session, "a")
    b = await _company(db_session, "b")
    message = await _arrive(db_session, [f"lf-typo@{a.domain}"])
    await db_session.commit()

    assert (await client.post(_dismiss_url(message), headers=b.auth)).status_code == 404
    await db_session.refresh(message)
    assert message.routing_state is InboundRoutingState.UNROUTED


async def test_lp1011_a_message_on_a_file_cannot_be_dismissed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a = await _company(db_session, "a")
    message = await _arrive(db_session, [a.address()])
    await db_session.commit()

    assert (await client.post(_dismiss_url(message), headers=a.auth)).status_code == 409
    await db_session.refresh(message)
    assert message.routing_state is InboundRoutingState.ROUTED


async def test_lp1011_the_card_shows_when_we_received_it_not_the_date_header(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """`_arrive` writes `Date: 3 Nov 2026`; the row is created now. A year-off header would read the
    same: the card follows the row."""
    a = await _company(db_session, "a")
    message = await _arrive(db_session, [a.address()])
    message.received_at = message.created_at.replace(year=message.created_at.year - 1)
    await db_session.commit()

    listed = (
        await client.get(f"/api/v1/loan-files/{a.files[0].id}/inbound/messages", headers=a.auth)
    ).json()
    expected = message.created_at.isoformat().replace("+00:00", "Z")
    assert listed[0]["received_at"] == expected

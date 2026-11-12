"""LP-1008 — the dev injector routes the way SES does: from the envelope, into mail storage."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from email.message import EmailMessage
from email.policy import default as email_policy
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from app.core.config import settings
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.main import app
from app.models import Company, LoanProgram, UserRole
from app.models.inbound_attachment import InboundAttachment
from app.models.inbound_message import InboundMessage, InboundRoutingState
from app.models.loan_file import LoanFile
from app.services.loan_files import create_loan_file
from app.services.mail_domain import set_company_mail_domain
from app.storage import get_mail_storage, get_storage_backend
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.user_factory import make_user

_PDF = (Path(__file__).resolve().parents[1] / "fixtures" / "attachments" / "clean.pdf").read_bytes()
_INJECT = "/api/v1/dev/inbound/inject"


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


async def _setup(db: AsyncSession) -> tuple[dict[str, str], list[LoanFile], str]:
    company = Company(name="Summit", slug=f"summit-{uuid4().hex[:6]}")
    db.add(company)
    await db.flush()
    user = make_user(
        company_id=company.id,
        email=f"u-{uuid4().hex[:6]}@example.test",
        hashed_password="x",  # pragma: allowlist secret
        first_name="Pat",
        last_name="Processor",
        roles=[UserRole.PROCESSOR],
    )
    db.add(user)
    domain = f"mb-{uuid4().hex[:8]}.example.test"
    await set_company_mail_domain(db, company_id=company.id, domain=domain)
    files = [
        await create_loan_file(db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL)
        for _ in range(2)
    ]
    await db.flush()
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}, files, domain


def _eml(to: str) -> bytes:
    message = EmailMessage()
    message["From"] = "jane@borrower.example"
    message["To"] = to
    message["Subject"] = "Documents"
    message["Message-ID"] = f"<{uuid4().hex}@borrower.example>"
    message.set_content("attached")
    message.add_attachment(_PDF, maintype="application", subtype="pdf", filename="March.pdf")
    return message.as_bytes(policy=email_policy)


async def _inject(
    client: AsyncClient,
    db: AsyncSession,
    auth: dict[str, str],
    *,
    to: str,
    data: dict[str, str | list[str]],
) -> InboundMessage:
    response = await client.post(
        _INJECT, headers=auth, files={"file": ("m.eml", _eml(to), "message/rfc822")}, data=data
    )
    assert response.status_code == 200, response.text
    message = await db.get(InboundMessage, UUID(response.json()["inbound_message_id"]))
    assert message is not None
    return message


def _address(loan_file: LoanFile, domain: str) -> str:
    return f"{loan_file.display_id.lower()}@{domain}"


async def test_the_envelope_routes_stores_under_inbound_and_accept_works(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    auth, (file_a, file_b), domain = await _setup(db_session)

    message = await _inject(
        client,
        db_session,
        auth,
        to=_address(file_a, domain),
        data={"recipient": _address(file_b, domain)},
    )

    assert message.loan_file_id == file_b.id
    assert message.envelope_recipients == [_address(file_b, domain)]
    assert message.auth_verdicts["dmarcVerdict"] == "PASS"
    assert message.raw_storage_path == f"inbound/{message.id}"
    assert await get_mail_storage().read(f"inbound/{message.id}")

    attachment = (
        await db_session.execute(
            select(InboundAttachment).where(InboundAttachment.inbound_message_id == message.id)
        )
    ).scalar_one()
    accepted = await client.post(
        f"/api/v1/loan-files/{file_b.id}/inbound/attachments/{attachment.id}/accept",
        headers=auth,
        json={},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["document_id"]


async def test_two_recipients_on_two_files_is_unrouted(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    auth, (file_a, file_b), domain = await _setup(db_session)
    message = await _inject(
        client,
        db_session,
        auth,
        to=_address(file_a, domain),
        data={"recipient": [_address(file_a, domain), _address(file_b, domain)]},
    )
    assert message.routing_state is InboundRoutingState.UNROUTED
    assert message.loan_file_id is None


async def test_no_recipient_is_unrouted_and_a_verdict_can_be_set(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    auth, (file_a, _b), domain = await _setup(db_session)
    message = await _inject(
        client, db_session, auth, to=_address(file_a, domain), data={"dmarc_verdict": "GRAY"}
    )
    assert message.routing_state is InboundRoutingState.UNROUTED
    assert message.envelope_recipients == []
    assert message.auth_verdicts["dmarcVerdict"] == "GRAY"


async def test_lp1010_a_new_message_queues_the_copy_for_the_worker_once(
    client: AsyncClient, db_session: AsyncSession, _no_processor_copy_queued: list[str]
) -> None:
    """The API never sends (rule 8): it queues the copy, and only for a first insert."""
    auth, (file_a, _), domain = await _setup(db_session)
    raw = _eml(_address(file_a, domain))
    data = {"recipient": _address(file_a, domain), "ses_message_id": f"ses-{uuid4().hex}"}

    first = await client.post(
        _INJECT, headers=auth, files={"file": ("m.eml", raw, "message/rfc822")}, data=data
    )
    again = await client.post(
        _INJECT, headers=auth, files={"file": ("m.eml", raw, "message/rfc822")}, data=data
    )
    assert first.json()["created"] is True
    assert again.json()["created"] is False
    assert _no_processor_copy_queued == [first.json()["inbound_message_id"]]

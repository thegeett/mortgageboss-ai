"""LP-1008 — find the file by address only, from the SES envelope (loan-email.md rule 7, §3 11-04).

Two companies throughout: a display id is short and not secret, so what stops mail reaching another
company's file is the domain, and a fixture with one company could not show that.
"""

from __future__ import annotations

from collections.abc import Iterator
from email.message import EmailMessage
from email.policy import default as email_policy
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.core.config import settings
from app.models import Company, LoanProgram
from app.models.base import utcnow
from app.models.company_mail_domain import CompanyMailDomain, MailDomainStatus
from app.models.inbound_attachment import InboundAttachment
from app.models.inbound_message import InboundMessage, InboundRoutingState
from app.models.loan_file import LoanFile
from app.models.loan_file_participant import LoanFileParticipant, ParticipantRole
from app.services.inbound_ingest import ingest_raw_message, process_raw_message
from app.services.inbound_routing import (
    RoutingSignal,
    apply_routing,
    resolve_loan_file_by_address,
    route_message,
)
from app.services.inbound_triage import (
    CannotAcceptError,
    _attachment_bytes,
    accept_attachment,
    attachment_preview,
)
from app.services.loan_files import create_loan_file
from app.services.mail_domain import set_company_mail_domain
from app.storage import StorageError, get_mail_storage, get_storage_backend
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_PDF = (Path(__file__).resolve().parents[1] / "fixtures" / "attachments" / "clean.pdf").read_bytes()


@pytest.fixture(autouse=True)
def _storage_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "storage_local_path", str(tmp_path / "storage"))
    get_storage_backend.cache_clear()
    yield
    get_storage_backend.cache_clear()


async def _company_with_domain(
    db: AsyncSession, *, slug: str
) -> tuple[Company, str, list[LoanFile]]:
    company = Company(name=slug.title(), slug=f"{slug}-{uuid4().hex[:8]}")
    db.add(company)
    await db.flush()
    domain = f"mb-{uuid4().hex[:8]}.example.test"
    await set_company_mail_domain(db, company_id=company.id, domain=domain)
    files = [
        await create_loan_file(db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL)
        for _ in range(2)
    ]
    return company, domain, files


def _address(loan_file: LoanFile, domain: str) -> str:
    return f"{loan_file.display_id.lower()}@{domain}"


async def _set_status(db: AsyncSession, company: Company, status: MailDomainStatus) -> None:
    row = await db.scalar(
        select(CompanyMailDomain).where(CompanyMailDomain.company_id == company.id)
    )
    assert row is not None
    row.status = status
    await db.flush()


async def _message(db: AsyncSession, **fields: Any) -> InboundMessage:
    message = InboundMessage(
        ingest_key=f"key-{uuid4().hex[:12]}",
        from_address="jane@borrower.example",
        **fields,
    )
    db.add(message)
    await db.flush()
    return message


def _raw(*, to: str, subject: str = "Documents", body: str = "attached") -> bytes:
    message = EmailMessage()
    message["From"] = "jane@borrower.example"
    message["To"] = to
    message["Subject"] = subject
    message["Message-ID"] = f"<{uuid4().hex}@borrower.example>"
    message.set_content(body)
    message.add_attachment(_PDF, maintype="application", subtype="pdf", filename="March.pdf")
    return message.as_bytes(policy=email_policy)


# --------------------------------------------------------------------------------------------- #
# The resolver
# --------------------------------------------------------------------------------------------- #
async def test_an_address_resolves_to_its_file(db_session: AsyncSession) -> None:
    _co, domain, (loan_file, other) = await _company_with_domain(db_session, slug="a")
    resolved = await resolve_loan_file_by_address(db_session, address=_address(loan_file, domain))
    assert resolved is not None
    assert resolved.id == loan_file.id
    assert resolved.id != other.id


async def test_an_uppercase_address_resolves(db_session: AsyncSession) -> None:
    _co, domain, (loan_file, _other) = await _company_with_domain(db_session, slug="a")
    shouted = _address(loan_file, domain).upper()
    resolved = await resolve_loan_file_by_address(db_session, address=shouted)
    assert resolved is not None and resolved.id == loan_file.id


async def test_the_right_file_on_the_wrong_companys_domain_is_nothing(
    db_session: AsyncSession,
) -> None:
    """Both halves are real: the display id exists, and so does the domain, for another company."""
    _a, a_domain, (a_file, _x) = await _company_with_domain(db_session, slug="a")
    _b, b_domain, (b_file, _y) = await _company_with_domain(db_session, slug="b")

    # The control: each address does work on its own company's domain.
    assert await resolve_loan_file_by_address(db_session, address=_address(a_file, a_domain))
    assert await resolve_loan_file_by_address(db_session, address=_address(b_file, b_domain))

    assert (
        await resolve_loan_file_by_address(db_session, address=_address(a_file, b_domain)) is None
    )


@pytest.mark.parametrize(
    ("status", "receives"),
    [
        (MailDomainStatus.ACTIVE, True),
        (MailDomainStatus.PROBLEM, True),
        (MailDomainStatus.INACTIVE, False),
        (MailDomainStatus.PENDING_NS, False),
        (MailDomainStatus.VERIFYING, False),
    ],
)
async def test_which_domain_states_receive(
    db_session: AsyncSession, status: MailDomainStatus, receives: bool
) -> None:
    company, domain, (loan_file, _other) = await _company_with_domain(db_session, slug="a")
    await _set_status(db_session, company, status)
    resolved = await resolve_loan_file_by_address(db_session, address=_address(loan_file, domain))
    assert (resolved is not None) is receives


async def test_a_deleted_file_is_nothing(db_session: AsyncSession) -> None:
    _co, domain, (loan_file, _other) = await _company_with_domain(db_session, slug="a")
    address = _address(loan_file, domain)
    assert await resolve_loan_file_by_address(db_session, address=address) is not None

    loan_file.deleted_at = utcnow()
    await db_session.flush()

    assert await resolve_loan_file_by_address(db_session, address=address) is None


@pytest.mark.parametrize(
    "address",
    [
        None,
        "",
        "   ",
        "not-an-address",
        "@domain.example",
        "lf-@domain.example",
        "docs@domain.example",
    ],
)
async def test_malformed_is_nothing(db_session: AsyncSession, address: str | None) -> None:
    assert await resolve_loan_file_by_address(db_session, address=address) is None


async def test_the_old_token_form_is_nothing(db_session: AsyncSession) -> None:
    """On the old domain and on the company's own: the token no longer opens a file either way."""
    _co, domain, (loan_file, _other) = await _company_with_domain(db_session, slug="a")
    for on in ("imbox.mortgageboss.ai", domain):
        address = f"lf-{loan_file.inbox_token}@{on}"
        assert await resolve_loan_file_by_address(db_session, address=address) is None


# --------------------------------------------------------------------------------------------- #
# The envelope, never To/Cc
# --------------------------------------------------------------------------------------------- #
async def test_the_envelope_wins_over_to(db_session: AsyncSession) -> None:
    _co, domain, (file_a, file_b) = await _company_with_domain(db_session, slug="a")
    message = await _message(
        db_session,
        to_addresses=[_address(file_a, domain)],
        envelope_recipients=[_address(file_b, domain)],
    )

    outcome = await route_message(db_session, message=message)

    assert outcome.loan_file is not None and outcome.loan_file.id == file_b.id
    assert outcome.signal is RoutingSignal.INBOX_TOKEN
    assert outcome.confidence == 1.0


async def test_to_with_no_envelope_is_unrouted(db_session: AsyncSession) -> None:
    _co, domain, (file_a, _b) = await _company_with_domain(db_session, slug="a")
    message = await _message(
        db_session, to_addresses=[_address(file_a, domain)], envelope_recipients=[]
    )
    assert not (await route_message(db_session, message=message)).routed


async def test_no_receipt_through_the_chain_is_unrouted(db_session: AsyncSession) -> None:
    _co, domain, (file_a, _b) = await _company_with_domain(db_session, slug="a")
    result = await process_raw_message(
        db_session, raw=_raw(to=_address(file_a, domain)), raw_storage_path=None, store_raw=True
    )
    message = await db_session.get(InboundMessage, UUID(result.message_id))
    assert message is not None
    assert message.envelope_recipients == []
    assert message.routing_state is InboundRoutingState.UNROUTED
    assert message.loan_file_id is None
    assert message.company_id is None


async def test_two_files_is_unrouted(db_session: AsyncSession) -> None:
    _co, domain, (file_a, file_b) = await _company_with_domain(db_session, slug="a")
    message = await _message(
        db_session, envelope_recipients=[_address(file_a, domain), _address(file_b, domain)]
    )
    await apply_routing(db_session, message=message)
    assert message.routing_state is InboundRoutingState.UNROUTED
    assert message.loan_file_id is None


async def test_two_addresses_of_one_file_is_routed(db_session: AsyncSession) -> None:
    _co, domain, (file_a, _b) = await _company_with_domain(db_session, slug="a")
    address = _address(file_a, domain)
    message = await _message(db_session, envelope_recipients=[address, address.upper()])
    outcome = await route_message(db_session, message=message)
    assert outcome.loan_file is not None and outcome.loan_file.id == file_a.id


async def test_one_file_plus_an_address_that_matches_nothing_is_routed(
    db_session: AsyncSession,
) -> None:
    _co, domain, (file_a, _b) = await _company_with_domain(db_session, slug="a")
    message = await _message(
        db_session, envelope_recipients=[f"typo@{domain}", _address(file_a, domain)]
    )
    outcome = await route_message(db_session, message=message)
    assert outcome.loan_file is not None and outcome.loan_file.id == file_a.id


async def test_the_company_is_read_off_the_file(db_session: AsyncSession) -> None:
    company, domain, (file_a, _b) = await _company_with_domain(db_session, slug="a")
    await _company_with_domain(db_session, slug="b")
    message = await _message(db_session, envelope_recipients=[_address(file_a, domain)])
    await apply_routing(db_session, message=message)
    assert message.company_id == company.id
    assert message.loan_file_id == file_a.id
    assert message.routing_state is InboundRoutingState.ROUTED


async def test_rungs_two_to_five_and_route_b_are_not_called(db_session: AsyncSession) -> None:
    """Every guess has what it needs, and the same message on rung 1's address does route."""
    from app.models.communication import (
        Communication,
        CommunicationDirection,
        CommunicationStatus,
    )

    company, domain, (loan_file, _b) = await _company_with_domain(db_session, slug="a")
    db_session.add(
        LoanFileParticipant(
            loan_file_id=loan_file.id,
            email="jane@borrower.example",
            role=ParticipantRole.BORROWER,
        )
    )
    db_session.add(
        Communication(
            loan_file_id=loan_file.id,
            direction=CommunicationDirection.OUTBOUND,
            status=CommunicationStatus.SENT,
            external_message_id="ours@mail.example",
        )
    )
    await db_session.flush()

    guesses: dict[str, Any] = {
        "company_id": company.id,
        "subject": f"Re: docs [{loan_file.display_id}]",
        "in_reply_to": "ours@mail.example",
        "references": ["ours@mail.example"],
    }
    message = await _message(db_session, envelope_recipients=[f"typo@{domain}"], **guesses)
    assert not (await route_message(db_session, message=message)).routed

    # THE POSITIVE CONTROL for the guesses: each rung, called by hand, does match this message.
    from app.services.inbound_routing import (
        _route_by_footer_tag,
        _route_by_participant,
        _route_by_subject,
        _route_by_thread,
    )

    for rung in (_route_by_thread, _route_by_footer_tag, _route_by_participant, _route_by_subject):
        outcome = await rung(db_session, message)
        assert outcome is not None and outcome.loan_file is not None
        assert outcome.loan_file.id == loan_file.id, rung.__name__


async def test_a_route_b_alias_gives_no_company(db_session: AsyncSession) -> None:
    from app.services.mailbox_connections import create_connection

    company, _domain, _files = await _company_with_domain(db_session, slug="a")
    connection = await create_connection(db_session, company_id=company.id)
    # The old Route B form; `get_ingest_address` is None since LP-1011 (no INBOX_DOMAIN).
    alias = f"co-{connection.token}@imbox.mortgageboss.ai"
    message = await _message(db_session, to_addresses=[alias], envelope_recipients=[alias])

    await apply_routing(db_session, message=message)

    assert message.company_id is None
    assert message.routing_state is InboundRoutingState.UNROUTED


# --------------------------------------------------------------------------------------------- #
# Ingest stores the envelope
# --------------------------------------------------------------------------------------------- #
async def test_ingest_stores_the_recipients_lowercased_and_trimmed(
    db_session: AsyncSession,
) -> None:
    result = await ingest_raw_message(
        db_session,
        raw=_raw(to="header@example.test"),
        raw_storage_path=None,
        receipt={"recipients": ["  LF-ABCD@Mail.Example.Test ", "", 7, "b@example.test"]},
    )
    message = await db_session.get(InboundMessage, UUID(result.message_id))
    assert message is not None
    assert message.envelope_recipients == ["lf-abcd@mail.example.test", "b@example.test"]
    assert message.to_addresses == ["header@example.test"]


# --------------------------------------------------------------------------------------------- #
# Reading raw mail from mail storage
# --------------------------------------------------------------------------------------------- #
async def _routed_attachment(
    db: AsyncSession,
) -> tuple[LoanFile, InboundMessage, InboundAttachment]:
    _co, domain, (loan_file, _b) = await _company_with_domain(db, slug="a")
    address = _address(loan_file, domain)
    result = await process_raw_message(
        db,
        raw=_raw(to=address),
        raw_storage_path=None,
        store_raw=True,
        receipt={"recipients": [address]},
    )
    message = await db.get(InboundMessage, UUID(result.message_id))
    assert message is not None
    attachment = (
        await db.execute(
            select(InboundAttachment).where(InboundAttachment.inbound_message_id == message.id)
        )
    ).scalar_one()
    return loan_file, message, attachment


async def test_stored_raw_mail_is_under_inbound_in_mail_storage(db_session: AsyncSession) -> None:
    _file, message, _attachment = await _routed_attachment(db_session)
    assert message.raw_storage_path == f"inbound/{message.id}"
    assert await get_mail_storage().read(f"inbound/{message.id}")
    # Not in the documents storage as well.
    with pytest.raises(StorageError):
        await get_storage_backend().read(f"inbound/{message.id}")


async def test_accept_and_preview_read_from_mail_storage(db_session: AsyncSession) -> None:
    from app.models.user import User, UserRole

    loan_file, _message_row, attachment = await _routed_attachment(db_session)
    user = User(
        company_id=loan_file.company_id,
        email=f"{uuid4().hex[:8]}@example.test",
        first_name="Pat",
        last_name="Processor",
        role=UserRole.PROCESSOR,
        hashed_password="x",  # pragma: allowlist secret
    )
    db_session.add(user)
    await db_session.flush()

    assert await attachment_preview(db_session, attachment=attachment)
    accepted = await accept_attachment(
        db_session, loan_file=loan_file, attachment=attachment, actor_user_id=user.id
    )
    assert accepted.document is not None
    assert accepted.document.loan_file_id == loan_file.id


async def test_an_s3_path_in_the_mail_bucket_reads_its_key(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The path SES-delivered mail has. Local mail storage stands in for the bucket; what is being
    proved is that the key is taken from the path and the bucket checked."""
    _file, message, attachment = await _routed_attachment(db_session)
    monkeypatch.setattr(settings, "mail_bucket", "the-mail-bucket")
    message.raw_storage_path = f"s3://the-mail-bucket/inbound/{message.id}"
    await db_session.flush()

    assert await _attachment_bytes(db_session, attachment=attachment) == _PDF


async def test_a_path_in_another_bucket_is_refused(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The key is real, so reading it anyway would succeed: only the bucket check refuses."""
    _file, message, attachment = await _routed_attachment(db_session)
    monkeypatch.setattr(settings, "mail_bucket", "the-mail-bucket")
    message.raw_storage_path = f"s3://the-documents-bucket/inbound/{message.id}"
    await db_session.flush()

    with pytest.raises(CannotAcceptError, match="no longer available"):
        await _attachment_bytes(db_session, attachment=attachment)
    with pytest.raises(CannotAcceptError, match="no longer available"):
        await attachment_preview(db_session, attachment=attachment)


async def test_a_missing_raw_file_is_no_longer_available_not_a_crash(
    db_session: AsyncSession,
) -> None:
    """A row from before this ticket: `inbound-raw/...`, which is not in mail storage."""
    _file, message, attachment = await _routed_attachment(db_session)
    message.raw_storage_path = f"inbound-raw/{message.id}.eml"
    await db_session.flush()

    with pytest.raises(CannotAcceptError, match="no longer available"):
        await _attachment_bytes(db_session, attachment=attachment)
    with pytest.raises(CannotAcceptError, match="no longer available"):
        await attachment_preview(db_session, attachment=attachment)


async def test_the_seed_uses_the_companys_own_domain(db_session: AsyncSession) -> None:
    """`_link_dev_mail_domain` keeps a domain already set, so a fixed `mb-mail.localhost` would have
    sent the seeded mail to a domain this company does not own, and nothing would have routed."""
    from app.scripts.seed_dev_data import _seed_inbound_mail

    company, domain, _files = await _company_with_domain(db_session, slug="seeded")
    assert domain != "mb-mail.localhost"

    await _seed_inbound_mail(db_session, company=company)

    routed = (
        (
            await db_session.execute(
                select(InboundMessage).where(InboundMessage.company_id == company.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(routed) == 2
    assert all(m.routing_state is InboundRoutingState.ROUTED for m in routed)

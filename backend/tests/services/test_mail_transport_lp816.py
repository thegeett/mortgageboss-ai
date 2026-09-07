"""LP-816 — sending as her, and the guards a transport cannot skip.

THE TICKET IS AN INTERFACE WITH NO PROVIDER, per the execution protocol's §5. So the tests are not
about sending — nothing sends. They are about the two things that have to be true before anything
does:

* **Every guard runs before a transport is reached.** `b7`'s warning going in: *"a send that bypasses
  the suppression list, the rate limit or the reviewed_by requirement because it goes out through a
  different transport is the same message with none of the checks."* Asserted by registering a
  transport that RECORDS what it was given and then checking it was given nothing, for each guard in
  turn — a test asserting the guard alone would pass on a build where the transport ran first and the
  guard refused afterwards.
* **The scope allowlist refuses a wider one.** Widening past `gmail.send` turns a scope review into a
  CASA assessment for the CUSTOMER's administrator, not for us.

`_REGISTRY` is module state, so every test that touches it restores it — a leaked registration would
make a later test's "nothing was transmitted" pass or fail for a reason it does not name.
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from app.models import Company, LoanProgram, User, UserRole
from app.models.communication import CommunicationStatus
from app.models.mailbox_connection import (
    MailboxConnectionKind,
    MailboxConnectionStatus,
)
from app.models.needs_item import NeedsItem, NeedsItemOrigin
from app.services import mail_transport
from app.services.mail_transport import (
    ALLOWED_SCOPES,
    MailTransport,
    NoTransport,
    OutboundEnvelope,
    SentResult,
    TransportError,
    register,
    transport_for,
)
from sqlalchemy.ext.asyncio import AsyncSession


class RecordingTransport(MailTransport):
    """Records what it was handed. THE POINT IS WHAT IT DOES NOT RECEIVE."""

    scopes = frozenset({"Mail.Send"})

    def __init__(self) -> None:
        self.sent: list[OutboundEnvelope] = []

    async def send(self, envelope: OutboundEnvelope) -> SentResult:
        self.sent.append(envelope)
        return SentResult(provider_message_id=f"provider-{len(self.sent)}")


@pytest.fixture
def registry_restored() -> Iterator[None]:
    """`_REGISTRY` is module state. A leaked registration makes a later test's "nothing was
    transmitted" pass or fail for a reason it does not name."""
    original = dict(mail_transport._REGISTRY)
    try:
        yield
    finally:
        mail_transport._REGISTRY.clear()
        mail_transport._REGISTRY.update(original)


async def _company_and_file(db: AsyncSession, *, slug: str):
    from app.services.loan_files import create_loan_file

    company = Company(name=slug.title(), slug=f"{slug}-{uuid4().hex[:8]}")
    db.add(company)
    await db.flush()
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    return company, loan_file


async def _actor(db: AsyncSession, company) -> User:
    user = User(
        company_id=company.id,
        email=f"p-{uuid4().hex[:8]}@example.com",
        hashed_password="x",  # pragma: allowlist secret
        first_name="Pat",
        last_name="Processor",
        role=UserRole.PROCESSOR,
    )
    db.add(user)
    await db.flush()
    return user


async def _draft(db: AsyncSession, loan_file, actor):
    from app.services.email_draft import add_needs_to_draft

    need = NeedsItem(
        loan_file_id=loan_file.id,
        title="Bank statements",
        needs_type="bank_statement",
        origin=NeedsItemOrigin.FINDING,
    )
    db.add(need)
    await db.flush()
    result = await add_needs_to_draft(db, loan_file=loan_file, needs=[need], actor_user_id=actor.id)
    return result.draft


async def _connect(db: AsyncSession, company, *, kind=MailboxConnectionKind.GRAPH):
    from app.services.mailbox_connections import create_connection

    connection = await create_connection(db, company_id=company.id)
    connection.kind = kind
    await db.flush()
    return connection


# --------------------------------------------------------------------------------------------- #
# What exists today
# --------------------------------------------------------------------------------------------- #
def test_no_provider_is_registered() -> None:
    """§5: *"build Route B (forwarding) only. Do not build Gmail API or Graph."* The emptiness is the
    ticket, and asserting it stops a half-finished provider being left registered."""
    assert mail_transport._REGISTRY == {}


async def test_a_forwarded_alias_can_never_send(
    db_session: AsyncSession, registry_restored: None
) -> None:
    """Route B forwards INBOUND mail. `phase4.md` §3 names send-as among "what forwarding cannot
    give", and a transport that tried would send from OUR domain with her name on it — which §3
    rules out explicitly: the borrower sees an unfamiliar sender on a mortgage file, the exact shape
    of the phishing they have been warned about.

    A TRANSPORT IS REGISTERED FOR THAT KIND, deliberately, and that is what makes this a test.
    Measured without it: removing the kind guard changed nothing, because the registry is empty and
    the lookup returned None anyway — the fixture could not reach the case it was named after. The
    registration is the mistake this guard exists to survive.
    """
    company, _loan_file = await _company_and_file(db_session, slug="fwd")
    register(MailboxConnectionKind.FORWARDED_ALIAS, RecordingTransport())
    connection = await _connect(db_session, company, kind=MailboxConnectionKind.FORWARDED_ALIAS)

    assert transport_for(connection) is None


async def test_a_revoked_connection_sends_nothing(
    db_session: AsyncSession, registry_restored: None
) -> None:
    company, _loan_file = await _company_and_file(db_session, slug="revoked")
    register(MailboxConnectionKind.GRAPH, RecordingTransport())
    connection = await _connect(db_session, company)
    connection.status = MailboxConnectionStatus.REVOKED
    await db_session.flush()

    assert transport_for(connection) is None


async def test_a_connected_one_with_a_provider_does_resolve(
    db_session: AsyncSession, registry_restored: None
) -> None:
    """THE CONTROL. Every "returns None" above passes against a function that returns None always —
    which is what it does today, so this is the test that says the plumbing is real."""
    company, _loan_file = await _company_and_file(db_session, slug="resolves")
    transport = RecordingTransport()
    register(MailboxConnectionKind.GRAPH, transport)
    connection = await _connect(db_session, company)

    assert transport_for(connection) is transport


def test_no_connection_is_copy_and_send() -> None:
    """None means copy-and-send, not broken. Most files have no mailbox connected."""
    assert transport_for(None) is None


async def test_the_default_transport_raises_rather_than_pretending(
    db_session: AsyncSession,
) -> None:
    """NOT A STUB THAT PRETENDS. Reporting a send that did not happen would tell a processor a
    borrower had been written to and start a reminder clock against silence nobody caused."""
    with pytest.raises(TransportError):
        await NoTransport().send(OutboundEnvelope(to="a@b.example", subject="s", body="b"))


# --------------------------------------------------------------------------------------------- #
# The scopes
# --------------------------------------------------------------------------------------------- #
def test_only_the_two_narrow_scopes_are_permitted() -> None:
    """`gmail.send` is *sensitive* — a scope review. The READ scopes are restricted and drag the
    customer into a CASA assessment, which is why inbound is forwarding and only outbound is an API.
    Graph's `Mail.Send` is delegated and needs no admin consent."""
    assert {
        "https://www.googleapis.com/auth/gmail.send",
        "Mail.Send",
    } == ALLOWED_SCOPES
    assert not any("readonly" in scope or "modify" in scope for scope in ALLOWED_SCOPES)


def test_a_wider_scope_is_refused_at_registration(registry_restored: None) -> None:
    """A scope creeping past `gmail.send` is the change that turns a scope review into a CASA
    assessment — for the customer's administrator, not for us. Refused here so it is a failing
    import rather than a support conversation six weeks in."""

    class Greedy(RecordingTransport):
        scopes = frozenset({"https://www.googleapis.com/auth/gmail.modify"})

    with pytest.raises(TransportError, match="outside the permitted scopes"):
        register(MailboxConnectionKind.GMAIL_API, Greedy())

    assert MailboxConnectionKind.GMAIL_API not in mail_transport._REGISTRY


def test_the_envelope_cannot_carry_an_attachment() -> None:
    """LP-815's rule, enforced on this path too: GLBA Safeguards 16 CFR 314.4(c)(3) means outbound
    carries an authenticated, expiring link and never a document. A transport that COULD take one is
    how that rule gets bypassed by a provider integration nobody re-read the compliance note for."""
    from dataclasses import fields

    names = {field.name for field in fields(OutboundEnvelope)}

    assert not (names & {"attachment", "attachments", "files", "parts", "documents"})


# --------------------------------------------------------------------------------------------- #
# The guards a transport cannot skip
# --------------------------------------------------------------------------------------------- #
async def test_a_suppressed_address_reaches_no_transport(
    db_session: AsyncSession, registry_restored: None
) -> None:
    """THE SHAPE THAT MATTERS. Asserting the guard refused is not enough — that passes on a build
    where the transport ran first and the guard refused afterwards, which is a message sent and then
    reported as blocked. So the transport records what it was handed, and it was handed nothing."""
    from app.models.suppressed_address import SuppressionReason
    from app.services.bounce_handling import suppress_address
    from app.services.email_send import CannotSendError, send_draft

    company, loan_file = await _company_and_file(db_session, slug="suppressed")
    actor = await _actor(db_session, company)
    draft = await _draft(db_session, loan_file, actor)
    transport = RecordingTransport()
    register(MailboxConnectionKind.GRAPH, transport)
    await _connect(db_session, company)
    await suppress_address(
        db_session,
        company_id=company.id,
        address="jane@borrower.example",
        reason=SuppressionReason.HARD_BOUNCE,
    )

    with pytest.raises(CannotSendError, match="suppressed"):
        await send_draft(
            db_session,
            loan_file=loan_file,
            draft_id=draft.id,
            recipient="jane@borrower.example",
            body="please send these",
            approver_user_id=actor.id,
        )

    assert transport.sent == []


async def test_a_rate_limited_send_reaches_no_transport(
    db_session: AsyncSession, registry_restored: None
) -> None:
    """One per address per five minutes. The limit is header-independent and it is above the
    transport, so a provider integration cannot be the way round it."""
    from app.services.email_send import CannotSendError, send_draft

    company, loan_file = await _company_and_file(db_session, slug="ratelimited")
    actor = await _actor(db_session, company)
    first = await _draft(db_session, loan_file, actor)
    transport = RecordingTransport()
    register(MailboxConnectionKind.GRAPH, transport)
    await _connect(db_session, company)

    await send_draft(
        db_session,
        loan_file=loan_file,
        draft_id=first.id,
        recipient="jane@borrower.example",
        body="first",
        approver_user_id=actor.id,
    )
    assert len(transport.sent) == 1, (
        "the first send must reach the transport, or this proves nothing"
    )

    second = await _draft(db_session, loan_file, actor)
    with pytest.raises(CannotSendError, match="minutes ago"):
        await send_draft(
            db_session,
            loan_file=loan_file,
            draft_id=second.id,
            recipient="jane@borrower.example",
            body="second",
            approver_user_id=actor.id,
        )

    assert len(transport.sent) == 1


async def test_a_transmitted_message_keeps_the_providers_id(
    db_session: AsyncSession, registry_restored: None
) -> None:
    """`external_message_id` MEANS "THIS MESSAGE'S OWN ID" (LP-818 separated it from the id a reply
    answers), and this is the first thing in the product that can fill it for outbound.

    It is what LP-805's rung 2 matches a borrower's `References` against — so their reply routes with
    CERTAIN confidence rather than falling to the footer tag, which §2.2 grades "high" and which
    Gmail and Outlook mobile routinely trim out of a quoted body.
    """
    from app.services.email_send import send_draft

    company, loan_file = await _company_and_file(db_session, slug="providerid")
    actor = await _actor(db_session, company)
    draft = await _draft(db_session, loan_file, actor)
    register(MailboxConnectionKind.GRAPH, RecordingTransport())
    await _connect(db_session, company)

    await send_draft(
        db_session,
        loan_file=loan_file,
        draft_id=draft.id,
        recipient="jane@borrower.example",
        body="please send these",
        approver_user_id=actor.id,
    )

    assert draft.external_message_id == "provider-1"


async def test_copy_and_send_records_no_provider_id(db_session: AsyncSession) -> None:
    """THE CONTROL, and the state of the product today. With no transport registered the send is
    recorded and nothing transmits — exactly as it was before this ticket."""
    from app.services.email_send import send_draft

    company, loan_file = await _company_and_file(db_session, slug="copysend")
    actor = await _actor(db_session, company)
    draft = await _draft(db_session, loan_file, actor)

    await send_draft(
        db_session,
        loan_file=loan_file,
        draft_id=draft.id,
        recipient="jane@borrower.example",
        body="please send these",
        approver_user_id=actor.id,
    )

    assert draft.external_message_id is None
    assert draft.status is CommunicationStatus.SENT


async def test_the_transport_is_handed_what_actually_went_out(
    db_session: AsyncSession, registry_restored: None
) -> None:
    """The processor's EDIT, not the composed draft — and with the footer tag, which is what LP-805's
    rung 3 matches when a client strips `Reply-To`."""
    from app.services.email_send import send_draft

    company, loan_file = await _company_and_file(db_session, slug="envelope")
    actor = await _actor(db_session, company)
    draft = await _draft(db_session, loan_file, actor)
    transport = RecordingTransport()
    register(MailboxConnectionKind.GRAPH, transport)
    await _connect(db_session, company)

    await send_draft(
        db_session,
        loan_file=loan_file,
        draft_id=draft.id,
        recipient="jane@borrower.example",
        body="I rewrote this before sending.",
        approver_user_id=actor.id,
    )

    envelope = transport.sent[0]
    assert envelope.to == "jane@borrower.example"
    assert "I rewrote this before sending." in envelope.body
    assert f"[{loan_file.display_id}]" in envelope.body
    # A HUMAN-APPROVED SEND CARRIES NO SUPPRESSION HEADERS. They ask a correspondent not to answer,
    # and a document request is the one message we most want answered.
    assert envelope.headers == {}


async def test_a_transport_failure_marks_the_message_failed(
    db_session: AsyncSession, registry_restored: None
) -> None:
    """THE RECORD IS NOT UNDONE. `record_sent` has already run, and rolling back would lose the
    evidence row and the needs transition for a message that may well have gone out — a provider
    that timed out after accepting it is the ordinary failure, not the exception."""
    from app.services.email_send import send_draft
    from app.services.evidence import evidence_for

    class Broken(RecordingTransport):
        async def send(self, envelope: OutboundEnvelope) -> SentResult:
            raise TransportError("the provider timed out")

    company, loan_file = await _company_and_file(db_session, slug="broken")
    actor = await _actor(db_session, company)
    draft = await _draft(db_session, loan_file, actor)
    register(MailboxConnectionKind.GRAPH, Broken())
    await _connect(db_session, company)

    with pytest.raises(TransportError):
        await send_draft(
            db_session,
            loan_file=loan_file,
            draft_id=draft.id,
            recipient="jane@borrower.example",
            body="please send these",
            approver_user_id=actor.id,
        )

    assert draft.status is CommunicationStatus.FAILED
    assert len(await evidence_for(db_session, loan_file=loan_file)) == 1


async def test_another_companys_connection_is_not_used(
    db_session: AsyncSession, registry_restored: None
) -> None:
    """The connection is looked up by the FILE's company. A lookup that found any connected mailbox
    would send one tenant's borrower mail out through another tenant's account."""
    from app.services.email_send import send_draft

    theirs, _their_file = await _company_and_file(db_session, slug="conn-theirs")
    mine, my_file = await _company_and_file(db_session, slug="conn-mine")
    actor = await _actor(db_session, mine)
    draft = await _draft(db_session, my_file, actor)
    transport = RecordingTransport()
    register(MailboxConnectionKind.GRAPH, transport)
    await _connect(db_session, theirs)

    await send_draft(
        db_session,
        loan_file=my_file,
        draft_id=draft.id,
        recipient="jane@borrower.example",
        body="please send these",
        approver_user_id=actor.id,
    )

    assert transport.sent == []
    assert draft.external_message_id is None

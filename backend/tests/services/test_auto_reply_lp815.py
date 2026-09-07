"""LP-815 — the one thing in Phase 4 that can generate mail by itself.

Everything else needs a processor to press something. This replies to a stranger, so almost every
test here is about a refusal, and the refusals are the deliverable.

THE HEADERS ARE NOT THE DEFENCE, and LP-811a said so when it built them: they ask a well-behaved
correspondent not to answer, and a loop forms with one that is not. So the suppression rules and the
header-independent rate limit are tested against messages that carry no cooperative headers at all.

Every case that asserts a refusal is paired with the positive control that the SAME fixture, with
only the refusing fact removed, does send. An absence assertion over a fixture that could never
reply is the shape this repo has been bitten by six times.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from app.models import Company, LoanProgram
from app.models.base import utcnow
from app.models.communication import (
    Communication,
    CommunicationDirection,
    CommunicationStatus,
)
from app.models.inbound_message import InboundMessage, InboundRoutingState
from app.models.upload_link import UploadLink
from app.services.auto_reply import (
    AUTO_REPLY_HEADERS,
    TEMPLATE_KEY,
    compose_nudge,
    record_auto_reply,
    should_auto_reply,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

BORROWER = "jane.borrower@personal-email.com"


async def _company_and_file(db: AsyncSession, *, slug: str):
    from app.services.loan_files import create_loan_file

    company = Company(name=slug.title(), slug=f"{slug}-{uuid4().hex[:8]}")
    db.add(company)
    await db.flush()
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    return company, loan_file


async def _arrived(db: AsyncSession, *, loan_file, **overrides) -> InboundMessage:
    """A routed message from a person. THE DEFAULT IS THE CASE THAT SHOULD REPLY, so every refusal
    below is one changed fact away from a send rather than a differently-built fixture."""
    message = InboundMessage(
        company_id=loan_file.company_id,
        loan_file_id=loan_file.id,
        ingest_key=f"key-{uuid4().hex[:12]}",
        from_address=overrides.pop("from_address", BORROWER),
        subject="Docs attached",
        routing_state=InboundRoutingState.ROUTED,
        auth_verdicts={},
        **overrides,
    )
    db.add(message)
    await db.flush()
    return message


# --------------------------------------------------------------------------------------------- #
# The control, first — everything below is this minus one fact
# --------------------------------------------------------------------------------------------- #
async def test_a_person_writing_to_their_own_file_gets_a_nudge(db_session: AsyncSession) -> None:
    _company, loan_file = await _company_and_file(db_session, slug="reply")
    message = await _arrived(db_session, loan_file=loan_file)

    decision = await should_auto_reply(db_session, message=message, loan_file=loan_file)

    assert decision.send is True


# --------------------------------------------------------------------------------------------- #
# The four ways an auto-reply goes wrong
# --------------------------------------------------------------------------------------------- #
async def test_a_bounce_is_never_answered(db_session: AsyncSession) -> None:
    """A DSN is a message from a mail system. Replying to one is at best noise and at worst a loop
    with a mail server, which does not get tired."""
    _company, loan_file = await _company_and_file(db_session, slug="dsn")
    message = await _arrived(db_session, loan_file=loan_file, is_dsn=True)

    decision = await should_auto_reply(db_session, message=message, loan_file=loan_file)

    assert decision.send is False
    assert "notification" in decision.reason


async def test_an_out_of_office_is_never_answered(db_session: AsyncSession) -> None:
    """The classic loop: they reply, we nudge, their assistant answers, we nudge."""
    _company, loan_file = await _company_and_file(db_session, slug="ooo")
    message = await _arrived(db_session, loan_file=loan_file, is_auto_reply=True)

    decision = await should_auto_reply(db_session, message=message, loan_file=loan_file)

    assert decision.send is False


async def test_a_mailing_list_is_never_answered(db_session: AsyncSession) -> None:
    """THE ONE NOTHING IMPLEMENTED BEFORE LP-815. `phase4.md` §5 names `Precedence: bulk|list` and
    `List-Id` alongside the RFC 3834 marker; `is_auto_reply` covered the marker and neither of the
    others, so a subscribed address would have been nudged.

    The loop a list forms is the worse one: a reply goes to the LIST, so every subscriber receives
    it and the reflector sends it back to us.
    """
    _company, loan_file = await _company_and_file(db_session, slug="list")
    message = await _arrived(db_session, loan_file=loan_file, is_bulk=True)

    decision = await should_auto_reply(db_session, message=message, loan_file=loan_file)

    assert decision.send is False
    assert "mailing list" in decision.reason


async def test_a_message_with_no_sender_is_never_answered(db_session: AsyncSession) -> None:
    """Replying to nowhere is at best wasted and at worst backscatter."""
    _company, loan_file = await _company_and_file(db_session, slug="nosender")
    message = await _arrived(db_session, loan_file=loan_file, from_address=None)

    assert (await should_auto_reply(db_session, message=message, loan_file=loan_file)).send is False


async def test_an_unrouted_message_is_never_answered(db_session: AsyncSession) -> None:
    """It belongs to nobody, so there is no company whose name would be on the reply — and a reply
    is the one thing that tells a stranger their guess at an address reached a real system."""
    _company, loan_file = await _company_and_file(db_session, slug="unrouted")
    message = await _arrived(db_session, loan_file=loan_file)
    # Made unrouted AFTER insert: `company_id` is part of the dedup identity and nullable, and
    # building it null from the start would test a different row than the one routing produces.
    message.routing_state = InboundRoutingState.UNROUTED
    message.company_id = None
    message.loan_file_id = None
    await db_session.flush()

    assert (await should_auto_reply(db_session, message=message, loan_file=loan_file)).send is False


async def test_a_message_routed_to_a_different_file_is_never_answered(
    db_session: AsyncSession,
) -> None:
    """The caller supplies both, and nothing but this proves they agree."""
    from app.services.loan_files import create_loan_file

    company, mine = await _company_and_file(db_session, slug="crossfile")
    theirs = await create_loan_file(
        db_session, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    message = await _arrived(db_session, loan_file=theirs)

    assert (await should_auto_reply(db_session, message=message, loan_file=mine)).send is False


async def test_a_suppressed_address_is_never_answered(db_session: AsyncSession) -> None:
    """LP-819 — mail to this address bounced permanently. Another automatic message produces another
    bounce, on a sending reputation shared by every borrower this system writes to."""
    from app.models.suppressed_address import SuppressionReason
    from app.services.bounce_handling import suppress_address

    company, loan_file = await _company_and_file(db_session, slug="suppressed")
    message = await _arrived(db_session, loan_file=loan_file)
    await suppress_address(
        db_session,
        company_id=company.id,
        address=BORROWER,
        reason=SuppressionReason.HARD_BOUNCE,
    )

    assert (await should_auto_reply(db_session, message=message, loan_file=loan_file)).send is False


# --------------------------------------------------------------------------------------------- #
# The header-independent loop breaker
# --------------------------------------------------------------------------------------------- #
async def _record_nudge(db: AsyncSession, *, loan_file, when=None) -> Communication:
    row = Communication(
        loan_file_id=loan_file.id,
        direction=CommunicationDirection.OUTBOUND,
        status=CommunicationStatus.QUEUED,
        recipient=BORROWER,
        template_key=TEMPLATE_KEY,
    )
    db.add(row)
    await db.flush()
    if when is not None:
        row.created_at = when
        await db.flush()
    return row


async def test_one_nudge_per_address_per_five_minutes(db_session: AsyncSession) -> None:
    """HEADER-INDEPENDENT, which is the whole point. The message below carries no cooperative
    headers at all — it is a person writing again — and the count is what stops the second reply."""
    _company, loan_file = await _company_and_file(db_session, slug="ratelimit")
    await _record_nudge(db_session, loan_file=loan_file)
    message = await _arrived(db_session, loan_file=loan_file)

    decision = await should_auto_reply(db_session, message=message, loan_file=loan_file)

    assert decision.send is False
    assert "recently" in decision.reason


async def test_the_window_expires(db_session: AsyncSession) -> None:
    """THE CONTROL FOR THE LIMIT. Without it, a rate limit that never lets anything through is green
    against the test above — and silence is the failure mode nobody reports."""
    _company, loan_file = await _company_and_file(db_session, slug="window")
    await _record_nudge(db_session, loan_file=loan_file, when=utcnow() - timedelta(hours=2))
    message = await _arrived(db_session, loan_file=loan_file)

    assert (await should_auto_reply(db_session, message=message, loan_file=loan_file)).send is True


async def test_three_a_day_is_the_ceiling(db_session: AsyncSession) -> None:
    _company, loan_file = await _company_and_file(db_session, slug="daily")
    for hours in (20, 15, 10):
        await _record_nudge(db_session, loan_file=loan_file, when=utcnow() - timedelta(hours=hours))
    message = await _arrived(db_session, loan_file=loan_file)

    assert (await should_auto_reply(db_session, message=message, loan_file=loan_file)).send is False


async def test_another_companys_nudges_do_not_silence_this_one(db_session: AsyncSession) -> None:
    """A borrower shopping two brokers is one mailbox and two companies. An unscoped count would let
    one tenant's traffic silence another's — the finding LP-811a's review established, applied here
    because this limit was written by copying that reasoning rather than that code."""
    _theirs, their_file = await _company_and_file(db_session, slug="tenant-theirs")
    _mine, my_file = await _company_and_file(db_session, slug="tenant-mine")
    await _record_nudge(db_session, loan_file=their_file)
    message = await _arrived(db_session, loan_file=my_file)

    assert (await should_auto_reply(db_session, message=message, loan_file=my_file)).send is True


async def test_a_processors_own_email_does_not_count_against_the_nudge(
    db_session: AsyncSession,
) -> None:
    """DIFFERENT THINGS AT DIFFERENT RATES. A considered document request and an automatic nudge are
    not interchangeable; counting them together would let one email suppress the nudge, or three
    nudges block the email that matters."""
    _company, loan_file = await _company_and_file(db_session, slug="notthesame")
    db_session.add(
        Communication(
            loan_file_id=loan_file.id,
            direction=CommunicationDirection.OUTBOUND,
            status=CommunicationStatus.SENT,
            recipient=BORROWER,
            template_key="document_request",
        )
    )
    await db_session.flush()
    message = await _arrived(db_session, loan_file=loan_file)

    assert (await should_auto_reply(db_session, message=message, loan_file=loan_file)).send is True


# --------------------------------------------------------------------------------------------- #
# What gets recorded
# --------------------------------------------------------------------------------------------- #
async def test_recording_mints_a_link_and_queues_the_reply(db_session: AsyncSession) -> None:
    _company, loan_file = await _company_and_file(db_session, slug="record")
    message = await _arrived(db_session, loan_file=loan_file)

    reply = await record_auto_reply(db_session, loan_file=loan_file, message=message)

    assert reply is not None
    assert reply.status is CommunicationStatus.QUEUED
    assert reply.recipient == BORROWER
    assert reply.template_key == TEMPLATE_KEY
    links = (
        (
            await db_session.execute(
                select(UploadLink).where(UploadLink.loan_file_id == loan_file.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(links) == 1
    assert links[0].recipient_email == BORROWER


async def test_a_refused_message_mints_no_link(db_session: AsyncSession) -> None:
    """THE CONTROL. A link minted for a reply that is never sent is a live capability for a mailbox
    nobody wrote to — and it would be invisible, because nothing failed."""
    _company, loan_file = await _company_and_file(db_session, slug="norecord")
    message = await _arrived(db_session, loan_file=loan_file, is_dsn=True)

    assert await record_auto_reply(db_session, loan_file=loan_file, message=message) is None
    links = (
        (
            await db_session.execute(
                select(UploadLink).where(UploadLink.loan_file_id == loan_file.id)
            )
        )
        .scalars()
        .all()
    )
    assert links == []


async def test_the_queued_reply_is_not_a_draft(db_session: AsyncSession) -> None:
    """QUEUED, NOT DRAFT, and the difference is load-bearing.

    A draft is the document request a processor reviews; there is a partial unique index enforcing
    one open draft per (file, template) and `get_open_draft` reads by that status. A nudge parked as
    a DRAFT would be a second thing on the file waiting for a person nobody ever asks.
    """
    from app.services.email_draft import get_open_draft

    _company, loan_file = await _company_and_file(db_session, slug="notdraft")
    message = await _arrived(db_session, loan_file=loan_file)

    await record_auto_reply(db_session, loan_file=loan_file, message=message)

    assert await get_open_draft(db_session, loan_file_id=loan_file.id) is None


async def test_the_reply_threads_to_what_it_answers(db_session: AsyncSession) -> None:
    """RFC 5322 §3.6.4. Without it the borrower sees an unrelated message rather than a reply."""
    _company, loan_file = await _company_and_file(db_session, slug="threaded")
    message = await _arrived(db_session, loan_file=loan_file)
    message.message_id = "abc@borrower.example.com"
    await db_session.flush()

    reply = await record_auto_reply(db_session, loan_file=loan_file, message=message)

    assert reply is not None
    assert reply.external_message_id == "abc@borrower.example.com"


# --------------------------------------------------------------------------------------------- #
# The message itself
# --------------------------------------------------------------------------------------------- #
async def test_the_nudge_carries_the_link_and_the_warning(db_session: AsyncSession) -> None:
    from app.services.upload_links import mint_upload_link

    _company, loan_file = await _company_and_file(db_session, slug="body")
    minted = await mint_upload_link(db_session, loan_file=loan_file)

    subject, body = compose_nudge(loan_file=loan_file, link=minted)

    assert minted.url in body
    assert "not a secure way" in body
    assert loan_file.display_id in subject
    assert f"[{loan_file.display_id}]" in body


async def test_the_nudge_names_nobody(db_session: AsyncSession) -> None:
    """It goes to whatever address wrote in, which after a spoof is not necessarily the borrower.

    Asserted against a file that HAS a borrower and a property, so the absence is a choice rather
    than an empty fixture.
    """
    from app.models.borrower import Borrower
    from app.models.property import Property
    from app.services.upload_links import mint_upload_link

    _company, loan_file = await _company_and_file(db_session, slug="anonymous")
    db_session.add(
        Borrower(
            loan_file_id=loan_file.id,
            first_name="Jane",
            last_name="Borrower",
            email=BORROWER,
            is_primary=True,
        )
    )
    db_session.add(Property(loan_file_id=loan_file.id, address_line="42 Maple Avenue"))
    await db_session.flush()
    minted = await mint_upload_link(db_session, loan_file=loan_file)

    _subject, body = compose_nudge(loan_file=loan_file, link=minted)

    assert "Jane" not in body
    assert "Borrower" not in body
    assert "Maple" not in body


def test_the_headers_say_auto_replied_not_auto_generated() -> None:
    """`phase4.md` §5 names these three for an auto-reply, and two differ from LP-811a's general set.

    RFC 3834 reserves `auto-replied` for a reply generated to a SPECIFIC message, which is exactly
    this, and `auto-generated` for everything else a system emits unprompted. Copying LP-811a's dict
    would have labelled this as the wrong kind of automatic mail, to the correspondents most likely
    to act on the label.
    """
    from app.services.email_send import AUTO_REPLY_SUPPRESSION_HEADERS

    assert AUTO_REPLY_HEADERS["Auto-Submitted"] == "auto-replied"
    assert AUTO_REPLY_HEADERS["Precedence"] == "auto_reply"
    assert AUTO_REPLY_HEADERS["X-Auto-Response-Suppress"] == "All"
    # The two sets are deliberately different; this fails if one is ever made an alias of the other.
    assert AUTO_REPLY_HEADERS != AUTO_REPLY_SUPPRESSION_HEADERS


def test_outbound_carries_no_attachment_field() -> None:
    """`phase4.md` §6 — "the attachment path is blocked in code, not by policy".

    GLBA Safeguards 16 CFR 314.4(c)(3) requires customer information to be encrypted in transit over
    external networks, and opportunistic STARTTLS is not a defensible compensating control on its
    own. So outbound carries the link, never the document.

    This asserts the block rather than trusting the absence: today `OutboundMessage` has no such
    field because nobody has added one, and the day somebody adds `attachments: list[bytes]` because
    a lender wants a PDF, this is what refuses.
    """
    from dataclasses import fields

    from app.services.email_send import _ATTACHMENT_FIELD_NAMES, OutboundMessage

    present = {field.name for field in fields(OutboundMessage)}
    assert not (present & _ATTACHMENT_FIELD_NAMES), (
        "outbound email must not carry a document — it carries the expiring upload link (LP-815)"
    )
    # A POSITIVE CONTROL on the detection itself. The assertion above is an absence, and would pass
    # just as happily against a name list that matches nothing.
    assert "attachments" in _ATTACHMENT_FIELD_NAMES

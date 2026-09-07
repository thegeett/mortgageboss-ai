"""LP-818 — reply, compose, and read state.

REPLY WAS BLOCKED BY THE DATA MODEL, NOT BY A MISSING BUTTON. §C.5 names the blockage: LP-809's
draft carries a needs join and LP-811's send endpoint requires a `draft_id`, so a reply to *"is page
4 really needed?"* — which has no needs behind it — could not become a draft and therefore could not
be sent.

The needs-less draft needs no column, and the first tests here are about why: the one-open-draft
index treats a NULL `template_key` as distinct, so several replies coexist and none collides with the
accumulating request. That is a claim about Postgres, so it is asserted by writing the rows rather
than by reading the index definition.
"""

from __future__ import annotations

from email import policy
from email.message import EmailMessage
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from app.models import Company, LoanProgram, User, UserRole
from app.models.base import utcnow
from app.models.communication import (
    Communication,
    CommunicationDirection,
    CommunicationStatus,
)
from app.models.inbound_message import InboundMessage
from app.services.email_reply import (
    CannotReplyError,
    create_compose_draft,
    create_reply_draft,
    mark_read,
    reply_context,
    set_important,
    unread_count,
)
from app.services.inbound_ingest import process_raw_message
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

_PDF = (Path(__file__).resolve().parents[1] / "fixtures" / "attachments" / "clean.pdf").read_bytes()


async def _company_and_file(db: AsyncSession, *, slug: str):
    from app.services.loan_files import create_loan_file

    company = Company(name=slug.title(), slug=f"{slug}-{uuid4().hex[:8]}")
    db.add(company)
    await db.flush()
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    return company, loan_file


async def _actor(db: AsyncSession, company) -> UUID:
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
    return user.id


async def _arrived(
    db: AsyncSession, loan_file, *, message_id: str, subject: str = "Question"
) -> Communication:
    """A REAL arrival through the real chain, so the Communication, the inbound message and the link
    between them are all the ones the product makes."""
    message = EmailMessage()
    message["From"] = "Jane Borrower <Jane.Borrower@Personal-Email.com>"
    message["To"] = loan_file.get_inbox_address()
    message["Subject"] = subject
    message["Message-ID"] = f"<{message_id}>"
    message.set_content("is page 4 really needed?")
    message.add_attachment(_PDF, maintype="application", subtype="pdf", filename="p.pdf")
    await process_raw_message(
        db, raw=message.as_bytes(policy=policy.default), raw_storage_path=None, store_raw=True
    )
    return (
        (
            await db.execute(
                select(Communication).where(
                    Communication.loan_file_id == loan_file.id,
                    Communication.direction == CommunicationDirection.INBOUND,
                )
            )
        )
        .scalars()
        .all()[-1]
    )


# --------------------------------------------------------------------------------------------- #
# The needs-less draft, and the index that lets it exist
# --------------------------------------------------------------------------------------------- #
async def test_a_reply_is_a_draft_with_no_needs_and_no_template(
    db_session: AsyncSession,
) -> None:
    company, loan_file = await _company_and_file(db_session, slug="reply")
    actor = await _actor(db_session, company)
    arrived = await _arrived(db_session, loan_file, message_id="q1@example.com")

    reply = await create_reply_draft(
        db_session,
        loan_file=loan_file,
        communication_id=arrived.id,
        body="No, page 4 is not needed.",
        actor_user_id=actor,
    )

    assert reply.status is CommunicationStatus.DRAFT
    assert reply.direction is CommunicationDirection.OUTBOUND
    # NULL is the truth — `Communication`'s own docstring says the column is null for anything
    # composed by hand — and it is what keeps this off the one-open-draft index.
    assert reply.template_key is None


async def test_two_replies_can_be_open_at_once(db_session: AsyncSession) -> None:
    """A CLAIM ABOUT POSTGRES, asserted by writing the rows. The one-open-draft index is
    `(loan_file_id, template_key) WHERE status = 'draft'` with no NULLS NOT DISTINCT, so every NULL
    template key is distinct — but reading an index definition is not the same as it behaving that
    way, and a processor answering two borrowers gets an IntegrityError if it does not."""
    company, loan_file = await _company_and_file(db_session, slug="two")
    actor = await _actor(db_session, company)
    first = await _arrived(db_session, loan_file, message_id="a@example.com")
    second = await _arrived(db_session, loan_file, message_id="b@example.com")

    await create_reply_draft(
        db_session, loan_file=loan_file, communication_id=first.id, body="one", actor_user_id=actor
    )
    await create_reply_draft(
        db_session, loan_file=loan_file, communication_id=second.id, body="two", actor_user_id=actor
    )

    drafts = (
        (
            await db_session.execute(
                select(Communication).where(
                    Communication.loan_file_id == loan_file.id,
                    Communication.status == CommunicationStatus.DRAFT,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(drafts) == 2


async def test_a_reply_does_not_become_the_files_document_request(
    db_session: AsyncSession,
) -> None:
    """`get_open_draft` reads by the request's template key. A reply appearing there would be picked
    up by "send the document request" and go out as one."""
    from app.services.email_draft import get_open_draft

    company, loan_file = await _company_and_file(db_session, slug="notrequest")
    actor = await _actor(db_session, company)
    arrived = await _arrived(db_session, loan_file, message_id="c@example.com")
    await create_reply_draft(
        db_session, loan_file=loan_file, communication_id=arrived.id, body="hi", actor_user_id=actor
    )

    assert await get_open_draft(db_session, loan_file_id=loan_file.id) is None


# --------------------------------------------------------------------------------------------- #
# Who it goes to, and what it threads to
# --------------------------------------------------------------------------------------------- #
async def test_the_recipient_comes_from_the_stored_message(db_session: AsyncSession) -> None:
    """NOT FROM THE COMMUNICATION, which has no sender by LP-805's deliberate choice, and not from a
    header read now. Normalised, so a borrower whose client capitalised their address is answered at
    the address the participant list would recognise."""
    company, loan_file = await _company_and_file(db_session, slug="recipient")
    actor = await _actor(db_session, company)
    arrived = await _arrived(db_session, loan_file, message_id="d@example.com")
    assert arrived.sender is None, "LP-805 writes no sender; this test is about where it IS read"

    reply = await create_reply_draft(
        db_session, loan_file=loan_file, communication_id=arrived.id, body="ok", actor_user_id=actor
    )

    assert reply.recipient == "jane.borrower@personal-email.com"


async def test_the_reply_threads_to_the_inbound_message_id(db_session: AsyncSession) -> None:
    """RFC 5322 §3.6.4. Without it the borrower sees an unrelated message rather than an answer.

    And `external_message_id` STAYS EMPTY: it means "this message's own id" and is what rung 2
    matches a borrower's `References` against. Writing the answered id there would make rung 2 match
    a thread to a row holding a borrower's id under the wrong meaning.
    """
    company, loan_file = await _company_and_file(db_session, slug="threaded")
    actor = await _actor(db_session, company)
    arrived = await _arrived(db_session, loan_file, message_id="e@example.com")

    reply = await create_reply_draft(
        db_session, loan_file=loan_file, communication_id=arrived.id, body="ok", actor_user_id=actor
    )

    assert reply.in_reply_to_message_id == "e@example.com"
    assert reply.external_message_id is None


async def test_the_subject_gains_one_re(db_session: AsyncSession) -> None:
    company, loan_file = await _company_and_file(db_session, slug="subject")
    actor = await _actor(db_session, company)
    arrived = await _arrived(db_session, loan_file, message_id="f@example.com", subject="RE: Docs")

    reply = await create_reply_draft(
        db_session, loan_file=loan_file, communication_id=arrived.id, body="ok", actor_user_id=actor
    )

    # NOT `Re: RE: Docs`. A subject that grows a prefix per exchange is the visible sign of a thread
    # nobody is managing.
    assert reply.subject == "RE: Docs"


# --------------------------------------------------------------------------------------------- #
# Refusals
# --------------------------------------------------------------------------------------------- #
async def test_another_files_message_cannot_be_replied_to(db_session: AsyncSession) -> None:
    """A REAL message on a real other company's file. The route proves the caller owns the FILE; the
    message id is a path parameter anybody can type."""
    _theirs, their_file = await _company_and_file(db_session, slug="reply-theirs")
    mine, my_file = await _company_and_file(db_session, slug="reply-mine")
    actor = await _actor(db_session, mine)
    arrived = await _arrived(db_session, their_file, message_id="g@example.com")

    with pytest.raises(CannotReplyError, match="No such message"):
        await create_reply_draft(
            db_session,
            loan_file=my_file,
            communication_id=arrived.id,
            body="hello",
            actor_user_id=actor,
        )


async def test_the_refusal_is_the_same_for_a_message_that_never_existed(
    db_session: AsyncSession,
) -> None:
    """Telling them apart would confirm the id exists — an oracle over another tenant's rows."""
    _theirs, their_file = await _company_and_file(db_session, slug="oracle-theirs")
    mine, my_file = await _company_and_file(db_session, slug="oracle-mine")
    actor = await _actor(db_session, mine)
    arrived = await _arrived(db_session, their_file, message_id="h@example.com")

    messages = []
    for target in (arrived.id, uuid4()):
        with pytest.raises(CannotReplyError) as caught:
            await create_reply_draft(
                db_session,
                loan_file=my_file,
                communication_id=target,
                body="x",
                actor_user_id=actor,
            )
        messages.append(str(caught.value))

    assert messages[0] == messages[1]


async def test_an_outbound_message_cannot_be_replied_to(db_session: AsyncSession) -> None:
    """Replying to our own message would address it to whoever we sent it to, thread it into their
    conversation, and read to them as us answering ourselves."""
    company, loan_file = await _company_and_file(db_session, slug="outbound")
    actor = await _actor(db_session, company)
    sent = Communication(
        loan_file_id=loan_file.id,
        direction=CommunicationDirection.OUTBOUND,
        status=CommunicationStatus.SENT,
        recipient="jane@borrower.example",
    )
    db_session.add(sent)
    await db_session.flush()

    with pytest.raises(CannotReplyError, match="arrived"):
        await create_reply_draft(
            db_session,
            loan_file=loan_file,
            communication_id=sent.id,
            body="x",
            actor_user_id=actor,
        )


async def test_a_message_with_no_sender_cannot_be_replied_to(db_session: AsyncSession) -> None:
    """Replying to nowhere is at best wasted and at worst backscatter — LP-815's rule, here too."""
    company, loan_file = await _company_and_file(db_session, slug="nosender")
    actor = await _actor(db_session, company)
    arrived = await _arrived(db_session, loan_file, message_id="i@example.com")
    inbound = await db_session.get(InboundMessage, arrived.inbound_message_id)
    assert inbound is not None
    inbound.from_address = None
    await db_session.flush()

    with pytest.raises(CannotReplyError, match="no address"):
        await create_reply_draft(
            db_session,
            loan_file=loan_file,
            communication_id=arrived.id,
            body="x",
            actor_user_id=actor,
        )


async def test_an_empty_reply_is_refused(db_session: AsyncSession) -> None:
    company, loan_file = await _company_and_file(db_session, slug="empty")
    actor = await _actor(db_session, company)
    arrived = await _arrived(db_session, loan_file, message_id="j@example.com")

    with pytest.raises(CannotReplyError):
        await create_reply_draft(
            db_session,
            loan_file=loan_file,
            communication_id=arrived.id,
            body="   ",
            actor_user_id=actor,
        )


# --------------------------------------------------------------------------------------------- #
# Compose
# --------------------------------------------------------------------------------------------- #
async def test_a_composed_message_needs_a_subject(db_session: AsyncSession) -> None:
    """REFUSED RATHER THAN DEFAULTED. A subject a system invented is one a borrower cannot
    recognise, and the request path never has this problem because its template supplies one."""
    company, loan_file = await _company_and_file(db_session, slug="nosubject")
    actor = await _actor(db_session, company)

    with pytest.raises(CannotReplyError, match="subject"):
        await create_compose_draft(
            db_session,
            loan_file=loan_file,
            recipient="jane@borrower.example",
            subject="  ",
            body="hello",
            actor_user_id=actor,
        )


async def test_a_composed_message_is_a_needs_less_draft(db_session: AsyncSession) -> None:
    company, loan_file = await _company_and_file(db_session, slug="composed")
    actor = await _actor(db_session, company)

    draft = await create_compose_draft(
        db_session,
        loan_file=loan_file,
        recipient="Jane@Borrower.Example",
        subject="Your file went to underwriting",
        body="Just so you know.",
        actor_user_id=actor,
    )

    assert draft.template_key is None
    assert draft.in_reply_to_message_id is None
    assert draft.recipient == "jane@borrower.example"


# --------------------------------------------------------------------------------------------- #
# Important, and read state
# --------------------------------------------------------------------------------------------- #
async def test_important_is_a_toggle(db_session: AsyncSession) -> None:
    _company, loan_file = await _company_and_file(db_session, slug="flag")
    arrived = await _arrived(db_session, loan_file, message_id="k@example.com")
    assert arrived.is_important is False

    await set_important(
        db_session, loan_file=loan_file, communication_id=arrived.id, important=True
    )
    assert arrived.is_important is True

    await set_important(
        db_session, loan_file=loan_file, communication_id=arrived.id, important=False
    )
    assert arrived.is_important is False


async def test_reading_is_reversible(db_session: AsyncSession) -> None:
    """A processor who opens something at the end of the day and cannot deal with it needs to put it
    back. A one-way flag makes the badge a thing to get rid of rather than a thing to act on."""
    _company, loan_file = await _company_and_file(db_session, slug="read")
    arrived = await _arrived(db_session, loan_file, message_id="l@example.com")

    await mark_read(db_session, loan_file=loan_file, communication_id=arrived.id, read=True)
    assert arrived.read_at is not None

    await mark_read(db_session, loan_file=loan_file, communication_id=arrived.id, read=False)
    assert arrived.read_at is None


async def test_an_outbound_message_cannot_be_marked_read(db_session: AsyncSession) -> None:
    """We wrote it, so "unread" is not a state it can be in. Refused rather than ignored: a caller
    doing this is confused about something, and a silent success hides it."""
    _company, loan_file = await _company_and_file(db_session, slug="readout")
    sent = Communication(
        loan_file_id=loan_file.id,
        direction=CommunicationDirection.OUTBOUND,
        status=CommunicationStatus.SENT,
    )
    db_session.add(sent)
    await db_session.flush()

    with pytest.raises(CannotReplyError, match="arrived"):
        await mark_read(db_session, loan_file=loan_file, communication_id=sent.id)


async def test_the_badge_counts_only_unread_inbound(db_session: AsyncSession) -> None:
    _company, loan_file = await _company_and_file(db_session, slug="badge")
    first = await _arrived(db_session, loan_file, message_id="m@example.com")
    await _arrived(db_session, loan_file, message_id="n@example.com")
    db_session.add(
        Communication(
            loan_file_id=loan_file.id,
            direction=CommunicationDirection.OUTBOUND,
            status=CommunicationStatus.SENT,
        )
    )
    await db_session.flush()

    assert await unread_count(db_session, loan_file=loan_file) == 2

    await mark_read(db_session, loan_file=loan_file, communication_id=first.id)

    assert await unread_count(db_session, loan_file=loan_file) == 1


async def test_the_badge_does_not_count_another_files_mail(db_session: AsyncSession) -> None:
    """SAME COMPANY, TWO FILES. A company-scoped count would pass every cross-tenant test while
    telling a processor one borrower has mail because another one does."""
    from app.services.loan_files import create_loan_file

    company, mine = await _company_and_file(db_session, slug="badge-scope")
    theirs = await create_loan_file(
        db_session, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    await _arrived(db_session, theirs, message_id="o@example.com")

    assert await unread_count(db_session, loan_file=mine) == 0
    assert await unread_count(db_session, loan_file=theirs) == 1


async def test_reply_context_says_who_and_what_before_anything_is_typed(
    db_session: AsyncSession,
) -> None:
    _company, loan_file = await _company_and_file(db_session, slug="context")
    arrived = await _arrived(db_session, loan_file, message_id="p@example.com", subject="Docs")

    context = await reply_context(db_session, loan_file=loan_file, communication_id=arrived.id)

    assert context.recipient == "jane.borrower@personal-email.com"
    assert context.subject == "Re: Docs"
    assert context.in_reply_to_message_id == "p@example.com"


# --------------------------------------------------------------------------------------------- #
# The migration, RUN in both directions (review finding)
# --------------------------------------------------------------------------------------------- #
def _migration_sql() -> tuple[str, str]:
    """The upgrade's backfill and the downgrade's restore, imported so a test can execute them.

    `_BACKFILL_NUDGE_REPLY_TO` was hoisted for exactly this and nothing was using it — the
    hook-with-no-consumer shape, one size down. LP-812's review established the pattern after
    running a backfill and finding two bugs in it.
    """
    from importlib.util import module_from_spec, spec_from_file_location

    root = Path(__file__).resolve().parents[1].parent / "alembic" / "versions"
    (path,) = [p for p in root.glob("*.py") if "d81b6e4c25f7" in p.name]  # pragma: allowlist secret
    spec = spec_from_file_location("_mig_lp818", path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    down = """
        UPDATE communications
        SET external_message_id = in_reply_to_message_id
        WHERE template_key = 'borrower_secure_upload_nudge'
          AND in_reply_to_message_id IS NOT NULL
          AND external_message_id IS NULL
    """
    return str(module._BACKFILL_NUDGE_REPLY_TO), down


async def _nudge(db: AsyncSession, loan_file, message_id: str) -> Communication:
    row = Communication(
        loan_file_id=loan_file.id,
        direction=CommunicationDirection.OUTBOUND,
        status=CommunicationStatus.SENT,
        template_key="borrower_secure_upload_nudge",
        external_message_id=message_id,
    )
    db.add(row)
    await db.flush()
    return row


async def test_the_nudge_id_round_trips_through_upgrade_and_downgrade(
    db_session: AsyncSession,
) -> None:
    """The separated meaning must be restorable, because the downgrade drops the column it lives in.

    Rung 2 matches `external_message_id`, so an id that does not come back is routing input this
    migration destroyed.
    """
    up, down = _migration_sql()
    _company, loan_file = await _company_and_file(db_session, slug=f"rt{uuid4().hex[:6]}")
    nudge = await _nudge(db_session, loan_file, "<nudge@example.com>")

    await db_session.execute(text(up))
    await db_session.refresh(nudge)
    assert nudge.external_message_id is None
    assert nudge.in_reply_to_message_id == "<nudge@example.com>"

    await db_session.execute(text(down))
    await db_session.refresh(nudge)
    assert nudge.external_message_id == "<nudge@example.com>"


async def test_a_row_soft_deleted_between_the_two_still_comes_back(
    db_session: AsyncSession,
) -> None:
    """Measured before the fix: it did not.

    The downgrade filtered `deleted_at IS NULL`, mirroring the upgrade — but the two statements do
    different jobs. The upgrade CHOOSES what to migrate; the downgrade RESTORES a column the next
    statement drops, so anything it skips is destroyed rather than left where it was.

    It matters because rung 2 (`inbound_routing._route_by_thread`) matches `external_message_id`
    with no `only_active`: a soft-deleted outbound message is still routing input, which is
    defensible — deleting our record does not unsend the message a borrower is replying to — but it
    means these ids are live data rather than tombstones.
    """
    up, down = _migration_sql()
    _company, loan_file = await _company_and_file(db_session, slug=f"sd{uuid4().hex[:6]}")
    nudge = await _nudge(db_session, loan_file, "<deleted-later@example.com>")

    await db_session.execute(text(up))
    await db_session.refresh(nudge)
    assert nudge.in_reply_to_message_id == "<deleted-later@example.com>"

    nudge.deleted_at = utcnow()
    await db_session.flush()

    await db_session.execute(text(down))
    await db_session.refresh(nudge)
    assert nudge.external_message_id == "<deleted-later@example.com>"


async def test_the_upgrade_leaves_a_soft_deleted_row_where_it_is(db_session: AsyncSession) -> None:
    """The control for the asymmetry, so the two filters are not "fixed" into agreement.

    The upgrade's `deleted_at IS NULL` is correct: it declines to migrate a deleted row, which
    leaves the id in `external_message_id` where it already was. Removing that filter would be a
    different change, not a symmetry.
    """
    up, _down = _migration_sql()
    _company, loan_file = await _company_and_file(db_session, slug=f"al{uuid4().hex[:6]}")
    nudge = await _nudge(db_session, loan_file, "<already-gone@example.com>")
    nudge.deleted_at = utcnow()
    await db_session.flush()

    await db_session.execute(text(up))
    await db_session.refresh(nudge)

    assert nudge.external_message_id == "<already-gone@example.com>"
    assert nudge.in_reply_to_message_id is None

"""LP-807 — the ingest chain, and proof that it now runs.

THE CHAIN HAD NO CALLER. `apply_safety_to_message` (LP-804b) and `apply_routing` (LP-805) were built,
tested and exported, and nothing outside their own test modules ever invoked them: the Celery task
and the dev injector both called `ingest_raw_message` and stopped. Every message in the system would
have sat at `routing_state=PENDING` with every attachment at `safety_state=PENDING` forever — never
routed to a file, never assessable, and never acceptable, since `accept_attachment` requires SAFE.

Both service suites were green throughout, because each called its own function directly.

So the first test here is a POSITIVE CONTROL and the second is its negative twin. The positive one
would pass just as happily if the chain ran twice; the negative one is what makes it mean something,
by showing what the same message looks like when only the row-writer runs. Neither is worth anything
alone.
"""

from __future__ import annotations

from email import policy
from email.message import EmailMessage
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from app.models import Company, LoanProgram
from app.models.inbound_attachment import AttachmentSafetyState, InboundAttachment
from app.models.inbound_message import InboundMessage, InboundRoutingState
from app.services.inbound_ingest import (
    INBOUND_RAW_PREFIX,
    ingest_raw_message,
    process_raw_message,
    raw_storage_path_for,
)
from app.services.inbound_triage import (
    CannotAcceptError,
    accept_attachment,
    attachment_preview,
    list_file_messages,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "attachments"
_PDF = (_FIXTURES / "clean.pdf").read_bytes()
_HEIC = (_FIXTURES / "photo.heic").read_bytes()
_ZIP_AS_PDF = (_FIXTURES / "zip_named_as.pdf").read_bytes()

#: The eight bytes every PNG starts with. Asserted rather than "the response was not empty", because
#: an endpoint that returns the ORIGINAL bytes under `image/png` also returns something not empty.
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


async def _company_and_file(db: AsyncSession, *, slug: str):
    from app.services.loan_files import create_loan_file

    company = Company(name=slug.title(), slug=f"{slug}-{uuid4().hex[:8]}")
    db.add(company)
    await db.flush()
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    return company, loan_file


async def _processor(db: AsyncSession, company) -> UUID:
    """A REAL user row. `activity_logs.actor_user_id` is a foreign key, so a bare uuid4() fails at
    flush and the failure reads like a bug in whatever was being tested."""
    from app.models import User, UserRole

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


def _message_to(
    address: str, *, message_id: str, content: bytes = _PDF, filename: str = "statement.pdf"
) -> bytes:
    message = EmailMessage()
    message["From"] = "akash@example.com"
    message["To"] = address
    message["Subject"] = "statements"
    message["Message-ID"] = f"<{message_id}>"
    message.set_content("attached")
    subtype = filename.rsplit(".", 1)[-1]
    message.add_attachment(content, maintype="application", subtype=subtype, filename=filename)
    return message.as_bytes(policy=policy.default)


async def _one_attachment(db: AsyncSession, message_id: UUID) -> InboundAttachment:
    return (
        await db.execute(
            select(InboundAttachment).where(InboundAttachment.inbound_message_id == message_id)
        )
    ).scalar_one()


# --------------------------------------------------------------------------------------------- #
# The chain runs — and the control that makes saying so mean something
# --------------------------------------------------------------------------------------------- #
async def test_the_chain_assesses_and_routes_what_it_ingests(db_session: AsyncSession) -> None:
    """One call, and the message comes out routed to a real file with a SAFE attachment."""
    _company, loan_file = await _company_and_file(db_session, slug="acme")
    raw = _message_to(loan_file.get_inbox_address(), message_id="chain-1@example.com")

    result = await process_raw_message(
        db_session, raw=raw, raw_storage_path=None, store_raw=True, receipt=None
    )

    message = await db_session.get(InboundMessage, UUID(result.message_id))
    assert message is not None
    assert message.routing_state is InboundRoutingState.ROUTED
    assert message.loan_file_id == loan_file.id
    assert message.company_id == loan_file.company_id
    assert message.routing_confidence == 1.0
    assert (
        await _one_attachment(db_session, message.id)
    ).safety_state is AttachmentSafetyState.SAFE


async def test_ingest_alone_leaves_the_message_pending_and_unrouted(
    db_session: AsyncSession,
) -> None:
    """THE CONTROL. The same message, through the row-writer only, reaches neither state.

    Without this the test above is a check that would pass whether or not the wiring existed —
    it would only be asserting that SOMETHING got the message here, and the fixture is the something.
    This pins the difference: PENDING and PENDING is exactly the state every message in the system
    was in before LP-807, from a call that looks like a complete ingest.
    """
    _company, loan_file = await _company_and_file(db_session, slug="control")
    raw = _message_to(loan_file.get_inbox_address(), message_id="control-1@example.com")

    result = await ingest_raw_message(db_session, raw=raw, raw_storage_path=None)

    message = await db_session.get(InboundMessage, UUID(result.message_id))
    assert message is not None
    assert message.routing_state is InboundRoutingState.PENDING
    assert message.loan_file_id is None
    assert message.company_id is None
    attachment = await _one_attachment(db_session, message.id)
    assert attachment.safety_state is AttachmentSafetyState.PENDING


async def test_an_unroutable_message_is_still_assessed(db_session: AsyncSession) -> None:
    """Routing failing must not skip safety. They are separate steps and only one of them applies.

    A message nobody claims is exactly the one a processor most needs a safety verdict on before
    deciding whether it is worth claiming.
    """
    raw = _message_to("nobody@example.com", message_id="orphan-1@example.com")

    result = await process_raw_message(db_session, raw=raw, raw_storage_path=None, store_raw=True)

    message = await db_session.get(InboundMessage, UUID(result.message_id))
    assert message is not None
    assert message.routing_state is InboundRoutingState.UNROUTED
    assert message.company_id is None
    assert (
        await _one_attachment(db_session, message.id)
    ).safety_state is AttachmentSafetyState.SAFE


async def test_a_quarantined_attachment_still_routes_its_message(db_session: AsyncSession) -> None:
    """A bad attachment is not a bad message. The message routes; the attachment is refused."""
    _company, loan_file = await _company_and_file(db_session, slug="quar")
    raw = _message_to(
        loan_file.get_inbox_address(), message_id="quar-1@example.com", content=_ZIP_AS_PDF
    )

    result = await process_raw_message(db_session, raw=raw, raw_storage_path=None, store_raw=True)

    message = await db_session.get(InboundMessage, UUID(result.message_id))
    assert message is not None
    assert message.routing_state is InboundRoutingState.ROUTED
    attachment = await _one_attachment(db_session, message.id)
    assert attachment.safety_state is AttachmentSafetyState.QUARANTINED
    assert attachment.safety_reason


# --------------------------------------------------------------------------------------------- #
# Storing the raw message, without which everything downstream refuses
# --------------------------------------------------------------------------------------------- #
async def test_store_raw_writes_bytes_that_read_back_identical(db_session: AsyncSession) -> None:
    from app.storage import get_storage_backend

    _company, loan_file = await _company_and_file(db_session, slug="stored")
    raw = _message_to(loan_file.get_inbox_address(), message_id="stored-1@example.com")

    result = await process_raw_message(db_session, raw=raw, raw_storage_path=None, store_raw=True)

    message = await db_session.get(InboundMessage, UUID(result.message_id))
    assert message is not None
    assert message.raw_storage_path == raw_storage_path_for(result.message_id)
    assert message.raw_storage_path.startswith(f"{INBOUND_RAW_PREFIX}/")
    # THE BYTES, not the path. A path recorded to an object that is not there is the failure this
    # column was NULL to avoid, and it looks identical until something reads it.
    assert await get_storage_backend().read(message.raw_storage_path) == raw


async def test_without_store_raw_the_path_is_whatever_the_caller_passed(
    db_session: AsyncSession,
) -> None:
    """SES's own bucket already holds the object; the task passes its key and stores nothing."""
    _company, loan_file = await _company_and_file(db_session, slug="ses")
    raw = _message_to(loan_file.get_inbox_address(), message_id="ses-1@example.com")

    result = await process_raw_message(
        db_session, raw=raw, raw_storage_path="s3://inbound/abc", store_raw=False
    )

    message = await db_session.get(InboundMessage, UUID(result.message_id))
    assert message is not None
    assert message.raw_storage_path == "s3://inbound/abc"


async def test_an_injected_message_can_actually_be_accepted(db_session: AsyncSession) -> None:
    """The end of the chain. Ingest → assess → route → accept, with nothing hand-set in between.

    This is what `raw_storage_path=None` broke: accept re-derives the bytes from the stored message
    and refuses when there is none, so every locally injected message was listable and unopenable.
    """
    company, loan_file = await _company_and_file(db_session, slug="whole")
    actor = await _processor(db_session, company)
    raw = _message_to(loan_file.get_inbox_address(), message_id="whole-1@example.com")
    result = await process_raw_message(db_session, raw=raw, raw_storage_path=None, store_raw=True)
    message = await db_session.get(InboundMessage, UUID(result.message_id))
    assert message is not None
    attachment = await _one_attachment(db_session, message.id)

    accepted = await accept_attachment(
        db_session, loan_file=loan_file, attachment=attachment, actor_user_id=actor
    )

    assert accepted.document is not None
    assert accepted.document.loan_file_id == loan_file.id


async def test_a_redelivery_does_not_reassess_or_reroute(db_session: AsyncSession) -> None:
    """A message a processor has already acted on must not have its verdicts recomputed under them."""
    _company, loan_file = await _company_and_file(db_session, slug="dup")
    raw = _message_to(loan_file.get_inbox_address(), message_id="dup-1@example.com")
    first = await process_raw_message(
        db_session, raw=raw, raw_storage_path=None, store_raw=True, ses_message_id="ses-dup"
    )
    message = await db_session.get(InboundMessage, UUID(first.message_id))
    assert message is not None
    attachment = await _one_attachment(db_session, message.id)
    attachment.safety_state = AttachmentSafetyState.QUARANTINED
    attachment.safety_reason = "a person decided this"
    await db_session.flush()

    second = await process_raw_message(
        db_session, raw=raw, raw_storage_path=None, store_raw=True, ses_message_id="ses-dup"
    )

    assert second.created is False
    assert second.message_id == first.message_id
    await db_session.refresh(attachment)
    assert attachment.safety_state is AttachmentSafetyState.QUARANTINED
    assert attachment.safety_reason == "a person decided this"


# --------------------------------------------------------------------------------------------- #
# What one file's tab reads
# --------------------------------------------------------------------------------------------- #
async def test_a_files_messages_exclude_a_sibling_files(db_session: AsyncSession) -> None:
    """SAME COMPANY, TWO FILES. The scoping axis here is the file, not the tenant.

    A company-scoped query looks correct and passes every cross-tenant test while showing one
    borrower's mail on another borrower's file — inside one processing company, which is where a
    processor would actually see it.
    """
    from app.services.loan_files import create_loan_file

    company, mine = await _company_and_file(db_session, slug="sib")
    theirs = await create_loan_file(
        db_session, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    await process_raw_message(
        db_session,
        raw=_message_to(mine.get_inbox_address(), message_id="sib-mine@example.com"),
        raw_storage_path=None,
        store_raw=True,
    )
    await process_raw_message(
        db_session,
        raw=_message_to(theirs.get_inbox_address(), message_id="sib-theirs@example.com"),
        raw_storage_path=None,
        store_raw=True,
    )

    mine_messages = await list_file_messages(db_session, loan_file=mine)
    theirs_messages = await list_file_messages(db_session, loan_file=theirs)

    assert [m.loan_file_id for m in mine_messages] == [mine.id]
    assert [m.loan_file_id for m in theirs_messages] == [theirs.id]


# --------------------------------------------------------------------------------------------- #
# The preview, which is the one thing on this path that renders a stranger's file
# --------------------------------------------------------------------------------------------- #
async def _attachment_for(db: AsyncSession, *, slug: str, content: bytes, filename: str):
    _company, loan_file = await _company_and_file(db, slug=slug)
    raw = _message_to(
        loan_file.get_inbox_address(),
        message_id=f"{slug}-p@example.com",
        content=content,
        filename=filename,
    )
    result = await process_raw_message(db, raw=raw, raw_storage_path=None, store_raw=True)
    message = await db.get(InboundMessage, UUID(result.message_id))
    assert message is not None
    return loan_file, await _one_attachment(db, message.id)


async def test_a_safe_pdf_previews_as_a_png_we_rendered(db_session: AsyncSession) -> None:
    """The body is a PNG, not the PDF and not the sender's bytes under a hopeful content type."""
    _file, attachment = await _attachment_for(
        db_session, slug="prev", content=_PDF, filename="statement.pdf"
    )

    png = await attachment_preview(db_session, attachment=attachment)

    assert png is not None
    assert png.startswith(_PNG_MAGIC)
    assert not png.startswith(b"%PDF")


async def test_a_quarantined_attachment_has_no_preview(db_session: AsyncSession) -> None:
    """§2.3: a refused message is "never rendered". Quarantine is a reason NOT to open something."""
    _file, attachment = await _attachment_for(
        db_session, slug="prevq", content=_ZIP_AS_PDF, filename="statement.pdf"
    )
    assert attachment.safety_state is AttachmentSafetyState.QUARANTINED, (
        "the fixture must actually be quarantined or this test refuses nothing"
    )

    with pytest.raises(CannotAcceptError):
        await attachment_preview(db_session, attachment=attachment)


@pytest.mark.parametrize(
    "state",
    [AttachmentSafetyState.PENDING, AttachmentSafetyState.UNSUPPORTED],
    ids=["pending", "unsupported"],
)
async def test_only_a_safe_attachment_is_rendered(
    db_session: AsyncSession, state: AttachmentSafetyState
) -> None:
    """NOT-QUARANTINED IS NOT SAFE. The gate is `is not SAFE`, and both other states must refuse.

    PENDING because the malware scan is asynchronous, so "we have not looked yet" genuinely
    persists. UNSUPPORTED because that is what LP-804b marks the attachment on a BOUNCE — the
    borrower's own message coming back — and rendering it would show a processor their own request
    as though the borrower had sent it.

    THE BYTES ARE PRESENT AND READABLE, which is the point of building this through the full
    pipeline and then flipping the state. The first version of this test built the attachment with
    `ingest_raw_message` alone, so `raw_storage_path` was NULL and the refusal came from "the
    original message is no longer available" — a mutation that let PENDING through passed it
    unchanged, because the test was never reaching the gate it names.
    """
    _file, attachment = await _attachment_for(
        db_session, slug=f"prev{state.value[:4]}", content=_PDF, filename="statement.pdf"
    )
    assert attachment.safety_state is AttachmentSafetyState.SAFE
    assert await attachment_preview(db_session, attachment=attachment) is not None, (
        "the bytes must be renderable BEFORE the flip, or the refusal below could be about them"
    )
    attachment.safety_state = state
    attachment.safety_reason = None
    await db_session.flush()

    with pytest.raises(CannotAcceptError, match="not been confirmed safe"):
        await attachment_preview(db_session, attachment=attachment)


async def test_a_safe_file_the_renderer_cannot_open_returns_none_rather_than_raising(
    db_session: AsyncSession,
) -> None:
    """A HEIC is a real document a borrower's iPhone sent. It is SAFE and it has no thumbnail.

    None and a refusal are different answers and the card shows different things for them: "we will
    not open this" versus "there is nothing to show, accept it to view it". Collapsing them would
    put a safety warning on an ordinary photo.
    """
    _file, attachment = await _attachment_for(
        db_session, slug="prevh", content=_HEIC, filename="photo.heic"
    )
    assert attachment.safety_state is AttachmentSafetyState.SAFE, (
        "a HEIC must reach SAFE or this test is about a refusal, not an unrenderable file"
    )

    assert await attachment_preview(db_session, attachment=attachment) is None


# --------------------------------------------------------------------------------------------- #
# The seed (§H3) — a queue the running system could have produced
# --------------------------------------------------------------------------------------------- #
async def test_the_seed_produces_all_three_shapes(db_session: AsyncSession) -> None:
    """RUN, not read. The seed exists so the frontend is not blocked, and a seed that produces two
    of its three shapes blocks it just as effectively while looking finished.

    It goes through `process_raw_message`, so these states are the pipeline's own verdicts rather
    than values the seed asserted about itself.
    """
    from app.scripts.seed_dev_data import _seed_inbound_mail
    from app.services.loan_files import create_loan_file

    company = Company(name="Seeded", slug=f"seeded-{uuid4().hex[:8]}")
    db_session.add(company)
    await db_session.flush()
    await create_loan_file(db_session, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL)

    created = await _seed_inbound_mail(db_session, company=company)

    assert created == 3
    messages = (await db_session.execute(select(InboundMessage))).scalars().all()
    states = {message.routing_state for message in messages}
    assert InboundRoutingState.ROUTED in states
    assert InboundRoutingState.UNROUTED in states
    safety = set()
    for message in messages:
        rows = (
            (
                await db_session.execute(
                    select(InboundAttachment).where(
                        InboundAttachment.inbound_message_id == message.id
                    )
                )
            )
            .scalars()
            .all()
        )
        safety.update(row.safety_state for row in rows)
    assert AttachmentSafetyState.SAFE in safety
    assert AttachmentSafetyState.QUARANTINED in safety


async def test_seeding_twice_adds_nothing(db_session: AsyncSession) -> None:
    """A developer re-running the seed must not get a second copy of every message."""
    from app.scripts.seed_dev_data import _seed_inbound_mail
    from app.services.loan_files import create_loan_file

    company = Company(name="Twice", slug=f"twice-{uuid4().hex[:8]}")
    db_session.add(company)
    await db_session.flush()
    await create_loan_file(db_session, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL)

    assert await _seed_inbound_mail(db_session, company=company) == 3
    assert await _seed_inbound_mail(db_session, company=company) == 0


async def test_the_reset_keys_are_the_keys_the_seed_writes(db_session: AsyncSession) -> None:
    """`_clear_seed` deletes by ingest key and the seeder writes by message id, and with no SES id
    those ARE the same string (`compute_ingest_key`).

    The unrouted message has no company and no loan file, so nothing cascades it — if these two
    lists ever drift, `--reset` leaves it behind, the idempotent re-seed skips it, and the developer
    who reset to get the queue back is missing the one message the queue exists to demonstrate.
    """
    from app.scripts.seed_dev_data import _SEEDED_INGEST_KEYS, _seed_inbound_mail
    from app.services.loan_files import create_loan_file

    company = Company(name="Reset", slug=f"reset-{uuid4().hex[:8]}")
    db_session.add(company)
    await db_session.flush()
    await create_loan_file(db_session, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL)
    await _seed_inbound_mail(db_session, company=company)

    written = {
        message.ingest_key
        for message in (await db_session.execute(select(InboundMessage))).scalars().all()
    }

    assert written == set(_SEEDED_INGEST_KEYS)

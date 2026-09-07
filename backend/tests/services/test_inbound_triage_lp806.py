"""LP-806 — accepting an attachment onto a loan file, which is the dangerous operation in Phase 4.

Everything before this OBSERVES. This one WRITES: it puts a stranger's file onto a borrower's loan as
a document a human will later rely on.

`b7`'s warning going in was the right one, and it is the general rule the last four tickets have been
teaching: **a fixture that cannot reach the dangerous case looks exactly like a system that refuses
it.** So the cross-file tests here build TWO companies, TWO files and TWO messages, and the attachment
being accepted into the wrong file is a real row that really exists — not an id that resolves to
nothing.
"""

from __future__ import annotations

from email import policy
from email.message import EmailMessage
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from app.models import Company, LoanProgram
from app.models.document import Document, UploadSource
from app.models.inbound_attachment import (
    AttachmentDisposition,
    AttachmentSafetyState,
    InboundAttachment,
)
from app.models.inbound_message import InboundMessage, InboundRoutingState
from app.services.attachment_safety import apply_safety_to_message
from app.services.inbound_ingest import ingest_raw_message
from app.services.inbound_triage import (
    AcceptAs,
    CannotAcceptError,
    accept_attachment,
    list_triage_queue,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

_PDF = (Path(__file__).resolve().parents[1] / "fixtures" / "attachments" / "clean.pdf").read_bytes()


def _message_bytes(*, message_id: str, filename: str = "statement.pdf") -> bytes:
    message = EmailMessage()
    message["From"] = "akash@example.com"
    message["To"] = "lf-abc@inbox.example.com"
    message["Subject"] = "statements"
    message["Message-ID"] = f"<{message_id}>"
    message.set_content("attached")
    message.add_attachment(_PDF, maintype="application", subtype="pdf", filename=filename)
    return message.as_bytes(policy=policy.default)


async def _company_user_file(db: AsyncSession, *, slug: str):
    from app.models import User, UserRole
    from app.services.loan_files import create_loan_file

    company = Company(name=slug.title(), slug=f"{slug}-{uuid4().hex[:8]}")
    db.add(company)
    await db.flush()
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
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    return company, user, loan_file


async def _routed_attachment(
    db: AsyncSession, *, loan_file, message_id: str, filename: str = "statement.pdf"
) -> InboundAttachment:
    """An assessed, SAFE attachment on a message routed to ``loan_file``.

    The raw message is stored locally so `accept` can re-read it — the bytes are re-derived from the
    stored `.eml` rather than copied, and a test that skipped that would not exercise the hash check.
    """
    from app.storage import get_storage_backend

    raw = _message_bytes(message_id=message_id, filename=filename)
    storage = get_storage_backend()
    storage_path = await storage.save(
        company_id=loan_file.company_id,
        file_id=loan_file.id,
        document_id=uuid4(),
        filename="message.eml",
        content=raw,
    )
    result = await ingest_raw_message(
        db, raw=raw, raw_storage_path=storage_path, ses_message_id=f"ses-{message_id}"
    )
    message_uuid = UUID(result.message_id)
    await apply_safety_to_message(db, inbound_message_id=message_uuid, raw=raw)

    from app.models.inbound_message import InboundMessage

    message = await db.get(InboundMessage, message_uuid)
    assert message is not None
    message.loan_file_id = loan_file.id
    message.company_id = loan_file.company_id
    await db.flush()

    attachment = (
        await db.execute(
            select(InboundAttachment).where(InboundAttachment.inbound_message_id == message_uuid)
        )
    ).scalar_one()
    assert attachment.safety_state is AttachmentSafetyState.SAFE, (
        "the fixture must produce a SAFE attachment or every acceptance test below is vacuous"
    )
    return attachment


# --------------------------------------------------------------------------------------------- #
# The dangerous case, made reachable
# --------------------------------------------------------------------------------------------- #
async def test_an_attachment_cannot_be_accepted_into_another_companys_file(
    db_session: AsyncSession,
) -> None:
    """TWO REAL COMPANIES, TWO REAL FILES, A REAL ATTACHMENT ON THE OTHER ONE.

    The attachment id is a path parameter, and the route only proves the caller owns the FILE.
    Nothing but this check proves the ATTACHMENT belongs to it — and the failure is one company's
    document on another company's loan."""
    _theirs, _their_user, their_file = await _company_user_file(db_session, slug="theirs")
    _mine, my_user, my_file = await _company_user_file(db_session, slug="mine")
    attachment = await _routed_attachment(
        db_session, loan_file=their_file, message_id="theirs-1@example.com"
    )

    with pytest.raises(CannotAcceptError, match="different loan file"):
        await accept_attachment(
            db_session,
            loan_file=my_file,
            attachment=attachment,
            actor_user_id=my_user.id,
        )

    # And nothing was created on either file.
    assert await db_session.scalar(select(func.count()).select_from(Document)) == 0


async def test_accepting_into_the_right_file_works(db_session: AsyncSession) -> None:
    """The control. A check that refused everything would satisfy the test above and would make the
    product unable to accept anything at all."""
    _company, user, loan_file = await _company_user_file(db_session, slug="theirs")
    attachment = await _routed_attachment(
        db_session, loan_file=loan_file, message_id="ours-1@example.com"
    )

    result = await accept_attachment(
        db_session, loan_file=loan_file, attachment=attachment, actor_user_id=user.id
    )

    assert result.document is not None
    assert result.attachment.disposition is AttachmentDisposition.ACCEPTED


# --------------------------------------------------------------------------------------------- #
# Pending is not a pass
# --------------------------------------------------------------------------------------------- #
async def test_an_unassessed_attachment_cannot_be_accepted(db_session: AsyncSession) -> None:
    """PENDING IS NOT A PASS. The malware scan is asynchronous, so it is a state that genuinely
    persists — and "nobody has looked yet" must never read as "nothing was found"."""
    _company, user, loan_file = await _company_user_file(db_session, slug="theirs")
    attachment = await _routed_attachment(
        db_session, loan_file=loan_file, message_id="pending-1@example.com"
    )
    attachment.safety_state = AttachmentSafetyState.PENDING
    await db_session.flush()

    with pytest.raises(CannotAcceptError, match="pending"):
        await accept_attachment(
            db_session, loan_file=loan_file, attachment=attachment, actor_user_id=user.id
        )
    assert await db_session.scalar(select(func.count()).select_from(Document)) == 0


async def test_a_quarantined_attachment_cannot_be_accepted(db_session: AsyncSession) -> None:
    _company, user, loan_file = await _company_user_file(db_session, slug="theirs")
    attachment = await _routed_attachment(
        db_session, loan_file=loan_file, message_id="quarantined-1@example.com"
    )
    attachment.safety_state = AttachmentSafetyState.QUARANTINED
    attachment.safety_reason = "The file says it is application/pdf but its contents are zip."
    await db_session.flush()

    with pytest.raises(CannotAcceptError, match="quarantined"):
        await accept_attachment(
            db_session, loan_file=loan_file, attachment=attachment, actor_user_id=user.id
        )


async def test_accepting_twice_is_refused(db_session: AsyncSession) -> None:
    """A second click must not produce a second document. The processor is told the first one went."""
    _company, user, loan_file = await _company_user_file(db_session, slug="theirs")
    attachment = await _routed_attachment(
        db_session, loan_file=loan_file, message_id="twice-1@example.com"
    )
    await accept_attachment(
        db_session, loan_file=loan_file, attachment=attachment, actor_user_id=user.id
    )

    with pytest.raises(CannotAcceptError, match="already been accepted"):
        await accept_attachment(
            db_session, loan_file=loan_file, attachment=attachment, actor_user_id=user.id
        )
    assert await db_session.scalar(select(func.count()).select_from(Document)) == 1


# --------------------------------------------------------------------------------------------- #
# Indistinguishable from a manual upload
# --------------------------------------------------------------------------------------------- #
async def test_the_document_is_a_normal_document_except_for_its_provenance(
    db_session: AsyncSession,
) -> None:
    """The ticket's own "Done when". Same `create_document`, same storage path shape, same PENDING
    status, same pipeline — the only differences are `upload_source` and a null uploader."""
    _company, user, loan_file = await _company_user_file(db_session, slug="theirs")
    attachment = await _routed_attachment(
        db_session, loan_file=loan_file, message_id="normal-1@example.com"
    )

    result = await accept_attachment(
        db_session, loan_file=loan_file, attachment=attachment, actor_user_id=user.id
    )

    document = result.document
    assert document is not None
    assert document.upload_source is UploadSource.BORROWER_INBOX
    # NULL, per ADR-056. Naming the processor who clicked accept would make the provenance say
    # something untrue — a borrower emailed it; no user uploaded it.
    assert document.uploaded_by_user_id is None
    assert document.loan_file_id == loan_file.id
    assert document.file_size_bytes == attachment.size_bytes
    assert attachment.document_id == document.id

    # AND THE STORED BYTES ARE THE ATTACHMENT'S BYTES. Asserted directly, because a mutant that
    # substituted different content still passed every other assertion here — the size came from the
    # recorded value rather than from what was written, so the one number anybody would check agreed
    # with a document containing something else.
    from app.storage import get_storage_backend

    stored = await get_storage_backend().read(document.storage_path)
    assert stored == _PDF


async def test_the_bytes_come_from_the_stored_message(db_session: AsyncSession) -> None:
    """Re-derived rather than copied, and matched back by sha256. If no part of the stored message
    hashes to what was recorded, the bytes are not the bytes that were ASSESSED — and accepting them
    would put unassessed content on a loan file behind a SAFE verdict about something else."""
    _company, user, loan_file = await _company_user_file(db_session, slug="theirs")
    attachment = await _routed_attachment(
        db_session, loan_file=loan_file, message_id="bytes-1@example.com"
    )
    attachment.sha256 = "0" * 64  # the stored message no longer contains anything hashing to this
    await db_session.flush()

    with pytest.raises(CannotAcceptError, match="no longer matches"):
        await accept_attachment(
            db_session, loan_file=loan_file, attachment=attachment, actor_user_id=user.id
        )


# --------------------------------------------------------------------------------------------- #
# possible_duplicate — a column nothing has ever written True to
# --------------------------------------------------------------------------------------------- #
async def test_a_second_document_of_the_same_type_is_flagged(
    db_session: AsyncSession,
) -> None:
    """`Document.possible_duplicate` has existed since LP-33 — the column, its schema field and its
    frontend type — and NOTHING HAS EVER WRITTEN True. Its docstring names this exact case: a
    document that arrives by email cannot be "replaced" by a click, so it arrives flagged."""
    _company, user, loan_file = await _company_user_file(db_session, slug="theirs")
    first = await _routed_attachment(
        db_session, loan_file=loan_file, message_id="dup-1@example.com"
    )
    first_result = await accept_attachment(
        db_session, loan_file=loan_file, attachment=first, actor_user_id=user.id
    )
    assert first_result.document is not None
    # Classification is a later pipeline step; set the type as that step would.
    first_result.document.document_type = "bank_statement"
    await db_session.flush()

    second = await _routed_attachment(
        db_session, loan_file=loan_file, message_id="dup-2@example.com", filename="again.pdf"
    )
    second_result = await accept_attachment(
        db_session, loan_file=loan_file, attachment=second, actor_user_id=user.id
    )
    assert second_result.document is not None
    second_result.document.document_type = "bank_statement"
    flagged = await _flag(db_session, loan_file.id, second_result.document)

    assert flagged is True
    assert second_result.document.possible_duplicate is True


async def _flag(db: AsyncSession, loan_file_id, document) -> bool:  # type: ignore[no-untyped-def]
    from app.services.inbound_triage import _flag_possible_duplicate

    return await _flag_possible_duplicate(db, loan_file_id=loan_file_id, document=document)


async def test_two_unclassified_documents_do_not_flag_each_other(
    db_session: AsyncSession,
) -> None:
    """The guard is on document_type being KNOWN, and this is the case that needs it. SQLAlchemy
    turns `document_type == None` into `IS NULL`, so without the guard two unclassified arrivals
    would match each other and both be flagged as duplicates of nothing in particular.

    Found by a surviving mutant: removing the guard left every other test green, because none of
    them had a second unclassified document to match against."""
    _company, user, loan_file = await _company_user_file(db_session, slug="theirs")
    first = await _routed_attachment(
        db_session, loan_file=loan_file, message_id="unclass-a@example.com"
    )
    second = await _routed_attachment(
        db_session, loan_file=loan_file, message_id="unclass-b@example.com", filename="b.pdf"
    )

    first_result = await accept_attachment(
        db_session, loan_file=loan_file, attachment=first, actor_user_id=user.id
    )
    second_result = await accept_attachment(
        db_session, loan_file=loan_file, attachment=second, actor_user_id=user.id
    )

    assert first_result.document is not None and second_result.document is not None
    assert first_result.document.document_type is None
    assert second_result.flagged_possible_duplicate is False
    assert second_result.document.possible_duplicate is False


async def test_an_unclassified_document_is_not_flagged(db_session: AsyncSession) -> None:
    """The control, and the reason the check is on TYPE rather than filename. An arrival with no type
    yet is not a duplicate of anything, and flagging on filename would fire on every `scan.pdf`."""
    _company, user, loan_file = await _company_user_file(db_session, slug="theirs")
    attachment = await _routed_attachment(
        db_session, loan_file=loan_file, message_id="unclassified-1@example.com"
    )

    result = await accept_attachment(
        db_session, loan_file=loan_file, attachment=attachment, actor_user_id=user.id
    )

    assert result.document is not None and result.document.document_type is None
    assert result.flagged_possible_duplicate is False
    assert result.document.possible_duplicate is False


# --------------------------------------------------------------------------------------------- #
# Correspondence
# --------------------------------------------------------------------------------------------- #
async def test_correspondence_is_kept_without_becoming_a_document(
    db_session: AsyncSession,
) -> None:
    """A lender's conditional-approval PDF satisfies no need and would be classified against a
    166-type BORROWER taxonomy. Correspondence keeps it and shows it without pretending it is
    evidence of anything."""
    _company, user, loan_file = await _company_user_file(db_session, slug="theirs")
    attachment = await _routed_attachment(
        db_session, loan_file=loan_file, message_id="corr-1@example.com"
    )

    result = await accept_attachment(
        db_session,
        loan_file=loan_file,
        attachment=attachment,
        actor_user_id=user.id,
        accept_as=AcceptAs.CORRESPONDENCE,
    )

    assert result.document is None
    assert result.attachment.disposition is AttachmentDisposition.CORRESPONDENCE
    assert await db_session.scalar(select(func.count()).select_from(Document)) == 0


# --------------------------------------------------------------------------------------------- #
# The queue
# --------------------------------------------------------------------------------------------- #
async def test_the_queue_is_scoped_to_the_company(db_session: AsyncSession) -> None:
    theirs, _their_user, their_file = await _company_user_file(db_session, slug="theirs")
    mine, _my_user, _my_file = await _company_user_file(db_session, slug="mine")
    await _routed_attachment(db_session, loan_file=their_file, message_id="queue-1@example.com")

    theirs_queue = await list_triage_queue(db_session, company_id=theirs.id, include_unrouted=False)
    mine_queue = await list_triage_queue(db_session, company_id=mine.id, include_unrouted=False)

    assert len(theirs_queue) == 1
    assert mine_queue == []


async def test_unrouted_messages_are_visible_but_only_when_asked_for(
    db_session: AsyncSession,
) -> None:
    """§2.2: "confidence gates auto-acceptance, never visibility". An unrouted message has NO
    company_id — LP-805 refuses to guess one — so it cannot come back from a company-scoped filter,
    and `include_unrouted` makes a caller ask for it deliberately."""
    theirs, _user, _file = await _company_user_file(db_session, slug="theirs")
    raw = _message_bytes(message_id="unrouted-1@example.com")
    await ingest_raw_message(
        db_session, raw=raw, raw_storage_path=None, ses_message_id="ses-unrouted-1"
    )

    without = await list_triage_queue(db_session, company_id=theirs.id, include_unrouted=False)
    with_unrouted = await list_triage_queue(db_session, company_id=theirs.id, include_unrouted=True)

    assert without == []
    assert len(with_unrouted) == 1
    assert with_unrouted[0].company_id is None


# --------------------------------------------------------------------------------------------- #
# An unrouted message is shown to EVERY company (review finding)
# --------------------------------------------------------------------------------------------- #
async def test_an_unclaimed_message_carries_nothing_the_sender_wrote(
    db_session: AsyncSession,
) -> None:
    """The queue returns unrouted messages to every company, because none owns them yet.

    Before the redaction that meant one tenant received another tenant's borrower's personal email
    address, a subject line that in this domain routinely names the borrower and the property, and
    the sender's own filenames. Measured: `from_address` came back as
    `jane.borrower@personal-email.com` to a company with no connection to it.

    `InboundAttachmentPublic`'s docstring names the condition that makes returning
    `filename_original` safe — "an authenticated user of the OWNING COMPANY, over a route already
    scoped to their loan file". An unrouted message has no owning company and this route is not
    file-scoped, so that condition is not met and the field must not travel.
    """
    from app.api.inbound import _message_public

    stranger = Company(name="Stranger", slug=f"s-{uuid4().hex[:8]}")
    db_session.add(stranger)
    await db_session.flush()

    message = InboundMessage(
        company_id=None,
        ingest_key=f"k-{uuid4().hex}",
        routing_state=InboundRoutingState.UNROUTED,
        from_address="jane.borrower@personal-email.com",
        subject="Docs for 42 Maple Ave - Jane Borrower",
        raw_storage_path="s3://bucket/key",
        auth_verdicts={},
    )
    db_session.add(message)
    await db_session.flush()
    db_session.add(
        InboundAttachment(
            inbound_message_id=message.id,
            filename_original="Jane_Borrower_2024_tax_return.pdf",
            filename_normalized="jane_borrower_2024_tax_return.pdf",
            size_bytes=1024,
            sha256="0" * 64,
        )
    )
    await db_session.flush()

    public = await _message_public(db_session, message)

    # Nothing the sender wrote.
    assert public.from_address is None
    assert public.subject is None
    assert [a.filename_original for a in public.attachments] == [None]
    assert [a.filename_normalized for a in public.attachments] == [None]

    # But it is still VISIBLE, which is what §2.2 requires: the fact of it, its shape, its age.
    assert public.id == message.id
    assert public.routing_state == InboundRoutingState.UNROUTED.value
    assert len(public.attachments) == 1
    assert public.attachments[0].size_bytes == 1024


async def test_a_claimed_message_is_returned_in_full(db_session: AsyncSession) -> None:
    """The control, and the one that matters: redacting everything would satisfy the test above
    while blinding a processor to their own file's mail."""
    from app.api.inbound import _message_public

    company = Company(name="Owner", slug=f"o-{uuid4().hex[:8]}")
    db_session.add(company)
    await db_session.flush()

    message = InboundMessage(
        company_id=company.id,
        ingest_key=f"k-{uuid4().hex}",
        routing_state=InboundRoutingState.ROUTED,
        from_address="jane.borrower@personal-email.com",
        subject="Docs for 42 Maple Ave - Jane Borrower",
        raw_storage_path="s3://bucket/key",
        auth_verdicts={},
    )
    db_session.add(message)
    await db_session.flush()
    db_session.add(
        InboundAttachment(
            inbound_message_id=message.id,
            filename_original="Jane_Borrower_2024_tax_return.pdf",
            filename_normalized="jane_borrower_2024_tax_return.pdf",
            size_bytes=1024,
            sha256="1" * 64,
        )
    )
    await db_session.flush()

    public = await _message_public(db_session, message)

    assert public.from_address == "jane.borrower@personal-email.com"
    assert public.subject == "Docs for 42 Maple Ave - Jane Borrower"
    assert public.attachments[0].filename_original == "Jane_Borrower_2024_tax_return.pdf"

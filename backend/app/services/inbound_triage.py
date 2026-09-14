"""Turning an inbound attachment into something on a loan file (LP-806).

THE DANGEROUS OPERATION IN PHASE 4. Everything before this observes: mail arrives, is parsed, is
assessed, is routed. This one WRITES — it puts a stranger's file onto a borrower's loan as a document
a human will later rely on. Two things must be impossible, and both are enforced here rather than
assumed upstream:

* **An attachment cannot be accepted into a file its message was not routed to.** The caller supplies
  a loan file (from an authenticated, company-scoped route) AND an attachment; if the attachment's
  message resolved to a different file, this refuses. Upstream already routed it — but "upstream
  already did it" is how a check gets left out, and the cost here is one company's document on
  another company's loan.
* **An attachment that has not been assessed cannot be accepted.** `PENDING` is not a pass: the
  malware scan is asynchronous, so it is a state that genuinely persists. Only `SAFE` may become a
  document.

CORRESPONDENCE IS THE THIRD ANSWER. A lender's conditional-approval PDF is worth keeping and is not
a borrower document — it satisfies no need and would be classified against a 166-type borrower
taxonomy. Accepting it as correspondence attaches it to the file and the timeline without entering
classify → extract → needs.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.activity_log import ActivityType
from app.models.document import Document, UploadSource
from app.models.helpers import only_active
from app.models.inbound_attachment import (
    AttachmentDisposition,
    AttachmentSafetyState,
    InboundAttachment,
)
from app.models.inbound_message import InboundMessage
from app.models.loan_file import LoanFile
from app.services.activity_log import log_activity
from app.services.documents import DuplicateDocumentError, create_document
from app.storage import get_storage_backend

logger = get_logger(__name__)


class CannotAcceptError(Exception):
    """The attachment cannot be accepted. Always names the rule that stopped it."""


class AcceptAs(StrEnum):
    """What an accepted attachment becomes."""

    DOCUMENT = "document"  # enters classify → extract → needs
    CORRESPONDENCE = "correspondence"  # kept and shown; never classified


@dataclass(frozen=True)
class AcceptResult:
    attachment: InboundAttachment
    document: Document | None
    #: True when a current document of the same type was already on the file. Surfaced, never
    #: blocking — the processor decides which one is the real one.
    flagged_possible_duplicate: bool


async def _attachment_bytes(db: AsyncSession, *, attachment: InboundAttachment) -> bytes:
    """The attachment's bytes, re-derived from the stored raw message.

    RE-PARSED RATHER THAN STORED TWICE. The `.eml` in S3 is the record of what arrived; a second copy
    of a borrower's document is a second thing to secure, retain and destroy. Matched back by sha256,
    which is what that column is for — and which also means a message whose bytes have changed since
    ingest cannot silently supply different content than the one that was assessed.
    """
    from app.services.inbound_mime import parse_message

    message = await db.get(InboundMessage, attachment.inbound_message_id)
    if message is None or not message.raw_storage_path:
        raise CannotAcceptError("The original message is no longer available.")

    storage = get_storage_backend()
    path = message.raw_storage_path
    if path.startswith("s3://"):
        path = path.split("/", 3)[3]
    raw = await storage.read(path)

    for parsed in parse_message(raw).attachments:
        if parsed.sha256 == attachment.sha256:
            return parsed.content
    # THE HASH IS THE CHECK. If no part of the stored message hashes to what we recorded, the bytes
    # are not the bytes that were assessed — and accepting them would put unassessed content on a
    # loan file behind a SAFE verdict that was about something else.
    raise CannotAcceptError("The attachment no longer matches the stored message.")


async def _flag_possible_duplicate(
    db: AsyncSession, *, loan_file_id: UUID, document: Document
) -> bool:
    """Mark the new document when a current one of the same type is already on the file.

    `Document.possible_duplicate` has existed since LP-33 — the column, its schema field and its
    frontend type — and NOTHING HAS EVER WRITTEN True TO IT. Its own docstring names this case: a
    document that arrives by email cannot be "replaced" by a click, so it arrives flagged for a
    processor to resolve.

    Only fires when the type is KNOWN. An unclassified arrival is not a duplicate of anything yet;
    flagging on filename would fire on every `scan.pdf`.
    """
    if document.document_type is None:
        return False
    existing = await db.scalar(
        only_active(
            select(Document.id).where(
                Document.loan_file_id == loan_file_id,
                Document.document_type == document.document_type,
                Document.id != document.id,
            ),
            Document,
        )
    )
    if existing is None:
        return False
    document.possible_duplicate = True
    return True


async def accept_attachment(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    attachment: InboundAttachment,
    actor_user_id: UUID,
    accept_as: AcceptAs = AcceptAs.DOCUMENT,
) -> AcceptResult:
    """Accept one attachment onto ``loan_file``. ``flush`` only; the endpoint commits.

    The resulting document is INDISTINGUISHABLE FROM A MANUAL UPLOAD except for its `upload_source`
    and its null `uploaded_by_user_id` — same `create_document`, same storage path shape, same
    `PENDING` status, same processing pipeline. That is the ticket's acceptance criterion and it is
    why this calls the existing service rather than building a parallel one.
    """
    message = await db.get(InboundMessage, attachment.inbound_message_id)
    if message is None:
        raise CannotAcceptError("The original message is no longer available.")

    # THE CROSS-FILE CHECK. The caller's loan file comes from an authenticated, company-scoped route;
    # the attachment comes from an id in the path. Nothing but this stops the two being different
    # files — and the failure is one company's document on another company's loan.
    if message.loan_file_id != loan_file.id:
        raise CannotAcceptError(
            "This attachment belongs to a message routed to a different loan file."
        )

    if attachment.safety_state is not AttachmentSafetyState.SAFE:
        # PENDING IS NOT A PASS. The malware scan is asynchronous, so this is a state that genuinely
        # persists rather than a momentary one, and "nobody has looked yet" must never read as
        # "nothing was found".
        raise CannotAcceptError(
            f"This attachment is {attachment.safety_state.value}, not safe to accept. "
            f"{attachment.safety_reason or ''}".strip()
        )

    if attachment.disposition is not AttachmentDisposition.PENDING:
        raise CannotAcceptError(f"This attachment has already been {attachment.disposition.value}.")

    if accept_as is AcceptAs.CORRESPONDENCE:
        attachment.disposition = AttachmentDisposition.CORRESPONDENCE
        await db.flush()
        await log_activity(
            db,
            loan_file_id=loan_file.id,
            activity_type=ActivityType.COMMUNICATION_RECEIVED,
            summary="An attachment was filed as correspondence",
            actor_user_id=actor_user_id,
            detail={"inbound_attachment_id": str(attachment.id), "as": "correspondence"},
        )
        return AcceptResult(attachment, None, flagged_possible_duplicate=False)

    content = await _attachment_bytes(db, attachment=attachment)
    document_id = uuid4()
    storage = get_storage_backend()
    storage_path = await storage.save(
        company_id=loan_file.company_id,
        file_id=loan_file.id,
        document_id=document_id,
        filename=attachment.filename_normalized or "attachment",
        content=content,
    )
    # LP-1000 — an attachment whose bytes are already on the file is refused with the rule that
    # stopped it, like every other refusal here. `CannotAcceptError` is what the endpoint maps to a
    # 409 carrying the message, so the processor triaging the mailbox is told WHICH document it
    # duplicates rather than being handed a 500.
    try:
        document = await create_document(
            db,
            loan_file=loan_file,
            document_id=document_id,
            filename=attachment.filename_normalized or "attachment",
            content=content,
            mime_type=attachment.sniffed_content_type or "application/octet-stream",
            # `len(content)` RATHER THAN `attachment.size_bytes`. They should agree — the bytes were
            # matched back by sha256 — but the recorded size is a fact about what was parsed and
            # this is a fact about what is being stored. Using the recorded one would let a document
            # whose stored bytes are something else still report the right size, which is the one
            # number anybody would check.
            size=len(content),
            storage_path=storage_path,
            # NULL, per ADR-056. A borrower emailed it; no user uploaded it, and naming the
            # processor who clicked accept would make the provenance say something untrue.
            uploaded_by_user_id=None,
            upload_source=UploadSource.BORROWER_INBOX,
        )
    except DuplicateDocumentError as exc:
        raise CannotAcceptError(str(exc)) from exc
    flagged = await _flag_possible_duplicate(db, loan_file_id=loan_file.id, document=document)

    attachment.disposition = AttachmentDisposition.ACCEPTED
    attachment.document_id = document.id
    await db.flush()

    await log_activity(
        db,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.DOCUMENT_UPLOADED,
        summary="A document arrived by email and was accepted",
        actor_user_id=actor_user_id,
        detail={
            "document_id": str(document.id),
            "inbound_attachment_id": str(attachment.id),
            "upload_source": UploadSource.BORROWER_INBOX.value,
            "possible_duplicate": flagged,
        },
    )
    # A COUNT AND IDS. Never the filename, which is text a stranger wrote.
    logger.info("inbound_attachment_accepted", possible_duplicate=flagged)
    return AcceptResult(attachment, document, flagged_possible_duplicate=flagged)


async def reject_attachment(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    attachment: InboundAttachment,
    actor_user_id: UUID,
) -> InboundAttachment:
    """Refuse one attachment. It stays on the message; it does not become a document."""
    message = await db.get(InboundMessage, attachment.inbound_message_id)
    if message is None or message.loan_file_id != loan_file.id:
        raise CannotAcceptError(
            "This attachment belongs to a message routed to a different loan file."
        )
    attachment.disposition = AttachmentDisposition.REJECTED
    await db.flush()
    return attachment


async def list_file_messages(db: AsyncSession, *, loan_file: LoanFile) -> list[InboundMessage]:
    """Everything that arrived for one loan file, newest first.

    SCOPED ON `loan_file_id`, and the file itself came from a company-scoped route. Deliberately NOT
    a filter applied to `list_triage_queue`'s result: that query returns every routed message for the
    company plus the unrouted pile, and narrowing a wide answer in the caller means the wide answer
    was computed, and could be returned, by a caller that forgot to narrow it.
    """
    return list(
        (
            await db.execute(
                only_active(
                    select(InboundMessage)
                    .where(InboundMessage.loan_file_id == loan_file.id)
                    .order_by(InboundMessage.received_at.desc().nullslast()),
                    InboundMessage,
                )
            )
        )
        .scalars()
        .all()
    )


async def attachment_preview(db: AsyncSession, *, attachment: InboundAttachment) -> bytes | None:
    """A PNG thumbnail of one attachment, or None when it has no renderable preview.

    SAFE ONLY, and that is the whole gate. `phase4.md` §2.3 says a rejected message is "never
    rendered, never extracted" — and a QUARANTINED attachment is quarantined precisely because
    something about its bytes was wrong, which makes it the last thing to hand a renderer. PENDING is
    not a pass here either, for the same reason accept refuses it: the scan is asynchronous.

    The bytes come through :func:`_attachment_bytes`, so the same sha256 check applies — a preview
    cannot show content that is not the content that was assessed.
    """
    if attachment.safety_state is not AttachmentSafetyState.SAFE:
        raise CannotAcceptError(
            attachment.safety_reason or "This attachment has not been confirmed safe to open."
        )
    from app.services.attachment_safety import render_preview_png

    return render_preview_png(await _attachment_bytes(db, attachment=attachment))


async def list_triage_queue(
    db: AsyncSession, *, company_id: UUID, include_unrouted: bool = True
) -> list[InboundMessage]:
    """Messages awaiting a processor's decision, for one company.

    SCOPED TO THE COMPANY, and unrouted messages are the interesting case: they have NO `company_id`,
    because LP-805 refuses to guess one from the sender. So they cannot be returned by a
    company-scoped filter, and `phase4.md` §2.2 says they must still be visible —
    "confidence gates auto-acceptance, never visibility".

    THE RESOLUTION IS THAT UNROUTED IS A SEPARATE, DELIBERATE QUERY, not a widening of the scoped
    one. `include_unrouted` exists so a caller has to ask for them, and the endpoint that does is a
    company-level view rather than a file-level one. An unrouted message is shown to every company —
    which is the honest consequence of not knowing whose it is, and is why nothing about it beyond
    the fact of its existence may be exposed until somebody claims it.
    """
    routed = (
        (
            await db.execute(
                only_active(
                    select(InboundMessage)
                    .where(InboundMessage.company_id == company_id)
                    .order_by(InboundMessage.created_at.desc()),
                    InboundMessage,
                )
            )
        )
        .scalars()
        .all()
    )
    if not include_unrouted:
        return list(routed)

    unrouted = (
        (
            await db.execute(
                only_active(
                    select(InboundMessage)
                    .where(InboundMessage.company_id.is_(None))
                    .order_by(InboundMessage.created_at.desc()),
                    InboundMessage,
                )
            )
        )
        .scalars()
        .all()
    )
    return [*routed, *unrouted]


__all__ = [
    "AcceptAs",
    "AcceptResult",
    "CannotAcceptError",
    "accept_attachment",
    "attachment_preview",
    "list_file_messages",
    "list_triage_queue",
    "reject_attachment",
]

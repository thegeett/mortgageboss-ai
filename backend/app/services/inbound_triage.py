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
from app.models.condition_round import ConditionRound
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
from app.services.documents import create_document
from app.storage import get_storage_backend

# ⚠️ THE MODEL IS A TOP-LEVEL IMPORT; ONLY THE SERVICE IS FUNCTION-LOCAL. An earlier version put
# `ConditionRound` under `TYPE_CHECKING`, reasoning about a cycle — but the cycle concern belongs to
# `app.services.condition_rounds`, which this module calls into, NOT to `app.models.condition_round`,
# which imports no services at all. The result was a name available to mypy and absent at runtime:
# `select(ConditionRound)` inside the forward action would have raised `NameError` on the first
# forward, while `import app.services.inbound_triage` succeeded and proved nothing.

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
    document = await create_document(
        db,
        loan_file=loan_file,
        document_id=document_id,
        filename=attachment.filename_normalized or "attachment",
        mime_type=attachment.sniffed_content_type or "application/octet-stream",
        # `len(content)` RATHER THAN `attachment.size_bytes`. They should agree — the bytes were
        # matched back by sha256 — but the recorded size is a fact about what was parsed and this is
        # a fact about what is being stored. Using the recorded one would let a document whose stored
        # bytes are something else still report the right size, which is the one number anybody would
        # check.
        size=len(content),
        storage_path=storage_path,
        # NULL, per ADR-056. A borrower emailed it; no user uploaded it, and naming the processor who
        # clicked accept would make the provenance say something untrue.
        uploaded_by_user_id=None,
        upload_source=UploadSource.BORROWER_INBOX,
    )
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


async def _round_carrying(
    db: AsyncSession, *, loan_file: LoanFile, attachment: InboundAttachment
) -> ConditionRound | None:
    """The active round on this file whose `sources` already carry this attachment, if any.

    ⚠️ ONE QUESTION, ASKED BY BOTH DOORS, AND SPLITTING IT IS HOW THE INVARIANT BROKE TWICE. The
    attachment→round link is DERIVED from `sources` rather than stored as a column (screen S1-13
    renders "Used as condition sheet → Round N" from it), and that derivation assumes ONE-TO-ONE.

    The first break was a self-permitting loop on the create path: the disposition guard admitted
    CORRESPONDENCE and the action set it, so every repeat forward made another round.

    The second was subtler and this helper exists because of it. The guard lived INSIDE
    `forward_attachment_as_sheet`, and the endpoint branches to the merge BEFORE calling it — so
    forwarding an attachment and then merging the same attachment into a DIFFERENT round produced
    two rounds carrying one id, with neither guard at fault: `enrich_round_with_pdf` asks only
    whether the TARGET round already has a PDF source, which cannot see another round. Worse than
    the first, because those two rounds look legitimately different — one PARSING from the email,
    one DRAFT under review — so nothing suggests they share a source.

    The fix is to ask the question where the ATTACHMENT is the subject, once, for both paths.
    """
    found: ConditionRound | None = await db.scalar(
        only_active(
            select(ConditionRound).where(
                ConditionRound.loan_file_id == loan_file.id,
                ConditionRound.sources.contains([{"inbound_attachment_id": str(attachment.id)}]),
            ),
            ConditionRound,
        )
    )
    return found


async def forward_attachment_as_sheet(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    attachment: InboundAttachment,
    actor_user_id: UUID,
) -> ConditionRound:
    """Use an emailed PDF as a condition sheet, keeping it as CORRESPONDENCE (LP-905, spec §6).

    ⚠️ IT LIVES HERE BY PRECEDENT, NOT BY TASTE. This module already imports the domain service that
    owns what an attachment becomes — `from app.services.documents import create_document` (line 44),
    called by `accept_attachment` at line 192 — so "a triage action reaches into the domain service
    that owns the object it produces" is the established pattern in this exact file, and this is that
    pattern one domain over.

    The alternative — building the action in `condition_rounds` — would invert a dependency this file
    has already settled, and would need `_attachment_bytes` promoted across a module boundary to do
    it. `condition_rounds` does not import this module, so the dependency still runs one way only.

    ⚠️ THE ATTACHMENT DOES NOT BECOME A DOCUMENT, and that is the whole point of the action. A
    lender's letter satisfies no need and would be classified against a 166-type BORROWER taxonomy —
    the same reasoning that created `CORRESPONDENCE` in the first place (ADR-403). So the bytes are
    re-derived and handed to `create_round_from_sheet`, which stores them with `save_at`; no
    `Document` row is created and the classify → extract → needs pipeline is never entered.

    The disposition is set to CORRESPONDENCE rather than left PENDING: the processor HAS now decided
    what this attachment is. Screen S1-13 reads that back as "Kept as correspondence" beside a link
    to the round, which is derivable from the round's `sources` — each carries the
    `inbound_attachment_id` it came from, so no column is needed to join them.
    """
    from app.models.condition_round import ConditionSourceKind
    from app.services.condition_rounds import SheetBytes, create_round_from_sheet

    message = await db.get(InboundMessage, attachment.inbound_message_id)
    if message is None:
        raise CannotAcceptError("The original message is no longer available.")

    # ⚠️ THE SAME GUARDS AS `accept_attachment`, COPIED RATHER THAN SHARED — AND THEY HAVE ALREADY
    # DIVERGED, which is the argument rather than a hypothetical one. `accept_attachment` refuses
    # anything that is not PENDING (line 174); this admits PENDING *or* CORRESPONDENCE, because a
    # processor may file an attachment as correspondence first and decide to read it as a sheet
    # afterwards. A shared `_may_be_used(...)` would have needed a parameter on the day it was
    # written, which is precisely the shape that makes a helper worse than the duplication.
    if message.loan_file_id != loan_file.id:
        raise CannotAcceptError(
            "This attachment belongs to a message routed to a different loan file."
        )
    if attachment.safety_state is not AttachmentSafetyState.SAFE:
        # PENDING IS NOT A PASS — the scan is asynchronous, so "nobody has looked yet" is a state
        # that genuinely persists and must never read as "nothing was found".
        raise CannotAcceptError(
            f"This attachment is {attachment.safety_state.value}, not safe to use. "
            f"{attachment.safety_reason or ''}".strip()
        )
    # ⚠️ ALREADY USED? THE GUARD BELOW CANNOT ANSWER THIS, BY CONSTRUCTION. It admits PENDING or
    # CORRESPONDENCE, and this function ends by SETTING CORRESPONDENCE — so the first call creates
    # exactly the state the next call requires, and it stays true forever. A self-permitting loop:
    # N forwards gave N rounds, all PARSING, all reading identical bytes.
    #
    # The wasted work was the least of it. Every such round carries the same `inbound_attachment_id`
    # in `sources`, and that field is how the attachment→round link is derived rather than stored as
    # a column. The derivation assumes ONE-TO-ONE; duplicates made it one-to-many and left screen
    # S1-13's "Used as condition sheet → Round N" with no single answer to render. A stated
    # invariant, invalidated silently.
    #
    # Asked of the rounds rather than of the attachment, and no new column is needed: the field that
    # IS the join is the field that answers it.
    existing = await _round_carrying(db, loan_file=loan_file, attachment=attachment)
    if existing is not None:
        # Naming the round is what a processor who clicked twice actually wants — "this is already
        # round 3" rather than a second round to discard.
        raise CannotAcceptError(
            f"This attachment has already been used as a condition sheet ({existing.id})."
        )

    if attachment.disposition not in (
        AttachmentDisposition.PENDING,
        AttachmentDisposition.CORRESPONDENCE,
    ):
        # Already accepted as a document, rejected or marked duplicate. CORRESPONDENCE is allowed
        # through because the processor may file it first and decide to read it afterwards.
        raise CannotAcceptError(f"This attachment has already been {attachment.disposition.value}.")

    content = await _attachment_bytes(db, attachment=attachment)
    round_ = await create_round_from_sheet(
        db,
        loan_file=loan_file,
        sheet=SheetBytes(
            content=content,
            source_kind=ConditionSourceKind.EMAIL,
            # ⚠️ WHAT THE SENDER'S MAIL CLIENT DECLARED, passed through rather than assumed, so a
            # refusal quotes the claim the sender actually made (LP-905 §1 review, Q1).
            declared_content_type=attachment.declared_content_type,
            inbound_attachment_id=attachment.id,
        ),
        actor_user_id=actor_user_id,
    )

    attachment.disposition = AttachmentDisposition.CORRESPONDENCE
    await db.flush()
    logger.info(
        "attachment_used_as_condition_sheet",
        attachment_id=str(attachment.id),
        round_id=str(round_.id),
        loan_file_id=str(loan_file.id),
    )
    return round_


async def merge_attachment_into_round(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    attachment: InboundAttachment,
    round_id: UUID,
    actor_user_id: UUID,
) -> ConditionRound:
    """Merge an emailed PDF into an EXISTING round instead of opening a new one (LP-907).

    This is what spec §LP-905's `attach_to_round_id` always meant, and what LP-905 refused with a
    `501` because the merge did not exist yet.

    ⚠️ THE ROUND IS LOADED SCOPED TO THIS LOAN FILE, AND THAT IS NOT OPTIONAL. `round_id` arrives in
    a REQUEST BODY, so it is a caller-supplied id for a globally-unique row — the one shape that
    cannot be trusted to belong to the file in the path. The route proves the caller owns the FILE;
    nothing but this query proves the ROUND is on it. Scoping inside the statement rather than
    fetching and comparing means a mismatched (file, round) pair is unfetchable, not merely
    rejected.

    ⚠️ THE `sources` GUARD APPLIES HERE TOO, AND AN EARLIER VERSION OF THIS DOCSTRING ARGUED IT
    SHOULD NOT. The argument was that merging creates no second round, so the duplicate guard did not
    fit — true as far as it went, and it left a hole a review found by execution: forward an
    attachment (round 1 carries its id), then merge the SAME attachment into a different round, and
    two rounds carry one `inbound_attachment_id`. Exactly the one-to-many S1-13 cannot render.

    `enrich_round_with_pdf` could not catch it: its guard asks whether THE TARGET round already has
    a PDF source, and a different round is invisible to that question. Both guards were individually
    correct, and the gap was the space between them.

    So `_round_carrying` runs on this path as well, with ONE exception: when the round already
    carrying the attachment IS the merge target. That is a re-attach to the same round, and
    `enrich_round_with_pdf` refuses it on its own terms with a message that says so — "this round
    already has the lender's PDF" is more useful there than "already used as a condition sheet".
    """
    from app.services.condition_enrich import enrich_round_with_pdf

    message = await db.get(InboundMessage, attachment.inbound_message_id)
    if message is None:
        raise CannotAcceptError("The original message is no longer available.")
    if message.loan_file_id != loan_file.id:
        raise CannotAcceptError(
            "This attachment belongs to a message routed to a different loan file."
        )
    if attachment.safety_state is not AttachmentSafetyState.SAFE:
        # PENDING IS NOT A PASS — the scan is asynchronous, so "nobody has looked yet" is a state
        # that genuinely persists and must never read as "nothing was found".
        raise CannotAcceptError(
            f"This attachment is {attachment.safety_state.value}, not safe to use. "
            f"{attachment.safety_reason or ''}".strip()
        )
    if attachment.disposition not in (
        AttachmentDisposition.PENDING,
        AttachmentDisposition.CORRESPONDENCE,
    ):
        raise CannotAcceptError(f"This attachment has already been {attachment.disposition.value}.")

    round_ = await db.scalar(
        only_active(
            select(ConditionRound).where(
                ConditionRound.id == round_id,
                ConditionRound.loan_file_id == loan_file.id,
            ),
            ConditionRound,
        )
    )
    if round_ is None:
        raise CannotAcceptError("No such condition round on this loan file.")

    carrying = await _round_carrying(db, loan_file=loan_file, attachment=attachment)
    if carrying is not None and carrying.id != round_.id:
        # A DIFFERENT round already has this attachment. Naming it is what the processor needs:
        # the answer is "it is already on round N", not "try a different round".
        raise CannotAcceptError(
            f"This attachment has already been used as a condition sheet ({carrying.id})."
        )

    from app.models.condition_round import ConditionSourceKind

    content = await _attachment_bytes(db, attachment=attachment)
    await enrich_round_with_pdf(
        db,
        round_=round_,
        content=content,
        # What the sender's mail client declared, so a refusal quotes the sender's own claim.
        declared_content_type=attachment.declared_content_type,
        actor_user_id=actor_user_id,
        # ⚠️ EMAIL, NOT THE DEFAULT. This letter arrived as a forwarded attachment, and `sources`
        # records how each arrival reached us. The enrich hard-coded `PDF_UPLOAD` until now, so every
        # round merged from a forward has been claiming someone uploaded it.
        source_kind=ConditionSourceKind.EMAIL,
    )

    # The attachment's id goes onto the ROUND's sources by the merge itself, so S1-13's link still
    # derives from the same field — now pointing at the round it enriched.
    round_.sources = [
        *round_.sources[:-1],
        {**round_.sources[-1], "inbound_attachment_id": str(attachment.id)},
    ]
    attachment.disposition = AttachmentDisposition.CORRESPONDENCE
    await db.flush()
    logger.info(
        "attachment_merged_into_condition_round",
        attachment_id=str(attachment.id),
        round_id=str(round_.id),
        loan_file_id=str(loan_file.id),
    )
    return round_


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
    "forward_attachment_as_sheet",
    "list_file_messages",
    "list_triage_queue",
    "reject_attachment",
]

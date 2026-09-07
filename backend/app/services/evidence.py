"""The evidence record, and the legal hold that stops it being destroyed (LP-821).

TWO HALVES OF ONE OBLIGATION. `phase4.md` §6 asks for a communication log that is *"append-only at
the application layer"* and *"must not be soft-deletable"* — and, separately, for a legal-hold flag
shipped **before** the purge job, because INFRA-1 builds the S3 lifecycle expiry (which *is* the
purge job) on day one of the critical path. A record that cannot be edited is worth nothing if a
lifecycle rule deletes the object it describes.

APPEND-ONLY IS ENFORCED BY WHAT THIS MODULE DOES NOT DO. There is no update function and no delete
function, and `record_*` refuses a second row for the same (message, event) rather than overwriting
one. The unique index makes that structural; the check here makes the refusal a sentence instead of
an `IntegrityError`, because a retried send is the case most likely to produce it.

WHAT IS RECOVERABLE FOR MESSAGES SENT BEFORE THIS TICKET is spelled out in
`models/communication_evidence`'s docstring rather than left for an audit to discover. The short
version: everything except the **composed draft**, which `send_draft` overwrote and which is gone
rather than unstored.

THE HOLD IS CHECKED WHERE DESTRUCTION HAPPENS, not where it is requested. `is_held` is a read any
purge path calls; `purge_blocked_by_hold` is the sentence it raises. Nothing in this repo purges yet
— INFRA-1 is unapplied — which is exactly why the flag ships now rather than beside it.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.base import utcnow
from app.models.communication import Communication
from app.models.communication_evidence import CommunicationEvidence, EvidenceEvent
from app.models.helpers import only_active
from app.models.inbound_attachment import InboundAttachment
from app.models.loan_file import LoanFile

logger = get_logger(__name__)


class LegalHoldError(Exception):
    """Something tried to destroy data on a file under hold."""


class EvidenceError(Exception):
    """The evidence record cannot be written as asked."""


async def _manifest(db: AsyncSession, *, inbound_message_id: UUID | None) -> list[dict[str, Any]]:
    """The attachment manifest with hashes, for an inbound message.

    THE HASH IS THE POINT. §6 asks for the manifest *with hashes* because a filename is what
    somebody called a file and a sha256 is what the file was — and an evidence record that named
    documents without identifying them could not answer "is this the one that arrived".

    `filename_original` — what the SENDER called it, which is what an auditor reading a borrower's
    own email would look for. It is attacker-controlled text and it is stored, never executed.
    """
    if inbound_message_id is None:
        return []
    rows = (
        (
            await db.execute(
                only_active(
                    select(InboundAttachment).where(
                        InboundAttachment.inbound_message_id == inbound_message_id
                    ),
                    InboundAttachment,
                )
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "filename": row.filename_original or row.filename_normalized,
            "sha256": row.sha256,
            "size_bytes": row.size_bytes,
            "safety_state": row.safety_state.value,
        }
        for row in rows
    ]


async def _refuse_duplicate(
    db: AsyncSession, *, communication_id: UUID, event: EvidenceEvent
) -> None:
    existing = await db.scalar(
        select(CommunicationEvidence.id).where(
            CommunicationEvidence.communication_id == communication_id,
            CommunicationEvidence.event == event,
        )
    )
    if existing is not None:
        # A SENTENCE, NOT AN IntegrityError. A retried send is the case most likely to reach this,
        # and a caller that has to distinguish "already recorded" from "the database rejected
        # something" will get it wrong at three in the morning.
        raise EvidenceError(f"This message already has a {event.value} record.")


async def record_sent(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    communication: Communication,
    approver_user_id: UUID | None,
    body_composed: str | None = None,
    guardrail_fired: str | None = None,
    model_id: str | None = None,
    prompt_version: str | None = None,
) -> CommunicationEvidence:
    """Record that a message went out, as it went out. ``flush`` only; the caller commits.

    `body_composed` IS PASSED IN, NOT READ. By the time `send_draft` calls this it has already
    replaced `draft.body` with the processor's edit — so the caller has to hand over what it held
    beforehand, and a version of this that read the row would silently record the edit twice and
    report a diff of nothing.
    """
    await _refuse_duplicate(db, communication_id=communication.id, event=EvidenceEvent.SENT)
    row = CommunicationEvidence(
        loan_file_id=loan_file.id,
        communication_id=communication.id,
        event=EvidenceEvent.SENT,
        sender=communication.sender,
        recipient=communication.recipient,
        approver_user_id=approver_user_id,
        template_key=communication.template_key,
        template_version=communication.template_version,
        subject=communication.subject,
        body_as_sent=communication.body,
        body_composed=body_composed,
        attachment_manifest=[],
        guardrail_fired=guardrail_fired,
        model_id=model_id,
        prompt_version=prompt_version,
        auth_verdicts={},
    )
    db.add(row)
    await db.flush()
    # METADATA ONLY — an id, an event and whether a draft was captured. Never the body, the subject
    # or the recipient, all three of which are on the row this line is about.
    logger.info(
        "evidence_recorded",
        loan_file_id=str(loan_file.id),
        # `evidence_event`, NOT `event`: structlog binds `event` as the message itself, so passing it
        # as a keyword raises TypeError — which would have crashed every send.
        evidence_event=EvidenceEvent.SENT.value,
        composed_captured=body_composed is not None,
    )
    return row


async def record_received(
    db: AsyncSession, *, loan_file: LoanFile, communication: Communication
) -> CommunicationEvidence:
    """Record that a message arrived, with its manifest and the verdicts it was judged on.

    THE VERDICTS TRAVEL WITH IT. §6 asks for the inbound auth verdicts in the evidence record and
    not only on the message, because the message row is soft-deletable and because the verdicts are
    what a later question — "why was this accepted?" — actually turns on.
    """
    from app.models.inbound_message import InboundMessage

    await _refuse_duplicate(db, communication_id=communication.id, event=EvidenceEvent.RECEIVED)
    message = (
        await db.get(InboundMessage, communication.inbound_message_id)
        if communication.inbound_message_id
        else None
    )
    row = CommunicationEvidence(
        loan_file_id=loan_file.id,
        communication_id=communication.id,
        event=EvidenceEvent.RECEIVED,
        sender=message.from_address if message else communication.sender,
        recipient=communication.recipient,
        approver_user_id=None,
        template_key=None,
        template_version=None,
        subject=message.subject if message else communication.subject,
        body_as_sent=None,
        body_composed=None,
        attachment_manifest=await _manifest(
            db, inbound_message_id=communication.inbound_message_id
        ),
        guardrail_fired=None,
        model_id=None,
        prompt_version=None,
        auth_verdicts=dict(message.auth_verdicts or {}) if message else {},
    )
    db.add(row)
    await db.flush()
    logger.info(
        "evidence_recorded",
        loan_file_id=str(loan_file.id),
        evidence_event=EvidenceEvent.RECEIVED.value,
        attachments=len(row.attachment_manifest),
    )
    return row


async def record_delivery_failed(
    db: AsyncSession, *, loan_file: LoanFile, communication: Communication, reason: str | None
) -> CommunicationEvidence:
    """Record that a message came back.

    A SEPARATE ROW, NOT A FIELD ON THE SEND. The send record must not change after the fact — that is
    what append-only means — and "sent" and "sent, then bounced" are two events with two times.
    """
    await _refuse_duplicate(
        db, communication_id=communication.id, event=EvidenceEvent.DELIVERY_FAILED
    )
    row = CommunicationEvidence(
        loan_file_id=loan_file.id,
        communication_id=communication.id,
        event=EvidenceEvent.DELIVERY_FAILED,
        recipient=communication.recipient,
        # The provider's own words about why. Prose written by a mail system, not by a person, and
        # kept because "why did it bounce" is the question a processor asks next. NOT
        # `guardrail_fired`: a bounce is not a guard, and that column is read as one.
        failure_reason=reason,
        attachment_manifest=[],
        auth_verdicts={},
    )
    db.add(row)
    await db.flush()
    return row


async def evidence_for(db: AsyncSession, *, loan_file: LoanFile) -> list[CommunicationEvidence]:
    """Every recorded event on this file, oldest first. Read-only; nothing here can edit one."""
    return list(
        (
            await db.execute(
                select(CommunicationEvidence)
                .where(CommunicationEvidence.loan_file_id == loan_file.id)
                .order_by(CommunicationEvidence.recorded_at)
            )
        )
        .scalars()
        .all()
    )


# --------------------------------------------------------------------------------------------- #
# The legal hold
# --------------------------------------------------------------------------------------------- #
async def place_hold(
    db: AsyncSession, *, loan_file: LoanFile, reason: str, actor_user_id: UUID
) -> LoanFile:
    """Suspend every destruction path for this file. ``flush`` only.

    A REASON IS REQUIRED TO PLACE ONE and never to lift one. Placing is the decision that has to be
    justifiable later — FRCP 37(e) asks what a party knew and when — and requiring a justification to
    LIFT a hold makes lifting harder than placing, which is the wrong way round for a control whose
    failure mode is holding too much forever.

    IDEMPOTENT, AND THE ORIGINAL TIME SURVIVES. Re-placing a hold keeps `legal_hold_at`, because
    "since when" is the question a court asks and the answer is when it was first placed.
    """
    if not (reason or "").strip():
        raise LegalHoldError("A legal hold needs a reason.")
    if not loan_file.legal_hold:
        loan_file.legal_hold = True
        loan_file.legal_hold_at = utcnow()
    loan_file.legal_hold_reason = reason.strip()
    await db.flush()

    from app.models.activity_log import ActivityType
    from app.services.activity_log import log_activity

    await log_activity(
        db,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.NOTE_ADDED,
        summary="A legal hold was placed on this file",
        actor_user_id=actor_user_id,
        # The reason IS recorded here, deliberately: it is a processor's own words about a legal
        # decision, not a borrower's prose, and an audit asking "why" needs it beside the when.
        detail={"legal_hold": True, "reason": reason.strip()},
    )
    logger.info("legal_hold_placed", loan_file_id=str(loan_file.id))
    return loan_file


async def lift_hold(db: AsyncSession, *, loan_file: LoanFile, actor_user_id: UUID) -> LoanFile:
    """Release the file. ``flush`` only.

    `legal_hold_at` IS CLEARED, and the activity log is what remembers. Leaving the timestamp would
    make "is it held" and "was it ever held" the same read, and the first is what a purge asks.
    """
    if not loan_file.legal_hold:
        return loan_file
    loan_file.legal_hold = False
    loan_file.legal_hold_at = None
    loan_file.legal_hold_reason = None
    await db.flush()

    from app.models.activity_log import ActivityType
    from app.services.activity_log import log_activity

    await log_activity(
        db,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.NOTE_ADDED,
        summary="The legal hold on this file was lifted",
        actor_user_id=actor_user_id,
        detail={"legal_hold": False},
    )
    logger.info("legal_hold_lifted", loan_file_id=str(loan_file.id))
    return loan_file


def is_held(loan_file: LoanFile) -> bool:
    """Whether anything on this file may be destroyed.

    THE ONE READ EVERY PURGE PATH MUST CALL. Nothing in this repo purges yet — INFRA-1's S3
    lifecycle expiry is written and unapplied — which is precisely why this exists now: §6 says the
    flag ships before the purge job, and a flag added afterwards is one the purge was already
    running without.
    """
    return bool(loan_file.legal_hold)


def refuse_if_held(loan_file: LoanFile, *, action: str) -> None:
    """Raise when ``action`` would destroy data on a held file.

    A FUNCTION RATHER THAN A COMMENT. `a comment is not a guard` — the destruction paths do not exist
    yet, and the thing that makes this real when they do is that they have something to call and a
    test that says what happens when they do not.
    """
    if is_held(loan_file):
        raise LegalHoldError(
            f"{action} is refused: this file is under a legal hold. "
            "Lift the hold first, and record why."
        )


async def held_file_ids(db: AsyncSession, *, company_id: UUID) -> set[UUID]:
    """Every held file for a company, for a purge sweep that works in batches.

    A SET RATHER THAN A PER-FILE CALL, because a purge over ten thousand objects that asked once per
    object is a purge somebody will make faster by skipping the question.
    """
    rows = (
        await db.execute(
            select(LoanFile.id).where(
                LoanFile.company_id == company_id, LoanFile.legal_hold.is_(True)
            )
        )
    ).scalars()
    return set(rows)


__all__ = [
    "EvidenceError",
    "LegalHoldError",
    "evidence_for",
    "held_file_ids",
    "is_held",
    "lift_hold",
    "place_hold",
    "record_delivery_failed",
    "record_received",
    "record_sent",
    "refuse_if_held",
]

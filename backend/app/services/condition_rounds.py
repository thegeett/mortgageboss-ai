"""Creating a condition round from an arriving sheet (LP-905, spec §6).

⚠️ A CONDITION SHEET IS NOT A BORROWER DOCUMENT, and everything here follows from that. It never
becomes a `Document` row, so it never enters classify → extract → needs: it satisfies no need, and a
166-type borrower taxonomy would either mis-file it or push it to the long tail and then ask a
processor why the file has an unrecognised document (ADR-403, and the same reasoning that produced
`AttachmentDisposition.CORRESPONDENCE`). The bytes go to storage directly via `save_at`, which exists
for exactly this — content with no document and no derived path.

THE ROUND IS CREATED BEFORE IT IS READ. `status` starts `PARSING`, `sheet_format` starts `GENERIC`,
and the Celery task fills both in. That ordering is what lets the endpoint answer 202 immediately
with a row the UI can poll (screen S1-02), instead of holding the request open across a PDF parse.

WHAT IS WRITTEN, AND IN WHICH ORDER: the row, then a `ROUND_RECEIVED` condition event, then the
`CONDITION_SHEET_RECEIVED` activity. All three flush and none commits — the caller owns the
transaction, as every service in this repo does.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import ActivityType
from app.models.base import utcnow
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_round import (
    ConditionRound,
    ConditionRoundCompleteness,
    ConditionSourceKind,
)
from app.models.inbound_attachment import AttachmentSafetyState
from app.models.loan_file import LoanFile
from app.services.activity_log import log_activity
from app.services.attachment_safety import assess
from app.storage import get_storage_backend

#: The only content type a condition sheet may be. The spec says PDF only.
PDF_CONTENT_TYPE = "application/pdf"


class ConditionSheetRejected(Exception):
    """The bytes cannot be accepted as a condition sheet, with a reason a processor can act on.

    ⚠️ CARRIES THE REAL REASON RATHER THAN A GENERIC FAILURE (spec §9.8). "That is not a PDF",
    "the PDF is password-protected" and "the file could not be read" lead a processor to three
    different next actions, and collapsing them into one message makes the sheet's arrival a
    dead end.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class SheetBytes:
    """An arriving sheet's bytes, with where they came from."""

    content: bytes
    source_kind: ConditionSourceKind
    #: ⚠️ WHAT THE SENDER SAID THIS WAS — the browser's part header on an upload, the MIME header on
    #: an emailed attachment, or None when nothing claimed anything. It belongs to the CALLER
    #: because `assess`'s mismatch message is a claim about the sender: "this is not what it said it
    #: was". Hardcoding `application/pdf` here made that sentence true for an upload and false for a
    #: forward — a real PDF attached as `application/octet-stream` would be told it "says it is
    #: application/pdf" when it said no such thing.
    declared_content_type: str | None = None
    #: Set for an EMAIL arrival — the attachment the bytes were re-derived from.
    inbound_attachment_id: UUID | None = None


def _storage_path(*, company_id: UUID, loan_file_id: UUID) -> str:
    """A server-controlled path. ⚠️ NEVER derived from the upload's filename.

    `save_at` refuses traversal, but the deeper rule is that a sender's filename is a sender's
    string: a real condition sheet's filename routinely carries the borrower's surname and the loan
    number, so building a path from it would write NPI into the storage layout itself.
    """
    return f"condition-sheets/{company_id}/{loan_file_id}/{uuid4().hex}.pdf"


def _reject_unless_pdf(content: bytes, *, declared_content_type: str | None = None) -> None:
    """Refuse anything that is not a readable, unencrypted PDF.

    ⚠️ THE STATE ALONE IS NOT ENOUGH, AND THIS IS THE TRAP. `assess` returns SAFE for an IMAGE too —
    "an image has no executable structure to strip and no pages to render — it IS the raster" — so a
    PNG passes the safety check cleanly. A condition sheet must be a PDF, so the sniffed type is
    checked as well; relying on the state would accept a screenshot of a sheet and then fail deep in
    the reader, where the message means nothing to a processor.
    """
    outcome = assess(content, declared_content_type=declared_content_type)

    if outcome.state is not AttachmentSafetyState.SAFE:
        raise ConditionSheetRejected(
            outcome.reason or "The file could not be accepted as a condition sheet."
        )
    if outcome.sniffed_content_type != PDF_CONTENT_TYPE:
        raise ConditionSheetRejected(
            f"A condition sheet must be a PDF. This file is "
            f"{outcome.sniffed_content_type or 'of an unrecognised type'}."
        )


async def create_round_from_sheet(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    sheet: SheetBytes,
    completeness: ConditionRoundCompleteness = ConditionRoundCompleteness.FULL,
    actor_user_id: UUID | None = None,
) -> ConditionRound:
    """Store an arriving sheet and open a `PARSING` round for it.

    Shared by both front doors — the upload endpoint and the inbox's "Use as condition sheet" — so
    that an emailed sheet and an uploaded one produce the same row, differing only in `sources`.
    """
    _reject_unless_pdf(sheet.content, declared_content_type=sheet.declared_content_type)

    storage_path = _storage_path(company_id=loan_file.company_id, loan_file_id=loan_file.id)
    await get_storage_backend().save_at(storage_path=storage_path, content=sheet.content)

    now = utcnow()
    source: dict[str, object] = {
        "kind": sheet.source_kind.value,
        "at": now.isoformat(),
        "storage_path": storage_path,
    }
    if actor_user_id is not None:
        source["user_id"] = str(actor_user_id)
    if sheet.inbound_attachment_id is not None:
        source["inbound_attachment_id"] = str(sheet.inbound_attachment_id)

    round_ = ConditionRound(
        company_id=loan_file.company_id,
        loan_file_id=loan_file.id,
        # The FILE's lender. If the sheet turns out to belong to a different one, the reader adds a
        # warning and does not block — a processor who forwarded the wrong letter needs to see it,
        # not to be refused (spec §LP-905).
        lender_id=loan_file.lender_id,
        completeness=completeness,
        sources=[source],
        # ⚠️ NOT NULL WITH NO DEFAULT. Until the sheet is read there is no printed date, so the round
        # is dated by arrival and `date_printed` stays null; the parse task fills it in and a
        # processor may edit it. Omitting it here fails the insert outright — the same shape as the
        # `display_id` defect that hid LP-904's guards.
        # `utcnow()` is `datetime.now(UTC)`, so this date is already UTC. An earlier version wrote
        # `now.astimezone(UTC).date()` as an "assertion of intent" — a provable no-op, and the kind
        # that later persuades a reader the value might NOT be UTC and earns a second conversion
        # somewhere else. The intent belongs in this comment, where it cannot be mistaken for work.
        round_date=now.date(),
        created_by_user_id=actor_user_id,
    )
    db.add(round_)
    await db.flush()

    db.add(
        ConditionEvent(
            company_id=loan_file.company_id,
            loan_file_id=loan_file.id,
            round_id=round_.id,
            kind=ConditionEventKind.ROUND_RECEIVED,
            actor_user_id=actor_user_id,
            # Metadata only — never the sheet's text. `detail` is NPI-capable and excluded from the
            # readonly layer, but that is a reason to keep it clean rather than a licence to fill it.
            detail={"source_kind": sheet.source_kind.value, "bytes": len(sheet.content)},
        )
    )

    await log_activity(
        db,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.CONDITION_SHEET_RECEIVED,
        summary="Condition sheet received",
        actor_user_id=actor_user_id,
        detail={"round_id": str(round_.id), "source_kind": sheet.source_kind.value},
    )
    await db.flush()
    return round_

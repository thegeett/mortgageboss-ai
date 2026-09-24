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
from datetime import date
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.conditions.readers import READER_VERSION, read_pasted_text
from app.conditions.readers.model import ParsedSheet
from app.models.activity_log import ActivityType
from app.models.base import utcnow
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_round import (
    ConditionRound,
    ConditionRoundCompleteness,
    ConditionRoundStatus,
    ConditionSourceKind,
)
from app.models.inbound_attachment import AttachmentSafetyState
from app.models.loan_file import LoanFile
from app.schemas.condition import DraftRowPublic
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


def reject_unless_pdf(content: bytes, *, declared_content_type: str | None = None) -> None:
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
    reject_unless_pdf(sheet.content, declared_content_type=sheet.declared_content_type)

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


def parse_report_for(reader: str, sheet: ParsedSheet) -> dict[str, Any]:
    """What the reader did. ⚠️ Counts, codes and names — no condition text except
    `unassigned_lines`, which LP-904 classifies as NPI and excludes from the readonly layer.

    Lives here rather than in the Celery task because BOTH doors write it now: the task after
    reading a PDF, and the paste service after reading text in the request. Two copies of this dict
    would drift the moment one gained a key — which is the same argument `draft_rows_json` makes
    about `DraftRowPublic`, one level up.
    """
    return {
        "reader": reader,
        "reader_version": READER_VERSION,
        "warnings": list(sheet.warnings),
        "unassigned_lines": list(sheet.unassigned_lines),
        "duplicates_dropped": sheet.duplicates_dropped,
        "ai_used": False,
        # The READER's verdict, carried through rather than recomputed. `ai_used` stays False until
        # LP-908 actually runs a split; the pair is what makes "waiting for AI" a findable state.
        "needs_ai": sheet.needs_ai,
    }


def draft_rows_json(sheet: ParsedSheet) -> list[dict[str, Any]]:
    """The parsed rows as JSON, through the SAME schema the API returns.

    ⚠️ NOT `dataclasses.asdict`. `ParsedRow` holds dates, enums and nested dataclasses, none of
    which JSONB accepts — and a hand-rolled dict here would be a THIRD representation of a row,
    free to drift from `DraftRowPublic`. Going through the response schema means what is stored is
    exactly what is served, by construction.
    """
    return [
        DraftRowPublic.model_validate(row, from_attributes=True).model_dump(mode="json")
        for row in sheet.rows
    ]


async def create_round_from_paste(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    text: str,
    completeness: ConditionRoundCompleteness,
    round_date: date | None = None,
    actor_user_id: UUID | None = None,
) -> ConditionRound:
    """Read conditions pasted from the lender's portal and open a round holding what was found.

    ⚠️ SYNCHRONOUS, UNLIKE EVERY OTHER DOOR, AND THE DIFFERENCE IS REAL RATHER THAN STYLISTIC. An
    upload has bytes to fetch from storage and pages to rasterise; a paste is already text in memory
    and the rules over it are string work. Queuing it would buy nothing and would cost the processor
    a "Reading…" screen for a result that was ready before the response was written.

    ⚠️ ALWAYS `DRAFT`, EVEN WHEN THE RULES COULD NOT SPLIT THE TEXT — a deliberate departure from
    spec §LP-907, which says to answer `PARSING` and queue the AI split. LP-908 does not exist, so
    that branch would enqueue nothing and leave the round in `PARSING` with no worker and no exit:
    the processor sits on screen S1-02 forever. LP-905 recorded a stranded `PARSING` round as the
    one gap it left open; manufacturing that state deliberately would be worse than the honest
    alternative, which is a DRAFT holding whatever the rules did find, with `needs_ai` recorded in
    `parse_report` so LP-908 can find exactly these rounds and finish the job.

    ⚠️ NO PDF, SO NOTHING IS STORED. There are no bytes — `raw_text` on the row IS the source, which
    is why `_storage_path` in the parse task returns None for a pasted round and a re-parse of one
    refuses rather than inventing a file.
    """
    sheet_format, reader, sheet = read_pasted_text(text)

    now = utcnow()
    source: dict[str, object] = {"kind": ConditionSourceKind.PASTE.value, "at": now.isoformat()}
    if actor_user_id is not None:
        source["user_id"] = str(actor_user_id)

    round_ = ConditionRound(
        company_id=loan_file.company_id,
        loan_file_id=loan_file.id,
        lender_id=loan_file.lender_id,
        status=ConditionRoundStatus.DRAFT,
        # ⚠️ REQUIRED FROM THE CALLER, never defaulted here (ADR-404). "Just some" can only ever add
        # and update; "the full list" is what lets a later comparison mean anything. A service that
        # guessed would decide the file's history on the processor's behalf.
        completeness=completeness,
        sheet_format=sheet_format,
        sources=[source],
        # ⚠️ NPI (ADR-405). Stored because it is the SOURCE for a pasted round — LP-908 splits the
        # text the processor actually sent, never a reconstruction from rows the rules may have
        # misread, and §9.3 checks every AI row is a substring of this.
        raw_text=text,
        date_printed=sheet.date_printed,
        # The processor's date wins, then the sheet's if the paste carried a letterhead, then today.
        round_date=round_date or sheet.date_printed or now.date(),
        header=sheet.header or None,
        expiry_dates={
            key: value.isoformat() if value else None for key, value in sheet.expiry_dates.items()
        },
        draft_rows=draft_rows_json(sheet),
        parse_report=parse_report_for(reader, sheet),
        created_by_user_id=actor_user_id,
    )
    db.add(round_)
    await db.flush()

    # ⚠️ BOTH EVENTS, BECAUSE BOTH THINGS HAPPENED. An uploaded sheet arrives (ROUND_RECEIVED) and is
    # read later by the task (ROUND_PARSED); a paste does both inside one request. Emitting only one
    # would leave the round-details history (S1-09) reading differently depending on which door the
    # round came through, for rounds that are otherwise identical.
    for kind, detail in (
        (
            ConditionEventKind.ROUND_RECEIVED,
            # Metadata only — never the pasted text, which is NPI and already on the row.
            {"source_kind": ConditionSourceKind.PASTE.value, "chars": len(text)},
        ),
        (
            ConditionEventKind.ROUND_PARSED,
            {
                "reader": reader,
                "reader_version": READER_VERSION,
                "rows": len(sheet.rows),
                "needs_ai": sheet.needs_ai,
            },
        ),
    ):
        db.add(
            ConditionEvent(
                company_id=loan_file.company_id,
                loan_file_id=loan_file.id,
                round_id=round_.id,
                kind=kind,
                actor_user_id=actor_user_id,
                detail=detail,
            )
        )

    await log_activity(
        db,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.CONDITION_SHEET_RECEIVED,
        summary="Conditions pasted",
        actor_user_id=actor_user_id,
        detail={
            "round_id": str(round_.id),
            "source_kind": ConditionSourceKind.PASTE.value,
            "rows": len(sheet.rows),
        },
    )
    await db.flush()
    return round_

"""Reading an arrived condition sheet, off the request path (LP-905 section 2, spec §6).

The upload endpoint answers `202` with a `PARSING` round and enqueues this. Reading a sheet
rasterises pages and may call a model, so holding the request open across it would block a worker on
a lender's page count — and a processor watching screen S1-02 ("Reading…") is the design that
replaces the wait.

⚠️ IDEMPOTENCY IS A COMPARE-AND-SET, NOT AN EXISTENCE CHECK. Three different events arrive at this
function with the same round id — a Celery redelivery, a manual re-enqueue, and a retry after a
crash — and only the database can say which one won. Keying on "has a ROUND_PARSED event already?"
loses to two workers racing, because both read before either writes; and the events table is
APPEND-ONLY, so a mistake there is permanent rather than merely wrong.

So every field lands in ONE conditional UPDATE guarded on `status = PARSING`, and the event is
written only by whoever the database let through. That removes the half-written state rather than
handling it: there is no window in which `draft_rows` exist under a `PARSING` status, because both
land together or neither does.

⚠️ THE CONSEQUENCE, STATED RATHER THAN IMPLIED: a re-parse after a code fix requires moving the round
back to `PARSING` first. That is a deliberate, auditable act — and the alternative is worse, because
a re-enqueue would otherwise silently overwrite a DRAFT a processor is already reviewing.

NO NPI IN LOGS (spec §9.5): ids, counts, codes and reader names only. Never condition text, a
borrower's name, an address or an amount — and the same rule governs `parse_report.failure_detail`,
which is composed here rather than quoted from the sheet.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from celery import Task
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.conditions.readers import READER_VERSION
from app.conditions.readers.model import ParsedSheet
from app.conditions.sheet_read import (
    ConditionParseError,
    SheetBytesUnavailable,
    sheet_from_bytes,
)
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_round import ConditionRound, ConditionRoundStatus
from app.services.condition_rounds import draft_rows_json, parse_report_for
from app.services.condition_split import (
    SPLIT_VERSION,
    ConditionSplitUnavailable,
    split_conditions,
)
from app.storage import StorageError, get_storage_backend
from app.tasks.base import run_async, task_session
from app.tasks.celery_app import celery_app
from app.tasks.retry import MAX_RETRIES, retry_or_terminal

logger = structlog.get_logger(__name__)

#: A sheet is small work next to a document pipeline, but a scanned multi-page letter still
#: rasterises. Its own limits rather than the global 180s, which is below what OCR can need.
PARSE_SOFT_LIMIT_SECONDS = 300
PARSE_HARD_LIMIT_SECONDS = 360


def _storage_path(round_: ConditionRound) -> str | None:
    """The newest arrival's stored bytes. `sources` is a list because a paste can gain a PDF."""
    for source in reversed(round_.sources or []):
        path = source.get("storage_path")
        if isinstance(path, str) and path:
            return path
    return None


async def _read_sheet(round_: ConditionRound) -> tuple[str, ParsedSheet]:
    """Fetch the round's stored bytes, then read them.

    The FETCHING half is what belongs to the task: `attach-pdf` already holds its upload in memory
    and shares only `sheet_from_bytes` (see `app.conditions.sheet_read`).
    """
    path = _storage_path(round_)
    if path is None:
        raise SheetBytesUnavailable(
            "This round has no stored file to read. Upload the condition sheet again."
        )

    try:
        content = await get_storage_backend().read(path)
    except StorageError as exc:
        raise SheetBytesUnavailable(
            "The stored condition sheet could not be retrieved. Upload it again."
        ) from exc

    return sheet_from_bytes(content)


async def _settle(
    db: AsyncSession,
    *,
    round_id: UUID,
    values: dict[str, Any],
    kind: ConditionEventKind,
    detail: dict[str, Any],
) -> bool:
    """Write the outcome and its event, or do nothing at all.

    ⚠️ ONE CONDITIONAL UPDATE, GUARDED ON `PARSING`. Whoever the database lets through owns the
    outcome; a second delivery matches no row, writes nothing, and appends no event. A round the
    processor DISCARDED while it was being read is also protected, because it is no longer PARSING.
    """
    result = await db.execute(
        update(ConditionRound)
        .where(
            ConditionRound.id == round_id,
            ConditionRound.status == ConditionRoundStatus.PARSING,
        )
        .values(**values)
        .returning(ConditionRound.id, ConditionRound.company_id, ConditionRound.loan_file_id)
    )
    won = result.one_or_none()
    if won is None:
        await db.rollback()
        return False

    _, company_id, loan_file_id = won
    db.add(
        ConditionEvent(
            company_id=company_id,
            loan_file_id=loan_file_id,
            round_id=round_id,
            kind=kind,
            detail=detail,
        )
    )
    await db.commit()
    return True


async def parse_round(db: AsyncSession, round_id: UUID) -> None:
    """Read one round into draft rows, on a session the CALLER owns.

    ⚠️ SPLIT FROM THE SESSION-OPENING WRAPPER SO IT CAN BE TESTED AT ALL. `task_session()` builds its
    own engine, and the suite isolates each test inside a transaction that is never committed — so a
    task opening its own session cannot see the round the test just created. Every task test in this
    repo calls the inner function for that reason, and a test that drove the Celery wrapper would be
    exercising a different database from the one it set up.
    """
    round_ = await db.scalar(select(ConditionRound).where(ConditionRound.id == round_id))
    if round_ is None:
        logger.info("condition_parse_round_missing", round_id=str(round_id))
        return
    if round_.status is not ConditionRoundStatus.PARSING:
        # Already settled, or discarded while this was queued. Not an error.
        logger.info(
            "condition_parse_not_pending", round_id=str(round_id), status=round_.status.value
        )
        return

    try:
        reader, sheet = await _read_sheet(round_)
    except ConditionParseError as exc:
        settled = await _settle(
            db,
            round_id=round_id,
            values={
                "status": ConditionRoundStatus.PARSE_FAILED,
                "parse_report": {
                    "reader": None,
                    "reader_version": READER_VERSION,
                    "warnings": [],
                    "unassigned_lines": [],
                    "duplicates_dropped": 0,
                    "ai_used": False,
                    # A read that never reached a reader has no verdict to carry. False, not the
                    # absence of the key, so the shape matches every other `parse_report`.
                    "needs_ai": False,
                    "failure_kind": exc.failure_kind,
                    "failure_detail": exc.detail,
                },
            },
            kind=ConditionEventKind.ROUND_PARSE_FAILED,
            detail={"failure_kind": exc.failure_kind},
        )
        logger.warning(
            "condition_parse_failed",
            round_id=str(round_id),
            failure_kind=exc.failure_kind,
            settled=settled,
        )
        return

    settled = await _settle(
        db,
        round_id=round_id,
        values={
            "status": ConditionRoundStatus.DRAFT,
            "sheet_format": sheet.sheet_format,
            "date_printed": sheet.date_printed,
            "header": sheet.header or None,
            "expiry_dates": {
                key: value.isoformat() if value else None
                for key, value in sheet.expiry_dates.items()
            },
            "draft_rows": draft_rows_json(sheet),
            "parse_report": parse_report_for(reader, sheet),
        },
        kind=ConditionEventKind.ROUND_PARSED,
        detail={
            "reader": reader,
            "reader_version": READER_VERSION,
            "rows": len(sheet.rows),
            "duplicates_dropped": sheet.duplicates_dropped,
        },
    )
    logger.info(
        "condition_parse_done",
        round_id=str(round_id),
        reader=reader,
        rows=len(sheet.rows),
        warnings=len(sheet.warnings),
        unassigned=len(sheet.unassigned_lines),
        settled=settled,
    )


async def split_round(db: AsyncSession, round_id: UUID) -> None:
    """Split a pasted round the rules could not read, on a session the CALLER owns (LP-908 §2).

    ⚠️ THIS ONE *DOES* REUSE `_settle`, AND THE ENRICH MERGE DELIBERATELY DOES NOT. The difference is
    not taste: this genuinely IS a parse settling a round that is `PARSING`, so the compare-and-set
    guarded on that status means exactly what it says — a redelivery, a manual re-enqueue and a
    crash-retry all converge, and a round the processor DISCARDED while the model was working is
    protected because it is no longer `PARSING`. Enrich borrows none of that, because there the
    round is `DRAFT` or `IMPORTED` with content a processor may already be reviewing.

    ⚠️ THE INPUT IS `raw_text`, WHICH IS WHY A PASTED ROUND STORES IT. Splitting a reconstruction of
    the rows the rules half-read would feed the model our guess instead of the lender's page — and
    §9.3's substring check is against this exact text.
    """
    round_ = await db.scalar(select(ConditionRound).where(ConditionRound.id == round_id))
    if round_ is None:
        logger.info("condition_split_round_missing", round_id=str(round_id))
        return
    if round_.status is not ConditionRoundStatus.PARSING:
        # Already settled, or discarded while this was queued. Not an error.
        logger.info(
            "condition_split_not_pending", round_id=str(round_id), status=round_.status.value
        )
        return

    text = round_.raw_text
    if not text:
        settled = await _settle(
            db,
            round_id=round_id,
            values={
                "status": ConditionRoundStatus.PARSE_FAILED,
                "parse_report": {
                    **(round_.parse_report or {}),
                    "failure_kind": "no_text",
                    "failure_detail": (
                        "This round has no text to read. Paste the conditions again."
                    ),
                },
            },
            kind=ConditionEventKind.ROUND_PARSE_FAILED,
            detail={"failure_kind": "no_text"},
        )
        logger.warning("condition_split_no_text", round_id=str(round_id), settled=settled)
        return

    try:
        outcome = await split_conditions(text)
    except ConditionSplitUnavailable as exc:
        settled = await _settle(
            db,
            round_id=round_id,
            values={
                "status": ConditionRoundStatus.PARSE_FAILED,
                "parse_report": {
                    **(round_.parse_report or {}),
                    "failure_kind": "ai_unavailable",
                    "failure_detail": exc.detail,
                },
            },
            kind=ConditionEventKind.ROUND_PARSE_FAILED,
            detail={"failure_kind": "ai_unavailable"},
        )
        logger.warning("condition_split_failed", round_id=str(round_id), settled=settled)
        return

    report = parse_report_for("split", outcome.sheet)
    # ⚠️ `ai_used` TRUE ONLY HERE. `parse_report_for` hardcodes False because it is written for the
    # rule readers, and the pair (needs_ai, ai_used) is what makes "waiting for the AI" and "the AI
    # has run" distinguishable states rather than one ambiguous flag.
    report["ai_used"] = True
    report["reader_version"] = SPLIT_VERSION
    report["rejected_rows"] = outcome.rejected

    settled = await _settle(
        db,
        round_id=round_id,
        values={
            "status": ConditionRoundStatus.DRAFT,
            "draft_rows": draft_rows_json(outcome.sheet),
            "parse_report": report,
        },
        kind=ConditionEventKind.ROUND_PARSED,
        detail={
            "reader": "split",
            "reader_version": SPLIT_VERSION,
            "rows": len(outcome.sheet.rows),
            "rejected": outcome.rejected,
        },
    )
    logger.info(
        "condition_split_settled",
        round_id=str(round_id),
        rows=len(outcome.sheet.rows),
        rejected=outcome.rejected,
        unassigned=len(outcome.sheet.unassigned_lines),
        settled=settled,
    )


async def _run_parse(round_id: str) -> None:
    try:
        round_pk = UUID(round_id)
    except ValueError:
        return
    async with task_session() as db:
        await parse_round(db, round_pk)


async def _run_split(round_id: str) -> None:
    try:
        round_pk = UUID(round_id)
    except ValueError:
        return
    async with task_session() as db:
        await split_round(db, round_pk)


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="conditions.parse_condition_round",
    max_retries=MAX_RETRIES,
    soft_time_limit=PARSE_SOFT_LIMIT_SECONDS,
    time_limit=PARSE_HARD_LIMIT_SECONDS,
)
def parse_condition_round(self: Task, round_id: str) -> None:
    """Celery task: read one arrived condition sheet into draft rows.

    The parse itself never raises — a typed failure is recorded on the round, which is what the
    processor sees. This bounded retry covers a transient error AROUND it (a database blip, storage
    briefly unreachable), and on exhaustion leaves the round in `PARSING` rather than inventing a
    terminal state the code did not reach.

    ⚠️ EXHAUSTION IS THE ONE GAP THIS TICKET LEAVES OPEN, and it is recorded rather than hidden: a
    round stranded in `PARSING` has no exit, and a processor sits on S1-02 indefinitely. The row
    carries `created_at` and `status`, so "PARSING for more than N minutes" is a query rather than a
    schema change — a reaper is buildable and deliberately not built here.
    """
    retry_or_terminal(
        self,
        lambda: run_async(_run_parse(round_id)),
        on_exhausted=lambda exc: logger.error(
            "condition_parse_exhausted", round_id=round_id, error_type=type(exc).__name__
        ),
        event="condition_parse_exhausted",
    )


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="conditions.split_condition_round",
    max_retries=MAX_RETRIES,
    soft_time_limit=PARSE_SOFT_LIMIT_SECONDS,
    time_limit=PARSE_HARD_LIMIT_SECONDS,
)
def split_condition_round(self: Task, round_id: str) -> None:
    """Celery task: split a pasted round the rules could not read (LP-908 §2).

    The same bounded-retry shape as the parse: the split itself never raises — an unreachable model
    is recorded on the round as a typed failure the processor can act on — so this covers a
    transient error AROUND it, and on exhaustion leaves the round in `PARSING` rather than inventing
    a terminal state the code never reached.

    ⚠️ THE SAME STRANDED-`PARSING` GAP LP-905 RECORDED APPLIES HERE, and it is the reason LP-907 did
    not open this state before the worker existed. It is buildable as a query — `status` plus
    `created_at` — and is still deliberately not built.
    """
    retry_or_terminal(
        self,
        lambda: run_async(_run_split(round_id)),
        on_exhausted=lambda exc: logger.error(
            "condition_split_exhausted", round_id=round_id, error_type=type(exc).__name__
        ),
        event="condition_split_exhausted",
    )


__all__ = ["parse_condition_round", "split_condition_round"]

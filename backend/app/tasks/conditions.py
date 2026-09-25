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
from kombu.exceptions import OperationalError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.conditions.limits import PARSE_HARD_LIMIT_SECONDS, PARSE_SOFT_LIMIT_SECONDS
from app.conditions.readers import READER_VERSION
from app.conditions.readers.model import ParsedSheet
from app.conditions.sheet_read import (
    ConditionParseError,
    SheetBytesUnavailable,
    sheet_from_bytes,
)
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_round import ConditionRound, ConditionRoundStatus
from app.services.condition_rounds import (
    ENQUEUE_FAILED_DETAIL,
    draft_rows_json,
    parse_report_for,
)
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


def _storage_path(round_: ConditionRound) -> str | None:
    """The newest arrival's stored bytes. `sources` is a list because a paste can gain a PDF."""
    for source in reversed(round_.sources or []):
        path = source.get("storage_path")
        if isinstance(path, str) and path:
            return path
    return None


async def _read_sheet(round_: ConditionRound) -> tuple[str, ParsedSheet, str]:
    """Fetch the round's stored bytes, then read them: reader name, sheet, and the source text.

    The FETCHING half is what belongs to the task: `attach-pdf` already holds its upload in memory
    and shares only `sheet_from_bytes` (see `app.conditions.sheet_read`).

    The third value is the lender's page as the reader saw it, persisted to `raw_text` so a sheet the
    rules cannot split can be handed to the AI. Before this, only a paste ever stored text, so
    chaining the split for a PDF door failed on "no text to read".
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
    kind: ConditionEventKind | None,
    detail: dict[str, Any],
) -> bool:
    """Write the outcome and its event, or do nothing at all.

    ⚠️ ONE CONDITIONAL UPDATE, GUARDED ON `PARSING`. Whoever the database lets through owns the
    outcome; a second delivery matches no row, writes nothing, and appends no event. A round the
    processor DISCARDED while it was being read is also protected, because it is no longer PARSING.

    ⚠️ `kind=None` WRITES NO EVENT, AND EXACTLY ONE CALLER WANTS THAT. A sheet the rules could not
    split is handed to the AI: its rows and text are stored, the status STAYS `PARSING`, and the
    split task emits `ROUND_PARSED` when it settles. Emitting one here too would put two parses in a
    round's history for one read — which LP-907 already shipped once and had to correct, because
    screen S1-09 renders that history and a processor would see a parse that never happened.

    The compare-and-set is unchanged by it: the guard is what makes the write safe, not the event.
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
    if kind is not None:
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


async def _queue_split_or_fail(
    db: AsyncSession, *, round_id: UUID, parse_report: dict[str, Any]
) -> None:
    """Queue the AI split, and settle the round FAILED if the broker will not take it.

    ⚠️ THE FIX THIS TICKET EXISTS FOR, REINTRODUCED BY ANOTHER ROUTE AND CAUGHT IN REVIEW. The
    commit that made the split reachable from every door called `.delay()` bare. The round is
    committed `PARSING` BEFORE the enqueue — correctly, since a worker that picked it up first
    would find no row — so a broker that is down left exactly the permanent-`PARSING` round this
    work set out to eliminate, arriving by a third path instead of the original two.

    ⚠️ AND NOTHING WOULD HAVE SHOWN IT. `OperationalError` appeared in one test file in the whole
    backend suite, covering the one enqueue that was already guarded: "the only door with coverage
    was the only door that worked", now true of the enqueues inside the fix for it.

    ⚠️ IT SETTLES RATHER THAN RE-RAISING, WHICH FORGOES CELERY'S RETRY ON PURPOSE. Letting the
    error escape would reach `retry_or_terminal`, which retries — and a retry genuinely would
    re-parse and re-enqueue, because the round is still `PARSING` so the compare-and-set wins
    again. But `on_exhausted` only LOGS, so once the retries run out the round sits `PARSING`
    forever with no exit and no reason recorded. A typed `PARSE_FAILED` is something a processor
    can act on immediately; a spinner that ends in silence six minutes later is not. The paste
    door made this same trade and states the same reason.

    The compare-and-set still guards the write: a processor who DISCARDED the round between the
    enqueue attempt and this settle is protected, because it is no longer `PARSING`.
    """
    try:
        split_condition_round.delay(str(round_id))
    except OperationalError:
        # ⚠️ SPECIFIC, NEVER A BARE `except Exception` (spec §9.8), AND FROM `kombu` RATHER THAN
        # `sqlalchemy.exc`. Two unrelated classes share this name; `.delay()` raises kombu's when
        # the broker refuses the message, so catching SQLAlchemy's would be a guard that never
        # fires — verified against the paste door, which imports the same one.
        #
        # Anything else is a bug and belongs in the error handler, not filed as a parse failure
        # that blames the lender's sheet.
        settled = await _settle(
            db,
            round_id=round_id,
            values={
                "status": ConditionRoundStatus.PARSE_FAILED,
                "parse_report": {
                    **parse_report,
                    "failure_kind": "enqueue_failed",
                    "failure_detail": ENQUEUE_FAILED_DETAIL,
                },
            },
            kind=ConditionEventKind.ROUND_PARSE_FAILED,
            detail={"failure_kind": "enqueue_failed"},
        )
        # Ids and counts only (spec §9.5) — never the sheet's text.
        logger.warning("condition_split_enqueue_failed", round_id=str(round_id), settled=settled)


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
        reader, sheet, source_text = await _read_sheet(round_)
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

    # ⚠️ `raw_text` IS WRITTEN ON BOTH PATHS, and that is what makes a PDF splittable at all.
    # `split_round` reads it, and before LP-908's review only the paste door ever wrote it — so
    # handing an uploaded or forwarded sheet to the AI settled it `PARSE_FAILED` with "This round has
    # no text to read. Paste the conditions again.", telling a processor to paste a letter they had
    # just uploaded. It is stored on the DRAFT path too, so a reparse after a reader fix has the page
    # without re-fetching the PDF.
    #
    # ⚠️ THIS IS A RETENTION CHANGE, NOT AN EXPOSURE ONE, and the distinction is worth stating
    # because the two are easy to conflate (LP-908 review). No NPI reaches anywhere it could not
    # reach before: `raw_text` is in the readonly layer's EXCLUDED set, migration `d1f4b8c25e93`
    # drops it by name, and the view projects only `(raw_text IS NOT NULL) AS has_raw_text`. What
    # DID change is how much is kept: the lender's full page is now at rest for every uploaded and
    # forwarded round, where before only pasted ones carried it. Reparse is what justifies holding
    # it; if that ever goes away, so should this.
    #
    # ⚠️ AND `has_raw_text` NOW MEANS SOMETHING ELSE. It used to separate pasted rounds from
    # uploaded ones, because only a paste wrote the column. From this commit it is true for nearly
    # every parsed round, so any readonly query that leaned on it to count pastes is silently
    # answering a different question. `sources[].kind` is the field that still means what that one
    # used to.
    values: dict[str, Any] = {
        "sheet_format": sheet.sheet_format,
        "date_printed": sheet.date_printed,
        "header": sheet.header or None,
        "expiry_dates": {
            key: value.isoformat() if value else None for key, value in sheet.expiry_dates.items()
        },
        "draft_rows": draft_rows_json(sheet),
        "parse_report": parse_report_for(reader, sheet),
        "raw_text": source_text,
    }

    if sheet.needs_ai:
        # ⚠️ STAYS `PARSING`, AND EMITS NOTHING. The rules could not tell where one condition ends
        # and the next begins, so the AI split owns the terminal state — and its own compare-and-set
        # is guarded on `PARSING`, which only holds if this write leaves it there. Settling to `DRAFT`
        # first would both hand a processor rows the rules admit are unsplit AND make the split's
        # guard miss, so the queued task would log "not pending" and do nothing.
        #
        # No `ROUND_PARSED` either: the split emits it when it settles, and two parses in one round's
        # history for one read is the defect LP-907 shipped and had to correct — screen S1-09 renders
        # that history, so a processor would see a parse that never happened.
        settled = await _settle(db, round_id=round_id, values=values, kind=None, detail={})
        if settled:
            # After the commit, for the reason every enqueue in this repo gives: a worker that picked
            # the round up before the transaction landed would find no row. Only if we WON the
            # compare-and-set — a redelivery that lost must not queue a second split.
            await _queue_split_or_fail(db, round_id=round_id, parse_report=values["parse_report"])
        logger.info(
            "condition_parse_needs_ai",
            round_id=str(round_id),
            reader=reader,
            rows=len(sheet.rows),
            settled=settled,
        )
        return

    settled = await _settle(
        db,
        round_id=round_id,
        values={**values, "status": ConditionRoundStatus.DRAFT},
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

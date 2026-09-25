"""Reading an arrived condition sheet (LP-905 section 2, spec §6).

⚠️ THESE DRIVE `parse_round`, NOT THE CELERY TASK, and that is deliberate rather than convenient.
`task_session()` builds its own engine, and the suite isolates each test inside a transaction that
is never committed — so a task opening its own session would not see the round the test just
created, and every assertion here would be about an empty database. `test_document_claim_lp637.py`
calls `_claim_for_processing` directly for the same reason.

THE PROPERTY THAT MATTERS MOST IS THAT NOTHING IS HALF-WRITTEN. Every field lands in one conditional
UPDATE guarded on `status = PARSING`, so a second delivery, a discarded round, and a crash mid-parse
all leave the row exactly as they found it — and the events table is APPEND-ONLY, so a duplicate
event could never be taken back.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.conditions import sheet_read
from app.conditions.sheet_read import SheetUnreadable
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_round import (
    ConditionRound,
    ConditionRoundStatus,
    ConditionSheetFormat,
    ConditionSourceKind,
)
from app.services.condition_rounds import SheetBytes, create_round_from_sheet
from app.tasks.conditions import parse_round
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.fixture_helpers import UWM_ROUND_1
from tests.conditions.uwm_pdf_fixture import render_text_pdf, render_uwm_pdf
from tests.models.conftest_helpers import make_company, make_loan_file


async def _round(
    db: AsyncSession,
    *,
    content: bytes | None = None,
    source_kind: ConditionSourceKind = ConditionSourceKind.PDF_UPLOAD,
) -> ConditionRound:
    company = await make_company(db)
    loan_file = await make_loan_file(db, company=company)
    return await create_round_from_sheet(
        db,
        loan_file=loan_file,
        sheet=SheetBytes(
            content=content if content is not None else render_uwm_pdf(UWM_ROUND_1),
            source_kind=source_kind,
        ),
    )


async def _events(db: AsyncSession, round_id: object) -> list[ConditionEvent]:
    result = await db.execute(
        select(ConditionEvent).where(ConditionEvent.round_id == round_id)  # type: ignore[arg-type]
    )
    return list(result.scalars().all())


# --------------------------------------------------------------------------- #
# The success path — LP-905's done-when
# --------------------------------------------------------------------------- #


async def test_a_uwm_pdf_becomes_a_draft_with_eleven_rows(db_session: AsyncSession) -> None:
    """Spec §LP-905's done-when, stated directly: "uploading a PDF built from `uwm_round1` produces
    a DRAFT round with 11 draft rows, its header and expiry dates"."""
    round_ = await _round(db_session)

    await parse_round(db_session, round_.id)
    await db_session.refresh(round_)

    assert round_.status is ConditionRoundStatus.DRAFT
    assert round_.sheet_format is ConditionSheetFormat.UWM_APPROVAL_LETTER
    assert round_.draft_rows is not None
    assert len(round_.draft_rows) == 11
    assert round_.header is not None
    assert round_.expiry_dates
    assert round_.expiry_dates["close_by"] == "2026-10-30"


async def test_the_draft_rows_are_stored_as_the_api_serves_them(db_session: AsyncSession) -> None:
    """⚠️ STORED THROUGH `DraftRowPublic`, NOT `dataclasses.asdict`. A hand-rolled dict would be a
    third representation of a row, free to drift from what the endpoint returns; going through the
    response schema makes stored and served identical by construction — and JSONB accepts none of
    the dates, enums and nested dataclasses a `ParsedRow` actually holds."""
    round_ = await _round(db_session)

    await parse_round(db_session, round_.id)
    await db_session.refresh(round_)

    assert round_.draft_rows is not None
    first = round_.draft_rows[0]
    assert first["lender_code"] == "1228"
    assert first["bucket_kind"] == "prior_to_docs"
    assert isinstance(first["confidence"], float)
    # A note's date must have survived as an ISO string rather than a `date` JSONB cannot hold.
    noted = next(r for r in round_.draft_rows if r["lender_code"] == "6132")
    assert noted["underwriter_notes"][0]["date"] == "2026-08-28"


async def test_the_parse_report_names_the_reader_and_its_version(
    db_session: AsyncSession,
) -> None:
    """Spec §9.6 — readers are versioned so a re-parse is reproducible, and the review screen
    renders it as "Read by rules (uwm v1) — no AI"."""
    round_ = await _round(db_session)

    await parse_round(db_session, round_.id)
    await db_session.refresh(round_)

    assert round_.parse_report["reader"] == "uwm"
    assert round_.parse_report["reader_version"] == "v1"
    assert round_.parse_report["ai_used"] is False
    assert round_.parse_report["unassigned_lines"] == []


async def test_a_successful_parse_writes_exactly_one_round_parsed_event(
    db_session: AsyncSession,
) -> None:
    """Spec §9.7: every state change writes a `condition_event` — and the detail is metadata only."""
    round_ = await _round(db_session)

    await parse_round(db_session, round_.id)

    kinds = [e.kind for e in await _events(db_session, round_.id)]
    assert kinds == [ConditionEventKind.ROUND_RECEIVED, ConditionEventKind.ROUND_PARSED]

    parsed = next(
        e for e in await _events(db_session, round_.id) if e.kind is ConditionEventKind.ROUND_PARSED
    )
    assert parsed.detail["rows"] == 11
    assert parsed.detail["reader"] == "uwm"


# --------------------------------------------------------------------------- #
# Idempotency — the part the append-only table makes unforgiving
# --------------------------------------------------------------------------- #


async def test_a_second_delivery_writes_nothing_and_appends_no_event(
    db_session: AsyncSession,
) -> None:
    """⚠️ THE COMPARE-AND-SET, EXERCISED. A Celery redelivery arrives at the same function with the
    same round id. The guard is `status = PARSING`, so the second attempt matches no row, writes
    nothing, and appends no event — which matters more than usual because `condition_events` is
    append-only and a duplicate could never be taken back."""
    round_ = await _round(db_session)

    await parse_round(db_session, round_.id)
    await parse_round(db_session, round_.id)
    await db_session.refresh(round_)

    kinds = [e.kind for e in await _events(db_session, round_.id)]
    assert kinds.count(ConditionEventKind.ROUND_PARSED) == 1
    assert round_.status is ConditionRoundStatus.DRAFT


async def test_a_discarded_round_is_not_clobbered(db_session: AsyncSession) -> None:
    """⚠️ A PROCESSOR CAN DISCARD A ROUND WHILE IT IS BEING READ. The guard protects that too: the
    round is no longer PARSING, so the parse settles nothing and the discard stands. Without it, a
    slow parse would resurrect a round the processor had thrown away."""
    round_ = await _round(db_session)
    round_.status = ConditionRoundStatus.DISCARDED
    await db_session.flush()

    await parse_round(db_session, round_.id)
    await db_session.refresh(round_)

    assert round_.status is ConditionRoundStatus.DISCARDED
    assert round_.draft_rows is None
    kinds = [e.kind for e in await _events(db_session, round_.id)]
    assert ConditionEventKind.ROUND_PARSED not in kinds


async def test_a_crash_mid_parse_leaves_the_round_untouched(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """⚠️ THE TEST THE REVIEW ASKED FOR FIRST, and the design turns it into a stronger assertion.

    A task that raised after writing `draft_rows` but before the status moved would leave a
    half-written round, and the retry would have to decide whether to trust it. Writing every field
    in ONE conditional UPDATE removes that state rather than handling it: there is no window in
    which `draft_rows` exist under a `PARSING` status. So the assertion is not "the half-written
    round is recoverable" but "nothing was written at all".
    """

    def _explode(_content: bytes) -> object:
        raise RuntimeError("reader blew up mid-parse")

    # ⚠️ PATCHED WHERE THE NAME NOW LIVES, AND THE MOVE BROKE THIS ONCE. LP-907 lifted the read out
    # of this task into `app.conditions.sheet_read`, and the old `setattr(task_module, ...)` went on
    # naming an attribute the module no longer had — `AttributeError`, caught here rather than by
    # quietly patching nothing. A monkeypatch is only as good as the binding it targets.
    monkeypatch.setattr(sheet_read, "lines_from_pdf", _explode)
    round_ = await _round(db_session)

    with pytest.raises(RuntimeError):
        await parse_round(db_session, round_.id)

    await db_session.refresh(round_)
    assert round_.status is ConditionRoundStatus.PARSING
    assert round_.draft_rows is None
    assert round_.parse_report == {}
    kinds = [e.kind for e in await _events(db_session, round_.id)]
    assert kinds == [ConditionEventKind.ROUND_RECEIVED]


# --------------------------------------------------------------------------- #
# The sheet the rules cannot split — every door, not just the paste one
# --------------------------------------------------------------------------- #

#: A page with no codes, no numbering and no headings. `test_prose_with_no_structure_at_all_needs_ai`
#: is what establishes that the generic reader answers `needs_ai` for this shape; rendered as a PDF
#: it is the only way an UPLOADED or FORWARDED sheet reaches that branch, because all three §7
#: fixtures are UWM letters the rules read cleanly.
PROSE_SHEET = "Please send over whatever you have for this file when you get a chance."


@pytest.mark.parametrize(
    "source_kind",
    [ConditionSourceKind.PDF_UPLOAD, ConditionSourceKind.EMAIL],
    ids=["upload", "forward"],
)
async def test_a_pdf_the_rules_cannot_split_queues_the_ai_and_stays_parsing(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, source_kind: ConditionSourceKind
) -> None:
    """⚠️ THE ORPHAN THIS TICKET EXISTS TO CLOSE, AT BOTH DOORS THAT HAD IT.

    `split_condition_round.delay()` was called from exactly one site — inside `paste_conditions` —
    so a sheet that ARRIVED as a PDF and whose reader asked for the AI was settled and then waited
    for a task nobody queued. Permanent, on two of three doors, and invisible: the only door with
    coverage was the only door that worked.

    Both source kinds go through `create_round_from_sheet` and then this one task, so the parse is
    genuinely where the fix belongs — but they are parameterised rather than collapsed to one case
    because "it works for an upload" is what was believed about the forward door too.

    The status is the load-bearing half. `split_round` reuses `_settle`, whose compare-and-set is
    guarded on `PARSING`; settling to `DRAFT` here would make that guard miss, so the queued split
    would log "not pending" and do nothing — a round stranded with rows the rules admit are unsplit.
    """
    from app.tasks import conditions as task_module

    enqueued: list[str] = []
    monkeypatch.setattr(
        task_module.split_condition_round, "delay", lambda round_id: enqueued.append(round_id)
    )

    round_ = await _round(db_session, content=render_text_pdf(PROSE_SHEET), source_kind=source_kind)

    await parse_round(db_session, round_.id)
    await db_session.refresh(round_)

    assert round_.parse_report["needs_ai"] is True
    assert round_.parse_report["ai_used"] is False
    assert round_.status is ConditionRoundStatus.PARSING
    assert enqueued == [str(round_.id)], "a PARSING round with nothing queued is stranded"


@pytest.mark.parametrize(
    "source_kind",
    [ConditionSourceKind.PDF_UPLOAD, ConditionSourceKind.EMAIL],
    ids=["upload", "forward"],
)
async def test_the_lenders_page_is_persisted_so_the_split_has_something_to_read(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, source_kind: ConditionSourceKind
) -> None:
    """⚠️ QUEUEING THE SPLIT WAS NOT ENOUGH ON ITS OWN, and this is the half that is easy to miss.

    `split_round` reads `round_.raw_text`, which only the paste door ever wrote. So a fix that just
    called `delay()` for an uploaded sheet would hand the task an empty column, hit its `if not
    text:` branch, and settle the round `PARSE_FAILED` with "This round has no text to read. Paste
    the conditions again." — telling a processor to paste a letter they had just uploaded.

    Asserting the text is a SUBSTRING of the page rather than equal to it: `Line.text` for PDF input
    is word boxes joined by single spaces, so the rendered page round-trips with its own spacing.
    Equality would pin the fixture's font metrics, which are this renderer's, not a lender's.
    """
    from app.tasks import conditions as task_module

    monkeypatch.setattr(task_module.split_condition_round, "delay", lambda round_id: None)

    round_ = await _round(db_session, content=render_text_pdf(PROSE_SHEET), source_kind=source_kind)

    await parse_round(db_session, round_.id)
    await db_session.refresh(round_)

    assert round_.raw_text is not None
    assert "whatever you have for this file" in round_.raw_text


async def test_handing_a_sheet_to_the_ai_writes_no_parsed_event(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """⚠️ ONE READ MUST LEAVE ONE PARSE IN THE HISTORY, and LP-907 shipped the other version once.

    The split emits `ROUND_PARSED` when it settles. Emitting one here too would put two parses in a
    round's history for a single read — and screen S1-09 renders that history, so a processor would
    see a parse that never happened. `_settle(kind=None)` exists for this caller alone.
    """
    from app.tasks import conditions as task_module

    monkeypatch.setattr(task_module.split_condition_round, "delay", lambda round_id: None)

    round_ = await _round(db_session, content=render_text_pdf(PROSE_SHEET))

    await parse_round(db_session, round_.id)

    kinds = [e.kind for e in await _events(db_session, round_.id)]
    assert kinds == [ConditionEventKind.ROUND_RECEIVED]


@pytest.mark.parametrize(
    "source_kind",
    [ConditionSourceKind.PDF_UPLOAD, ConditionSourceKind.EMAIL],
    ids=["upload", "forward"],
)
async def test_a_broker_that_refuses_the_split_fails_the_round_rather_than_stranding_it(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, source_kind: ConditionSourceKind
) -> None:
    """⚠️ THE STRANDED ROUND THIS TICKET ELIMINATED, ARRIVING BY A THIRD ROUTE (LP-908 review).

    Queueing the split from every door closed two paths to a permanent `PARSING` round and opened
    one: the row is committed BEFORE `.delay()` is reached, so a broker that is down leaves a round
    with rows, text, and no task — and the first version of this fix called `.delay()` bare.

    Asserting the enqueue proves the CALL, not the delivery. The tests above pass in exactly this
    scenario, because the call was made. Only this one distinguishes "queued" from "queued and
    accepted", which is the distinction the processor experiences.

    ⚠️ `kombu`'s `OperationalError`, NOT `sqlalchemy.exc`'s. Two unrelated exception classes share
    the name, and catching the wrong one would be a guard that never fires while every test here
    still passed — the mutation run is what proves this one does.
    """
    from app.tasks import conditions as task_module
    from kombu.exceptions import OperationalError

    def _broker_down(_round_id: str) -> None:
        raise OperationalError("broker unreachable")

    monkeypatch.setattr(task_module.split_condition_round, "delay", _broker_down)

    round_ = await _round(db_session, content=render_text_pdf(PROSE_SHEET), source_kind=source_kind)

    await parse_round(db_session, round_.id)
    await db_session.refresh(round_)

    assert round_.status is ConditionRoundStatus.PARSE_FAILED
    assert round_.parse_report["failure_kind"] == "enqueue_failed"
    assert "try again" in round_.parse_report["failure_detail"]
    # The reader's own verdict survives the failure: `needs_ai` is still what the rules answered.
    assert round_.parse_report["needs_ai"] is True
    kinds = [e.kind for e in await _events(db_session, round_.id)]
    assert ConditionEventKind.ROUND_PARSE_FAILED in kinds


async def test_a_broker_failure_quotes_nothing_from_the_sheet(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec §9.5: `failure_detail` is COMPOSED. It lives inside `parse_report`, which the readonly
    layer drops whole rather than scrubs — so text quoted here would be NPI at rest in a column
    nobody can inspect to find it."""
    from app.tasks import conditions as task_module
    from kombu.exceptions import OperationalError

    def _broker_down(_round_id: str) -> None:
        raise OperationalError("broker unreachable")

    monkeypatch.setattr(task_module.split_condition_round, "delay", _broker_down)

    round_ = await _round(db_session, content=render_text_pdf(PROSE_SHEET))

    await parse_round(db_session, round_.id)
    await db_session.refresh(round_)

    detail = round_.parse_report["failure_detail"]
    assert "whatever you have for this file" not in detail
    # Nor does the broker's own message leak: that is operational text, not something a processor
    # can act on, and "broker unreachable" in front of a loan processor is noise.
    assert "broker" not in detail.lower()


async def test_a_pdf_the_rules_read_queues_no_ai_at_all(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """⚠️ THE OTHER SIDE, AND WITHOUT IT THE FIX ABOVE PASSES FOR A VERSION THAT SPLITS EVERYTHING.

    A UWM letter the rules read is DRAFT with its rows, and there is no model call to pay for. The
    absent assertion of this shape is what let the original defect ship: the enqueue was asserted
    where someone thought to assert it, and assumed everywhere else.
    """
    from app.tasks import conditions as task_module

    enqueued: list[str] = []
    monkeypatch.setattr(
        task_module.split_condition_round, "delay", lambda round_id: enqueued.append(round_id)
    )

    round_ = await _round(db_session)

    await parse_round(db_session, round_.id)
    await db_session.refresh(round_)

    assert round_.parse_report["needs_ai"] is False
    assert round_.status is ConditionRoundStatus.DRAFT
    assert enqueued == []


# --------------------------------------------------------------------------- #
# Typed failures — spec §9.8
# --------------------------------------------------------------------------- #


async def test_an_unreadable_pdf_fails_with_a_typed_reason(db_session: AsyncSession) -> None:
    """⚠️ NEVER A BARE `except Exception`. Measured: empty bytes raise `pymupdf.EmptyFileError` and
    garbage raises `FileDataError`, so both are caught by name and become one typed failure a
    processor can act on."""
    round_ = await _round(db_session)
    round_.sources = [{**round_.sources[0], "storage_path": round_.sources[0]["storage_path"]}]
    # Replace the stored bytes with something no PDF library can open.
    from app.storage import get_storage_backend

    await get_storage_backend().save_at(
        storage_path=round_.sources[0]["storage_path"], content=b"not a pdf at all"
    )

    await parse_round(db_session, round_.id)
    await db_session.refresh(round_)

    assert round_.status is ConditionRoundStatus.PARSE_FAILED
    assert round_.parse_report["failure_kind"] == SheetUnreadable.failure_kind
    assert "damaged" in round_.parse_report["failure_detail"]
    kinds = [e.kind for e in await _events(db_session, round_.id)]
    assert ConditionEventKind.ROUND_PARSE_FAILED in kinds


async def test_missing_bytes_fail_with_their_own_reason(db_session: AsyncSession) -> None:
    """ "The file is gone" and "this PDF is damaged" lead to different next actions, so they are
    different `failure_kind`s rather than one generic failure."""
    round_ = await _round(db_session)
    round_.sources = [{"kind": "pdf_upload", "at": "2026-09-23T00:00:00+00:00"}]
    await db_session.flush()

    await parse_round(db_session, round_.id)
    await db_session.refresh(round_)

    assert round_.status is ConditionRoundStatus.PARSE_FAILED
    assert round_.parse_report["failure_kind"] == "bytes_unavailable"


async def test_the_failure_detail_quotes_nothing_from_the_sheet(
    db_session: AsyncSession,
) -> None:
    """⚠️ COMPOSED, NEVER QUOTED (spec §9.5), AND NOT FOR THE REASON THIS DOCSTRING USED TO GIVE.

    It said `failure_detail` "reaches the readonly layer, which scrubs identifier SHAPES only". It
    does not reach it: `parse_report` is in the EXCLUDED set and migration `d1f4b8c25e93` drops it
    whole, projecting only derived scalars. Nothing quoted here escapes — and it is still wrong to
    store, because that column is excluded PRECISELY BECAUSE `unassigned_lines` inside it carries
    verbatim sheet text, so a borrower's name in `failure_detail` is NPI at rest in a field nobody
    can inspect to find it.

    The same rule that moved a warning from quoting a loan-information line to naming its position:
    there too nothing escaped the view, and storing it was the part that needed fixing.
    """
    # ⚠️ THE BAD BYTES GO IN *AFTER* CREATION. An earlier version passed them to
    # `create_round_from_sheet`, which refuses a non-PDF at the door — so the round never existed
    # and the test failed inside its own setup with `ConditionSheetRejected`. The upload guard and
    # the parse guard are different defences; this one is about the second.
    from app.storage import get_storage_backend

    round_ = await _round(db_session)
    await get_storage_backend().save_at(
        storage_path=round_.sources[0]["storage_path"], content=b"not a pdf at all"
    )

    await parse_round(db_session, round_.id)
    await db_session.refresh(round_)

    detail = round_.parse_report["failure_detail"]
    assert "not a pdf at all" not in detail
    assert detail.endswith("send it again.")


async def test_an_unknown_round_id_is_not_an_error(db_session: AsyncSession) -> None:
    """A round deleted between enqueue and pickup is not a failure — there is nothing to fail."""
    await parse_round(db_session, uuid4())

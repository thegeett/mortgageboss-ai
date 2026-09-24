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
from tests.conditions.uwm_pdf_fixture import render_uwm_pdf
from tests.models.conftest_helpers import make_company, make_loan_file


async def _round(db: AsyncSession, *, content: bytes | None = None) -> ConditionRound:
    company = await make_company(db)
    loan_file = await make_loan_file(db, company=company)
    return await create_round_from_sheet(
        db,
        loan_file=loan_file,
        sheet=SheetBytes(
            content=content if content is not None else render_uwm_pdf(UWM_ROUND_1),
            source_kind=ConditionSourceKind.PDF_UPLOAD,
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

"""Opening a round from a paste (LP-907 section 1, spec §LP-907).

The service, not the endpoint: what a pasted round looks like the instant it is created. Unlike an
uploaded sheet there is no "before it is read" state to pin — the rules run inside the call — so
what matters here is that the round arrives FINISHED and that every field a paste cannot carry is
null rather than invented.
"""

from __future__ import annotations

from datetime import date

from app.models.activity_log import ActivityLog, ActivityType
from app.models.base import utcnow
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_round import (
    ConditionRound,
    ConditionRoundCompleteness,
    ConditionRoundStatus,
    ConditionSheetFormat,
    ConditionSourceKind,
)
from app.services.condition_rounds import create_round_from_paste
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.fixture_helpers import UWM_ROUND_2, portal_excerpt, sheet_text
from tests.models.conftest_helpers import make_company, make_loan_file


async def _paste(
    db: AsyncSession,
    *,
    text: str | None = None,
    completeness: ConditionRoundCompleteness = ConditionRoundCompleteness.PARTIAL,
    round_date: date | None = None,
) -> ConditionRound:
    company = await make_company(db)
    loan_file = await make_loan_file(db, company=company)
    return await create_round_from_paste(
        db,
        loan_file=loan_file,
        text=text if text is not None else portal_excerpt(),
        completeness=completeness,
        round_date=round_date,
    )


async def test_a_paste_arrives_already_read(db_session: AsyncSession) -> None:
    """⚠️ `DRAFT`, NOT `PARSING` — the opposite of every other door, and deliberately so. An upload
    has bytes to fetch and pages to rasterise; a paste is text already in memory, so queuing it
    would cost the processor a "Reading…" screen for work that finished inside the request."""
    round_ = await _paste(db_session)

    assert round_.status is ConditionRoundStatus.DRAFT
    assert round_.draft_rows is not None
    assert len(round_.draft_rows) == 6
    assert round_.round_number is None, "numbers are assigned on import, not on arrival"


async def test_a_recognised_paste_keeps_the_lenders_own_columns(db_session: AsyncSession) -> None:
    """THE PROPERTY THE IMPORT DEPENDS ON, asserted on the stored row rather than on the reader.

    Without recognition the fallback glues each row's category onto the front of its text, so no
    pasted condition fingerprints equal to the same condition read from the PDF — and "6 seen again"
    silently becomes "6 new".
    """
    round_ = await _paste(db_session)

    assert round_.sheet_format is ConditionSheetFormat.UWM_APPROVAL_LETTER
    assert round_.draft_rows is not None
    assert [row["lender_code"] for row in round_.draft_rows] == [
        "1228",
        "1947",
        "1582",
        "0006",
        "0007",
        "6378",
    ]
    assert round_.draft_rows[3]["lender_category"] == "Invoice"
    assert round_.draft_rows[3]["verbatim_text"] == "Provide copy of invoice for credit report."
    assert round_.parse_report["reader"] == "uwm"


async def test_the_raw_paste_is_stored_because_it_IS_the_source(db_session: AsyncSession) -> None:
    """⚠️ NPI (ADR-405), and kept anyway. A pasted round has no file: `raw_text` is the only copy of
    what the processor sent. LP-908 splits THAT text, never a reconstruction from rows the rules may
    have misread, and §9.3 checks every AI row is a substring of it."""
    text = portal_excerpt()
    round_ = await _paste(db_session, text=text)

    assert round_.raw_text == text
    # Stored verbatim: the soft hyphen the lender's pipeline emitted is still there, untouched.
    assert "­" in text
    assert "­" in (round_.raw_text or "")


async def test_the_source_records_a_paste_and_nothing_it_does_not_have(
    db_session: AsyncSession,
) -> None:
    round_ = await _paste(db_session)

    assert len(round_.sources) == 1
    assert round_.sources[0]["kind"] == ConditionSourceKind.PASTE.value
    # ⚠️ NO `storage_path`. Nothing was stored, so claiming a path would make the parse task fetch a
    # file that does not exist instead of refusing cleanly.
    assert "storage_path" not in round_.sources[0]


async def test_completeness_is_carried_not_guessed(db_session: AsyncSession) -> None:
    """ADR-404: only a FULL round's absences can ever mean anything, so the caller must say."""
    partial = await _paste(db_session, completeness=ConditionRoundCompleteness.PARTIAL)
    full = await _paste(db_session, completeness=ConditionRoundCompleteness.FULL)

    assert partial.completeness is ConditionRoundCompleteness.PARTIAL
    assert full.completeness is ConditionRoundCompleteness.FULL


async def test_the_round_date_prefers_the_processor_then_the_sheet_then_today(
    db_session: AsyncSession,
) -> None:
    """Three sources, in falling order of how much they know."""
    chosen = await _paste(db_session, round_date=date(2026, 9, 1))
    assert chosen.round_date == date(2026, 9, 1)

    # A paste of the WHOLE letter carries a printed date, and it is used when nobody chose one.
    whole = await _paste(db_session, text=sheet_text(UWM_ROUND_2))
    assert whole.date_printed == date(2026, 9, 10)
    assert whole.round_date == date(2026, 9, 10)

    # An excerpt has no letterhead, so there is no date but today's.
    excerpt = await _paste(db_session)
    assert excerpt.date_printed is None
    assert excerpt.round_date == utcnow().date()


async def test_both_events_are_written_because_both_things_happened(
    db_session: AsyncSession,
) -> None:
    """An uploaded sheet arrives and is read later, in two events. A paste does both inside one
    request — writing only one would make the round-details history (S1-09) read differently for
    rounds that are otherwise identical."""
    round_ = await _paste(db_session)

    events = (
        (
            await db_session.execute(
                select(ConditionEvent).where(ConditionEvent.round_id == round_.id)
            )
        )
        .scalars()
        .all()
    )
    kinds = [event.kind for event in events]

    assert ConditionEventKind.ROUND_RECEIVED in kinds
    assert ConditionEventKind.ROUND_PARSED in kinds
    parsed = next(e for e in events if e.kind is ConditionEventKind.ROUND_PARSED)
    assert parsed.detail["reader"] == "uwm"
    assert parsed.detail["rows"] == 6
    # ⚠️ NO NPI IN AN EVENT DETAIL (spec §9.5): counts, codes and reader names only.
    received = next(e for e in events if e.kind is ConditionEventKind.ROUND_RECEIVED)
    assert set(received.detail) == {"source_kind", "chars"}


async def test_a_paste_awaiting_the_ai_has_not_been_parsed_yet(
    db_session: AsyncSession,
) -> None:
    """⚠️ THE ROUND'S HISTORY MUST NOT CLAIM A PARSE THAT HAS NOT HAPPENED.

    A paste the rules read emits ROUND_RECEIVED and ROUND_PARSED together, because both genuinely
    happened inside the request. One that needs the AI has only ARRIVED — the split task emits
    ROUND_PARSED when it settles. Emitting it here too put two parses on one round, one of which
    never occurred, and screen S1-09 renders that history to a processor.
    """
    round_ = await _paste(
        db_session, text="Please send whatever you have for this file when you can."
    )

    kinds = [
        event.kind
        for event in (
            await db_session.execute(
                select(ConditionEvent).where(ConditionEvent.round_id == round_.id)
            )
        )
        .scalars()
        .all()
    ]

    assert kinds == [ConditionEventKind.ROUND_RECEIVED]
    assert round_.status is ConditionRoundStatus.PARSING


async def test_a_paste_writes_a_timeline_entry(db_session: AsyncSession) -> None:
    round_ = await _paste(db_session)

    entry = await db_session.scalar(
        select(ActivityLog).where(ActivityLog.loan_file_id == round_.loan_file_id)
    )

    assert entry is not None
    assert entry.activity_type is ActivityType.CONDITION_SHEET_RECEIVED
    assert entry.detail["round_id"] == str(round_.id)
    assert entry.detail["source_kind"] == ConditionSourceKind.PASTE.value


async def test_text_the_rules_cannot_split_opens_parsing_for_the_ai(
    db_session: AsyncSession,
) -> None:
    """⚠️ LP-907's DEVIATION, REVERTED NOW THAT ITS REASON HAS EXPIRED.

    LP-907 shipped this as `DRAFT` for one stated reason: LP-908 did not exist, so `PARSING` would
    have enqueued nothing and stranded the round with no worker and no exit — the gap LP-905
    recorded. LP-908 §2 is the worker, so the spec's shape applies: `PARSING`, and the caller
    enqueues the split.

    `needs_ai` with `ai_used` still false is what says the round is WAITING rather than finished —
    the two are read together, and the split task sets the second.
    """
    round_ = await _paste(
        db_session, text="Please send whatever you have for this file when you can."
    )

    assert round_.status is ConditionRoundStatus.PARSING
    assert round_.sheet_format is ConditionSheetFormat.PASTED_TEXT
    assert round_.parse_report["needs_ai"] is True
    assert round_.parse_report["ai_used"] is False


async def test_a_rule_read_paste_does_not_ask_for_ai(db_session: AsyncSession) -> None:
    """The other side of the same flag. `needs_ai` must not be set merely because a read happened —
    setting it on a sheet the rules understood would pay for an AI call to redo finished work."""
    round_ = await _paste(db_session)

    assert round_.parse_report["needs_ai"] is False
    assert round_.parse_report["ai_used"] is False


async def test_draft_rows_are_stored_through_the_response_schema(
    db_session: AsyncSession,
) -> None:
    """⚠️ NOT `dataclasses.asdict`. Dates, enums and nested dataclasses are not JSONB, and a
    hand-rolled dict would be a third representation of a row free to drift from `DraftRowPublic`.
    Going through the schema means what is stored is exactly what is served."""
    round_ = await _paste(db_session)

    assert round_.draft_rows is not None
    row = round_.draft_rows[0]
    # Enums came out as their values and nothing is a Python object.
    assert row["bucket_kind"] == "prior_to_docs"
    assert row["confidence"] == 1.0
    assert isinstance(row["underwriter_notes"], list)
    assert row["source_line_numbers"] == [1, 2, 3]

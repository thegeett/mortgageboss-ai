"""The derived numbers on a round card — "11 on sheet · 11 new · 0 seen again" (S1-05, S1-08).

⚠️ NEITHER PRODUCER HAD A TEST UNTIL THIS FILE. `rows_on_sheet` exists because `condition_count`
"defaulted to 0 since LP-904 with nothing filling it, so a round card would have read '0 on sheet'
for as long as anyone looked" — a bug that survived a whole ticket precisely because 0 is a VALID
count and nothing fails on it. The helper written to fix that was then itself unguarded, and
`import_counts` adds two more fields with the same hazard.

So what these pin is not "the number is right" but the distinction the numbers depend on: a value
that was MEASURED versus one that was defaulted, and a question that does not apply versus an answer
of zero.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_round import ConditionRound, ConditionRoundStatus
from app.services.conditions import import_counts, import_counts_for_file, rows_on_sheet
from sqlalchemy.ext.asyncio import AsyncSession
from tests.models.conftest_helpers import make_company, make_loan_file, make_round


async def _imported_event(
    db: AsyncSession,
    *,
    round_: ConditionRound,
    detail: dict[str, Any],
    occurred_at: datetime | None = None,
) -> ConditionEvent:
    """One `ROUND_IMPORTED` event, written the way `condition_import.py` writes it.

    ⚠️ A REAL tz-aware `datetime`, NOT AN ISO STRING. The first version passed a string and silenced
    the complaint with `type: ignore[assignment]` — a suppression on the one line that was actually
    wrong. asyncpg then refused it: "expected a datetime.date or datetime.datetime instance, got
    'str'". The column is TIMESTAMP WITH TIME ZONE, and the ordering these events are read back in
    is the whole subject of the test below, so a naive value would have been wrong a second way.
    """
    event = ConditionEvent(
        company_id=round_.company_id,
        loan_file_id=round_.loan_file_id,
        round_id=round_.id,
        kind=ConditionEventKind.ROUND_IMPORTED,
        detail=detail,
    )
    if occurred_at is not None:
        event.occurred_at = occurred_at
    db.add(event)
    await db.flush()
    return event


async def test_an_imported_round_reports_what_its_import_recorded(
    db_session: AsyncSession,
) -> None:
    company = await make_company(db_session)
    loan_file = await make_loan_file(db_session, company=company)
    round_ = await make_round(
        db_session,
        company=company,
        loan_file=loan_file,
        status=ConditionRoundStatus.IMPORTED,
        round_number=1,
    )
    await _imported_event(db_session, round_=round_, detail={"created": 11, "seen_again": 0})

    counts = await import_counts_for_file(db_session, loan_file_id=loan_file.id)

    assert counts[round_.id] == (11, 0)
    assert import_counts(round_, counts) == (11, 0)


async def test_a_draft_says_the_question_does_not_apply_rather_than_zero(
    db_session: AsyncSession,
) -> None:
    """⚠️ THE DISTINCTION THE WHOLE FIELD EXISTS FOR. A draft has never been imported, so "0 new" is
    a claim about an event that never happened. `condition_count` shipped as `0` for exactly this
    reason and nothing caught it, because zero reads as data."""
    company = await make_company(db_session)
    loan_file = await make_loan_file(db_session, company=company)
    draft = await make_round(db_session, company=company, loan_file=loan_file)

    counts = await import_counts_for_file(db_session, loan_file_id=loan_file.id)

    assert import_counts(draft, counts) == (None, None)
    assert import_counts(draft, counts) != (0, 0)


async def test_a_reimported_round_reports_the_LATEST_event(db_session: AsyncSession) -> None:
    """⚠️ `condition_events` IS APPEND-ONLY, so a second import leaves two rows and the older one is
    still there forever. "Newest wins" is a decision rather than a property of the table."""
    company = await make_company(db_session)
    loan_file = await make_loan_file(db_session, company=company)
    round_ = await make_round(
        db_session,
        company=company,
        loan_file=loan_file,
        status=ConditionRoundStatus.IMPORTED,
        round_number=1,
    )
    await _imported_event(
        db_session,
        round_=round_,
        detail={"created": 11, "seen_again": 0},
        occurred_at=datetime(2026, 8, 28, 10, 0, tzinfo=UTC),
    )
    await _imported_event(
        db_session,
        round_=round_,
        detail={"created": 0, "seen_again": 6},
        occurred_at=datetime(2026, 9, 10, 16, 20, tzinfo=UTC),
    )

    counts = await import_counts_for_file(db_session, loan_file_id=loan_file.id)

    assert counts[round_.id] == (0, 6)


async def test_a_detail_that_cannot_answer_is_skipped_rather_than_zeroed(
    db_session: AsyncSession,
) -> None:
    """⚠️ SKIPPED, NOT `(0, 0)`. A detail missing a key cannot say what the import did, and recording
    it as zero would put a confident wrong number on the card — the same shape as the default this
    field was written to avoid. Absent here becomes `None` on the wire, which a screen can omit."""
    company = await make_company(db_session)
    loan_file = await make_loan_file(db_session, company=company)
    round_ = await make_round(
        db_session,
        company=company,
        loan_file=loan_file,
        status=ConditionRoundStatus.IMPORTED,
        round_number=1,
    )
    await _imported_event(db_session, round_=round_, detail={"created": 11})

    counts = await import_counts_for_file(db_session, loan_file_id=loan_file.id)

    assert round_.id not in counts
    assert import_counts(round_, counts) == (None, None)


async def test_counts_do_not_leak_between_files(db_session: AsyncSession) -> None:
    """One query serves the whole file, so the `loan_file_id` filter is what keeps it to this one."""
    company = await make_company(db_session)
    mine = await make_loan_file(db_session, company=company)
    theirs = await make_loan_file(db_session, company=company)
    other_round = await make_round(
        db_session,
        company=company,
        loan_file=theirs,
        status=ConditionRoundStatus.IMPORTED,
        round_number=1,
    )
    await _imported_event(db_session, round_=other_round, detail={"created": 5, "seen_again": 5})

    assert await import_counts_for_file(db_session, loan_file_id=mine.id) == {}


async def test_rows_on_sheet_counts_draft_rows_before_import_and_appearances_after(
    db_session: AsyncSession,
) -> None:
    """⚠️ THE HELPER THAT HAD NO TEST. Its own docstring is the assertion: "a draft counts its rows
    and an imported round counts its appearances", and conflating the two makes a draft look empty."""
    company = await make_company(db_session)
    loan_file = await make_loan_file(db_session, company=company)
    draft = await make_round(db_session, company=company, loan_file=loan_file)
    draft.draft_rows = [{"sequence": 1}, {"sequence": 2}]
    imported = await make_round(
        db_session,
        company=company,
        loan_file=loan_file,
        status=ConditionRoundStatus.IMPORTED,
        round_number=1,
    )
    await db_session.flush()

    # A draft reads its own rows and ignores the appearance map entirely.
    assert rows_on_sheet(draft, {draft.id: 99}) == 2
    # An imported round reads the map and ignores `draft_rows`, which import clears.
    assert rows_on_sheet(imported, {imported.id: 11}) == 11
    # And an imported round with no appearances recorded is 0 rather than a KeyError.
    assert rows_on_sheet(imported, {uuid4(): 3}) == 0

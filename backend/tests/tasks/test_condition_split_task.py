"""Settling a pasted round with the AI split (LP-908 section 2).

⚠️ THESE DRIVE `split_round`, NOT THE CELERY WRAPPER, for the reason every task test in this repo
does: `task_session()` builds its own engine and the suite isolates each test inside a transaction
that is never committed, so a task opening its own session would not see the round the test created.

THE PROPERTY THAT MATTERS MOST IS THE ONE LP-907 REFUSED TO CREATE: a round in `PARSING` with no way
out. Every path below either settles it or leaves it untouched for a retry — never half-written.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from app.conditions.readers.model import AI_SPLIT_CONFIDENCE, ParsedRow, ParsedSheet
from app.models.condition import BucketKind
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_round import (
    ConditionRound,
    ConditionRoundCompleteness,
    ConditionRoundStatus,
    ConditionSheetFormat,
)
from app.services.condition_rounds import create_round_from_paste
from app.services.condition_split import ConditionSplitUnavailable, SplitOutcome
from app.tasks import conditions as task_module
from app.tasks.conditions import split_round
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.models.conftest_helpers import make_company, make_loan_file

PROSE = "Please send whatever you have for this file when you can."


async def _parsing_round(db: AsyncSession, *, text: str = PROSE) -> ConditionRound:
    """A pasted round the rules could not split — the state LP-908 exists to finish."""
    company = await make_company(db)
    loan_file = await make_loan_file(db, company=company)
    round_ = await create_round_from_paste(
        db, loan_file=loan_file, text=text, completeness=ConditionRoundCompleteness.PARTIAL
    )
    assert round_.status is ConditionRoundStatus.PARSING
    return round_


def _outcome(*texts: str, rejected: int = 0) -> SplitOutcome:
    sheet = ParsedSheet(sheet_format=ConditionSheetFormat.PASTED_TEXT)
    sheet.rows = [
        ParsedRow(
            sequence=index,
            lender_code=None,
            lender_category=None,
            bucket_heading="",
            bucket_kind=BucketKind.UNKNOWN,
            verbatim_text=text,
            confidence=AI_SPLIT_CONFIDENCE,
        )
        for index, text in enumerate(texts, start=1)
    ]
    return SplitOutcome(sheet=sheet, model="claude-haiku-4-5", rejected=rejected)


async def _events(db: AsyncSession, round_id: object) -> list[ConditionEvent]:
    result = await db.execute(
        select(ConditionEvent).where(ConditionEvent.round_id == round_id)  # type: ignore[arg-type]
    )
    return list(result.scalars().all())


async def test_a_split_settles_the_round_to_draft(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    round_ = await _parsing_round(db_session)
    monkeypatch.setattr(
        task_module, "split_conditions", AsyncMock(return_value=_outcome("Send the invoice."))
    )

    await split_round(db_session, round_.id)
    await db_session.refresh(round_)

    assert round_.status is ConditionRoundStatus.DRAFT
    assert round_.draft_rows is not None
    assert [row["verbatim_text"] for row in round_.draft_rows] == ["Send the invoice."]
    assert round_.draft_rows[0]["confidence"] == AI_SPLIT_CONFIDENCE


async def test_the_report_records_that_the_ai_actually_ran(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """⚠️ `needs_ai` AND `ai_used` ARE READ TOGETHER. Before this task the pair says "waiting";
    after it, "done". `parse_report_for` hardcodes `ai_used=False` because it is written for the
    rule readers, so the task sets it — otherwise a finished round is indistinguishable from one
    still queued."""
    round_ = await _parsing_round(db_session)
    monkeypatch.setattr(
        task_module, "split_conditions", AsyncMock(return_value=_outcome("Send the invoice."))
    )

    await split_round(db_session, round_.id)
    await db_session.refresh(round_)

    assert round_.parse_report["ai_used"] is True
    assert round_.parse_report["reader"] == "split"
    assert round_.parse_report["reader_version"] == "split_v1"


async def test_rejected_rows_are_counted_on_the_round(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The number of rows the model produced that the input did not contain — visible to a processor
    rather than only in a log line."""
    round_ = await _parsing_round(db_session)
    monkeypatch.setattr(
        task_module,
        "split_conditions",
        AsyncMock(return_value=_outcome("Send the invoice.", rejected=2)),
    )

    await split_round(db_session, round_.id)
    await db_session.refresh(round_)

    assert round_.parse_report["rejected_rows"] == 2


async def test_an_unreachable_model_leaves_a_typed_failure_not_a_stranded_round(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """⚠️ THE STATE LP-907 REFUSED TO CREATE BEFORE THIS WORKER EXISTED. A round in `PARSING` with
    no exit is the gap LP-905 recorded; a failed split must land in `PARSE_FAILED` with a reason the
    processor can act on."""
    round_ = await _parsing_round(db_session)
    monkeypatch.setattr(
        task_module,
        "split_conditions",
        AsyncMock(side_effect=ConditionSplitUnavailable("The conditions could not be read.")),
    )

    await split_round(db_session, round_.id)
    await db_session.refresh(round_)

    assert round_.status is ConditionRoundStatus.PARSE_FAILED
    assert round_.parse_report["failure_kind"] == "ai_unavailable"
    assert "could not be read" in round_.parse_report["failure_detail"]
    kinds = [event.kind for event in await _events(db_session, round_.id)]
    assert ConditionEventKind.ROUND_PARSE_FAILED in kinds


async def test_a_round_with_no_text_fails_rather_than_calling_the_model(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`raw_text` IS the source for a pasted round. Without it there is nothing to split, and paying
    for a model call to discover that would be the wrong shape of honesty."""
    round_ = await _parsing_round(db_session)
    round_.raw_text = None
    await db_session.flush()
    called = AsyncMock()
    monkeypatch.setattr(task_module, "split_conditions", called)

    await split_round(db_session, round_.id)
    await db_session.refresh(round_)

    assert round_.status is ConditionRoundStatus.PARSE_FAILED
    assert round_.parse_report["failure_kind"] == "no_text"
    called.assert_not_awaited()


async def test_a_second_delivery_settles_nothing_and_appends_no_event(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """⚠️ THE COMPARE-AND-SET, AND WHY THIS TASK REUSES IT WHERE THE ENRICH MERGE DOES NOT. This
    genuinely IS a parse settling a `PARSING` round, so the guard means what it says: the second
    delivery matches no row, writes nothing, and appends no event — which matters because
    `condition_events` is append-only and a duplicate could never be taken back."""
    round_ = await _parsing_round(db_session)
    monkeypatch.setattr(
        task_module, "split_conditions", AsyncMock(return_value=_outcome("Send the invoice."))
    )

    await split_round(db_session, round_.id)
    await split_round(db_session, round_.id)
    await db_session.refresh(round_)

    kinds = [event.kind for event in await _events(db_session, round_.id)]
    assert kinds.count(ConditionEventKind.ROUND_PARSED) == 1
    assert round_.status is ConditionRoundStatus.DRAFT


async def test_a_discarded_round_is_not_resurrected(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A processor can throw the round away while the model is working. The guard protects that: the
    round is no longer `PARSING`, so the split settles nothing."""
    round_ = await _parsing_round(db_session)
    round_.status = ConditionRoundStatus.DISCARDED
    await db_session.flush()
    # ⚠️ NOT `== []`. A paste that needs the AI still carries whatever the RULES managed to read —
    # `create_round_from_paste` writes `draft_rows` either way — so "empty" was never the property.
    # What matters is that the split left them exactly as it found them.
    before = list(round_.draft_rows or [])
    called = AsyncMock()
    monkeypatch.setattr(task_module, "split_conditions", called)

    await split_round(db_session, round_.id)
    await db_session.refresh(round_)

    assert round_.status is ConditionRoundStatus.DISCARDED
    assert list(round_.draft_rows or []) == before
    called.assert_not_awaited()

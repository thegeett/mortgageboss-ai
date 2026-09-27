"""The lender's own dated note reopening a condition — A1, ADR-408, screen S2-08.

THIS IS THE ONE PLACE IN STAGE 2 WHERE THE APP MOVES A STATUS WITH NOBODY CLICKING, which is why it
is the path that needs the most convincing. Everything else waits for a person: only a recorded
verdict clears, and every refusal exists to stop a status moving on an inference. Here an import reads
a dated note the lender wrote, concludes the condition was NOT satisfied, and writes that down.

SO THE EVENT HAS TO CARRY WHERE IT CAME FROM. The append-only guard's question is whether a reader
could infer the lender answered without the row saying where the lender said it
(`tests/models/test_condition_events_append_only.py`). `CONDITION_CAME_BACK` does state an answer, so
it is legitimate ONLY because it names `source_kind: underwriter_note` and the note's own date — and
that is asserted here rather than assumed, because without it `came_back` is exactly the bare claim
the guard forbids.

THE ROWS ARE SYNTHETIC AND THE NOTES ARE INVENTED. `uwm_round2_2026-09-10.txt` carries no underwriter
notes at all, so there is no fixture that drives this path; and real borrower data may not enter the
repo (spec §6). The wording below is written for the test.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from app.models.condition import (
    BucketKind,
    Condition,
    ConditionLenderStatus,
    ConditionPrepStatus,
    OwnerHint,
    OwnerHintSource,
)
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_round import (
    ConditionRound,
    ConditionRoundCompleteness,
    ConditionRoundStatus,
)
from app.schemas.condition import DraftRowPublic, VerdictSourceKind
from app.services.condition_import import import_round
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.models.conftest_helpers import make_company, make_lender, make_loan_file, make_round

INVOICE = "Provide copy of invoice for credit report."

#: Round 1 printed, round 2 printed, and the note the underwriter dated in between.
R1_DATE = date(2026, 8, 28)
R2_DATE = date(2026, 9, 10)
NOTE_DATE = date(2026, 9, 8)

NOTE_TEXT = "Invoice provided does not match the fee on the credit report. Please resubmit."


def _row(**overrides: Any) -> dict[str, Any]:
    """One draft row, THROUGH THE SCHEMA rather than as a dict literal.

    `draft_rows` is written by `draft_rows_json`, which routes every row through
    `DraftRowPublic.model_dump(mode="json")` precisely so what is stored is what is served. A literal
    here would be a third representation of a row, free to keep passing after the schema moved.
    """
    base: dict[str, Any] = {
        "sequence": 1,
        "lender_code": "7086",
        "lender_category": "Assets",
        "bucket_heading": "Closing (PTF)",
        "bucket_kind": BucketKind.PRIOR_TO_FUNDING,
        "verbatim_text": INVOICE,
        "underwriter_notes": [],
        "owner_hint": OwnerHint.BORROWER,
        "owner_hint_source": OwnerHintSource.CODE_MAP,
    }
    base.update(overrides)
    return DraftRowPublic(**base).model_dump(mode="json")


def _note(*, note_date: date | None = NOTE_DATE, text: str = NOTE_TEXT) -> dict[str, Any]:
    """A note as the reader produces it. `date` is None for one it could not date."""
    return {"date": note_date, "text": text}


async def _imported_round_1(db: AsyncSession, *, rows: list[dict[str, Any]] | None = None) -> Any:
    """A file whose round 1 is imported. Returns `(round, loan_file)`."""
    company = await make_company(db)
    loan_file = await make_loan_file(db, company=company)
    lender = await make_lender(db, company=company)
    round_ = await make_round(db, company=company, loan_file=loan_file, lender=lender)
    round_.round_date = R1_DATE
    round_.draft_rows = rows if rows is not None else [_row()]
    await db.flush()
    await import_round(db, round_=round_)
    return round_, loan_file


async def _second_sheet(
    db: AsyncSession,
    *,
    first: ConditionRound,
    rows: list[dict[str, Any]],
    completeness: ConditionRoundCompleteness = ConditionRoundCompleteness.FULL,
) -> ConditionRound:
    """Another sheet for the same file, printed later — built directly, as `make_round` takes a
    Company and the first round already carries the ids this needs."""
    round_ = ConditionRound(
        company_id=first.company_id,
        loan_file_id=first.loan_file_id,
        lender_id=first.lender_id,
        status=ConditionRoundStatus.DRAFT,
        completeness=completeness,
        round_date=R2_DATE,
        sources=[],
        parse_report={},
        draft_rows=rows,
    )
    db.add(round_)
    await db.flush()
    return round_


async def _the_condition(db: AsyncSession, loan_file_id: UUID) -> Condition:
    result = await db.execute(select(Condition).where(Condition.loan_file_id == loan_file_id))
    conditions = list(result.scalars().all())
    assert len(conditions) == 1, "these tests are about ONE condition seen twice"
    return conditions[0]


async def _events(db: AsyncSession, condition_id: UUID) -> list[ConditionEvent]:
    result = await db.execute(
        select(ConditionEvent)
        .where(ConditionEvent.condition_id == condition_id)
        .order_by(ConditionEvent.occurred_at)
    )
    return list(result.scalars().all())


async def _came_back_event(db: AsyncSession, condition_id: UUID) -> ConditionEvent:
    matching = [
        event
        for event in await _events(db, condition_id)
        if event.kind is ConditionEventKind.CONDITION_CAME_BACK
    ]
    assert len(matching) == 1, f"expected exactly one came-back event, found {len(matching)}"
    return matching[0]


# --------------------------------------------------------------------------- #
# The event says where it came from
# --------------------------------------------------------------------------- #


async def test_the_came_back_event_names_the_note_that_caused_it(db_session: AsyncSession) -> None:
    """THE ASSERTION THAT MAKES THIS EVENT ALLOWED TO EXIST.

    Without `source_kind` and the note's date in the detail, `condition_came_back` asserts the lender
    refused a condition and offers nothing behind the assertion — which is what
    `test_no_event_kind_can_state_a_clearing_on_its_own` forbids for the clearing direction, and the
    same argument applies to this one.

    THE DATE IS THE NOTE'S, NOT THE IMPORT'S. An event stamped with when we read the sheet says when
    WE found out; S2-08's line is "set by the lender's 9/8 note", which is a different fact and the
    only one a processor can check against the letter in front of them.
    """
    first, loan_file = await _imported_round_1(db_session)
    second = await _second_sheet(db_session, first=first, rows=[_row(underwriter_notes=[_note()])])

    await import_round(db_session, round_=second)

    condition = await _the_condition(db_session, loan_file.id)
    event = await _came_back_event(db_session, condition.id)
    assert event.detail["source_kind"] == VerdictSourceKind.UNDERWRITER_NOTE.value
    assert event.detail["source_date"] == NOTE_DATE.isoformat()
    # BOTH FROM→TO PAIRS ON THE ONE EVENT (ADR-408): the lender's answer and what it means for our
    # work are one statement, so a second event beside it would make the history double-count.
    assert event.detail["lender_status_from"] == ConditionLenderStatus.OPEN.value
    assert event.detail["lender_status_to"] == ConditionLenderStatus.NOT_CLEARED.value


async def test_the_verdict_on_the_row_carries_the_same_provenance(
    db_session: AsyncSession,
) -> None:
    """S2-03's callout reads the ROW's verdict, not the event, so the provenance has to be on both.

    `not_cleared` WITH A VERDICT IS WHAT MAKES `came_back` TRUE. The flag is narrowed to
    `verdict.source_kind == underwriter_note` (LP-912), so a `not_cleared` recorded by hand from a
    phone call is not a came-back and does not paint S2-08's amber rail — this asserts the note-sourced
    case sets exactly what that flag reads.
    """
    first, loan_file = await _imported_round_1(db_session)
    second = await _second_sheet(db_session, first=first, rows=[_row(underwriter_notes=[_note()])])

    await import_round(db_session, round_=second)

    condition = await _the_condition(db_session, loan_file.id)
    assert condition.lender_status is ConditionLenderStatus.NOT_CLEARED
    assert condition.verdict is not None
    assert condition.verdict["source_kind"] == VerdictSourceKind.UNDERWRITER_NOTE.value
    assert condition.verdict["source_date"] == NOTE_DATE.isoformat()
    assert condition.verdict["round_id"] == str(second.id), "the sheet that showed it"


async def test_no_note_added_event_is_written_beside_it(db_session: AsyncSession) -> None:
    """EXACTLY ONE EVENT PER CHANGE (spec §6 rule 4), and ADR-408 folds `condition_note_added` in.

    The note IS the reopening here, so writing both would put two lines in the history for one thing
    the lender did — and a processor reading "note added" and "came back" as separate entries would
    reasonably conclude there were two notes.
    """
    first, loan_file = await _imported_round_1(db_session)
    second = await _second_sheet(db_session, first=first, rows=[_row(underwriter_notes=[_note()])])

    await import_round(db_session, round_=second)

    condition = await _the_condition(db_session, loan_file.id)
    kinds = [event.kind for event in await _events(db_session, condition.id)]
    assert ConditionEventKind.CONDITION_CAME_BACK in kinds
    assert ConditionEventKind.CONDITION_NOTE_ADDED not in kinds
    # The appearance is still recorded separately — the `R1 R2` chips derive from it (ADR-408).
    assert ConditionEventKind.CONDITION_SEEN_AGAIN in kinds


# --------------------------------------------------------------------------- #
# What it does and does not reset
# --------------------------------------------------------------------------- #


async def test_work_that_had_moved_on_goes_back_to_to_do(db_session: AsyncSession) -> None:
    """`ready` and `with_underwriter` became untrue the moment the lender refused it.

    A condition we had marked *Sent to lender* has not been sent to anyone's satisfaction, and leaving
    it there hides it from the list that would make somebody pick it up again.
    """
    first, loan_file = await _imported_round_1(db_session)
    condition = await _the_condition(db_session, loan_file.id)
    condition.prep_status = ConditionPrepStatus.WITH_UNDERWRITER
    await db_session.flush()

    second = await _second_sheet(db_session, first=first, rows=[_row(underwriter_notes=[_note()])])
    await import_round(db_session, round_=second)

    await db_session.refresh(condition)
    assert condition.prep_status is ConditionPrepStatus.TO_DO
    event = await _came_back_event(db_session, condition.id)
    assert event.detail["prep_status_from"] == ConditionPrepStatus.WITH_UNDERWRITER.value
    assert event.detail["prep_status_to"] == ConditionPrepStatus.TO_DO.value


async def test_work_already_in_hand_is_left_where_it_is(db_session: AsyncSession) -> None:
    """THE OTHER BRANCH, AND IT PROTECTS A PROCESSOR'S CHOICE. A condition still `waiting` on the
    borrower was already being worked — resetting it to `to_do` would wipe the owner somebody chose
    and claim a correction that was not needed."""
    first, loan_file = await _imported_round_1(db_session)
    condition = await _the_condition(db_session, loan_file.id)
    condition.prep_status = ConditionPrepStatus.WAITING
    condition.waiting_on = OwnerHint.BORROWER
    await db_session.flush()

    second = await _second_sheet(db_session, first=first, rows=[_row(underwriter_notes=[_note()])])
    await import_round(db_session, round_=second)

    await db_session.refresh(condition)
    assert condition.prep_status is ConditionPrepStatus.WAITING
    assert condition.waiting_on is OwnerHint.BORROWER, "the owner somebody chose survives"
    # The lender's track still moved — only ours was left alone.
    assert condition.lender_status is ConditionLenderStatus.NOT_CLEARED


# --------------------------------------------------------------------------- #
# What is not enough to move anything
# --------------------------------------------------------------------------- #


async def test_a_note_we_cannot_date_reopens_nothing(db_session: AsyncSession) -> None:
    """THE SAFEST OPTION, TAKEN DELIBERATELY (survey §5.2, ADR-408).

    A verdict needs a date, and a note we cannot date is not the lender answering on a day. So the
    note is RECORDED — nothing disappears — and no status moves. Stage 1's behaviour, kept.

    The alternative was to date it by the round, which would have invented the one fact that makes a
    verdict checkable.
    """
    first, loan_file = await _imported_round_1(db_session)
    second = await _second_sheet(
        db_session, first=first, rows=[_row(underwriter_notes=[_note(note_date=None)])]
    )

    await import_round(db_session, round_=second)

    condition = await _the_condition(db_session, loan_file.id)
    assert condition.lender_status is ConditionLenderStatus.OPEN, "no verdict without a date"
    assert condition.verdict is None
    kinds = [event.kind for event in await _events(db_session, condition.id)]
    assert ConditionEventKind.CONDITION_CAME_BACK not in kinds
    # RECORDED, THOUGH. The note is on the row even though it moved nothing.
    assert any(note.get("text") == NOTE_TEXT for note in condition.underwriter_notes)


async def test_the_same_note_arriving_twice_reopens_once(db_session: AsyncSession) -> None:
    """A FULL SHEET REPEATS EVERY NOTE IT STILL CARRIES, so "a note is present" cannot mean "the
    lender just wrote one".

    Round 3 printing the same dated note is the lender still showing us the same refusal, not a second
    one. Without this the condition would come back on every import for the rest of the file's life,
    and the history would fill with came-back lines nobody can match to anything the lender did.
    """
    first, loan_file = await _imported_round_1(db_session)
    second = await _second_sheet(db_session, first=first, rows=[_row(underwriter_notes=[_note()])])
    await import_round(db_session, round_=second)

    third = await _second_sheet(db_session, first=first, rows=[_row(underwriter_notes=[_note()])])
    await import_round(db_session, round_=third)

    condition = await _the_condition(db_session, loan_file.id)
    # `_came_back_event` asserts there is exactly one.
    await _came_back_event(db_session, condition.id)
    assert [note.get("text") for note in condition.underwriter_notes] == [NOTE_TEXT], (
        "one note, not two copies of it"
    )

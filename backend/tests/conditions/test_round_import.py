"""A reviewed draft becoming the file's conditions (LP-909 section 2, spec §LP-909 steps 1-5).

⚠️ THE PROPERTY MOST OF THESE PIN IS "NOTHING IS LOST AND NOTHING IS INVENTED". Import is the moment
a parse becomes the record, so the failures that matter are a condition duplicated across rounds, a
condition silently replaced, a status moved that Stage 1 may not move, and a created condition with
no event to say it appeared — the last of which actually happened in `condition_enrich.py`.

Rows are built THROUGH `DraftRowPublic`, never as hand-rolled dicts. `draft_rows_json` makes the
same argument on the writing side: a hand-rolled dict here would be a third representation of a row,
free to drift from the schema that both stores and serves them.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.models.activity_log import ActivityLog, ActivityType
from app.models.condition import (
    BucketKind,
    Condition,
    ConditionLenderStatus,
    ConditionOrigin,
    ConditionPrepStatus,
    OwnerHint,
    OwnerHintSource,
)
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_round import ConditionRound, ConditionRoundStatus
from app.models.lender_condition_code import LenderCodeStatus, LenderConditionCode
from app.schemas.condition import DraftRowPublic
from app.services import condition_import
from app.services.condition_import import RoundNotImportable, import_round
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.models.conftest_helpers import (
    make_company,
    make_lender,
    make_loan_file,
    make_round,
)

INVOICE = "Provide copy of invoice for credit report."
HOI = "Provide evidence of hazard insurance for the subject property."


def _row(**overrides: Any) -> dict[str, Any]:
    """One draft row, in exactly the shape the readers store and the API serves.

    ⚠️ THROUGH THE SCHEMA, NOT A DICT LITERAL. `draft_rows` is written by
    `draft_rows_json`, which routes every row through `DraftRowPublic.model_dump(mode="json")`
    precisely so that what is stored is what is served. A literal here would be a third
    representation, and it would keep passing after the schema moved under it.
    """
    base: dict[str, Any] = {
        "sequence": 1,
        "lender_code": "7086",
        "lender_category": "Assets",
        "bucket_heading": "Closing (PTF)",
        "bucket_kind": BucketKind.PRIOR_TO_FUNDING,
        "verbatim_text": INVOICE,
        "underwriter_notes": [],
        "owner_hint": OwnerHint.UNKNOWN,
        "owner_hint_source": OwnerHintSource.NONE,
    }
    base.update(overrides)
    return DraftRowPublic(**base).model_dump(mode="json")


async def _draft(
    db: AsyncSession,
    *,
    rows: list[dict[str, Any]] | None = None,
    with_lender: bool = True,
    status: ConditionRoundStatus = ConditionRoundStatus.DRAFT,
) -> tuple[ConditionRound, Any, Any]:
    """A draft round holding `rows`, ready to import. Returns `(round, loan_file, lender)`."""
    company = await make_company(db)
    loan_file = await make_loan_file(db, company=company)
    lender = await make_lender(db, company=company) if with_lender else None
    round_ = await make_round(
        db, company=company, loan_file=loan_file, lender=lender, status=status
    )
    round_.draft_rows = rows if rows is not None else [_row()]
    await db.flush()
    return round_, loan_file, lender


async def _conditions(db: AsyncSession, loan_file_id: Any) -> list[Condition]:
    result = await db.execute(
        select(Condition).where(Condition.loan_file_id == loan_file_id).order_by(Condition.sequence)
    )
    return list(result.scalars().all())


async def _events(db: AsyncSession, round_id: Any) -> list[ConditionEvent]:
    result = await db.execute(select(ConditionEvent).where(ConditionEvent.round_id == round_id))
    return list(result.scalars().all())


# --------------------------------------------------------------------------- #
# Step 1 — the round becomes the record
# --------------------------------------------------------------------------- #


async def test_a_draft_becomes_the_files_conditions(db_session: AsyncSession) -> None:
    """Spec step 1: the round takes a number, becomes IMPORTED, and its rows are gone because they
    are now conditions."""
    round_, loan_file, _ = await _draft(
        db_session, rows=[_row(), _row(sequence=2, lender_code="0006", verbatim_text=HOI)]
    )

    outcome = await import_round(db_session, round_=round_)

    assert outcome.round_number == 1
    assert outcome.created == 2
    assert outcome.seen_again == 0
    assert round_.status is ConditionRoundStatus.IMPORTED
    assert round_.round_number == 1
    assert round_.draft_rows is None, "the rows ARE conditions now"

    conditions = await _conditions(db_session, loan_file.id)
    assert [c.verbatim_text for c in conditions] == [INVOICE, HOI]
    assert [c.lender_code for c in conditions] == ["7086", "0006"]
    assert all(c.origin is ConditionOrigin.SHEET for c in conditions)
    assert all(c.first_round_id == round_.id for c in conditions)
    assert all(c.last_seen_round_id == round_.id for c in conditions)


async def test_the_lenders_words_are_stored_exactly(db_session: AsyncSession) -> None:
    """⚠️ THE API IS THE LAST PLACE THIS COULD BE TIDIED. The wording is the lender's, quoted from a
    document, and a processor's edit on the review screen imports as they wrote it."""
    edited = "Provide the PAID invoice for the credit report, dated within 30 days."
    round_, loan_file, _ = await _draft(db_session, rows=[_row(verbatim_text=edited)])

    await import_round(db_session, round_=round_)

    (condition,) = await _conditions(db_session, loan_file.id)
    assert condition.verbatim_text == edited


async def test_every_created_condition_records_that_it_appeared(db_session: AsyncSession) -> None:
    """⚠️ THE RULE THAT WAS ALREADY BROKEN ONCE. `condition_enrich.py` created conditions and emitted
    no `CONDITION_CREATED`, so they carried no round chips while their own NOT NULL `first_round_id`
    pointed at the round that made them. Every writer of a Condition emits this event."""
    round_, loan_file, _ = await _draft(
        db_session, rows=[_row(), _row(sequence=2, lender_code="0006", verbatim_text=HOI)]
    )

    await import_round(db_session, round_=round_)

    conditions = await _conditions(db_session, loan_file.id)
    created = [
        e
        for e in await _events(db_session, round_.id)
        if e.kind is ConditionEventKind.CONDITION_CREATED
    ]
    assert {e.condition_id for e in created} == {c.id for c in conditions}


async def test_the_round_records_its_own_import(db_session: AsyncSession) -> None:
    """Spec step 5: `ROUND_IMPORTED`, with counts rather than wording."""
    round_, _file, _ = await _draft(db_session)

    await import_round(db_session, round_=round_)

    (event,) = [
        e
        for e in await _events(db_session, round_.id)
        if e.kind is ConditionEventKind.ROUND_IMPORTED
    ]
    assert event.detail["round_number"] == 1
    assert event.detail["created"] == 1
    assert event.detail["seen_again"] == 0
    assert event.condition_id is None


async def test_the_timeline_says_what_happened(db_session: AsyncSession) -> None:
    """Spec step 5's own words: "Conditions imported: N new, M seen again"."""
    round_, loan_file, _ = await _draft(db_session)

    await import_round(db_session, round_=round_)

    entry = await db_session.scalar(
        select(ActivityLog).where(
            ActivityLog.loan_file_id == loan_file.id,
            ActivityLog.activity_type == ActivityType.CONDITION_IMPORTED,
        )
    )
    assert entry is not None
    assert entry.summary == "Conditions imported: 1 new, 0 seen again"


# --------------------------------------------------------------------------- #
# Step 2 — the match
# --------------------------------------------------------------------------- #


async def _second_round(
    db: AsyncSession, *, first: ConditionRound, rows: list[dict[str, Any]]
) -> ConditionRound:
    """Another sheet for the same file — built directly, because `make_round` takes a Company and
    the first round already carries the ids this needs."""
    round_ = ConditionRound(
        company_id=first.company_id,
        loan_file_id=first.loan_file_id,
        lender_id=first.lender_id,
        status=ConditionRoundStatus.DRAFT,
        round_date=first.round_date,
        sources=[],
        parse_report={},
        draft_rows=rows,
    )
    db.add(round_)
    await db.flush()
    return round_


async def test_a_returning_condition_is_seen_again(db_session: AsyncSession) -> None:
    """The second sheet carries the same demand: one condition, two appearances."""
    first, loan_file, _ = await _draft(db_session)
    await import_round(db_session, round_=first)

    second = await _second_round(db_session, first=first, rows=[_row(sequence=4)])
    outcome = await import_round(db_session, round_=second)

    assert outcome.round_number == 2
    assert outcome.created == 0
    assert outcome.seen_again == 1

    conditions = await _conditions(db_session, loan_file.id)
    assert len(conditions) == 1, "the same demand, not a second row"
    assert conditions[0].first_round_id == first.id, "where it was first seen never moves"
    assert conditions[0].last_seen_round_id == second.id
    assert conditions[0].sequence == 4, "its place on the LATEST sheet"

    kinds = {e.kind for e in await _events(db_session, second.id)}
    assert ConditionEventKind.CONDITION_SEEN_AGAIN in kinds
    assert ConditionEventKind.CONDITION_CREATED not in kinds


async def test_a_new_underwriter_note_is_appended_once(db_session: AsyncSession) -> None:
    """A dated note inside the text means the condition came back. It is appended, and importing
    the same note again must not append it twice — the fingerprint ignores notes precisely so the
    condition still matches."""
    first, loan_file, _ = await _draft(db_session)
    await import_round(db_session, round_=first)

    note = {"date": "2026-08-28", "text": "8/28 Not in Upload"}
    second = await _second_round(db_session, first=first, rows=[_row(underwriter_notes=[note])])
    await import_round(db_session, round_=second)

    (condition,) = await _conditions(db_session, loan_file.id)
    assert [n["text"] for n in condition.underwriter_notes] == ["8/28 Not in Upload"]
    assert condition.underwriter_notes[0]["first_seen_round_id"] == str(second.id)
    assert any(
        e.kind is ConditionEventKind.CONDITION_NOTE_ADDED
        for e in await _events(db_session, second.id)
    )

    third = await _second_round(db_session, first=first, rows=[_row(underwriter_notes=[note])])
    await import_round(db_session, round_=third)

    (condition,) = await _conditions(db_session, loan_file.id)
    assert len(condition.underwriter_notes) == 1, "the same note is not appended twice"
    assert not any(
        e.kind is ConditionEventKind.CONDITION_NOTE_ADDED
        for e in await _events(db_session, third.id)
    )


async def test_same_code_different_words_creates_a_condition_and_names_the_possible_match(
    db_session: AsyncSession,
) -> None:
    """⚠️ AN ID FOR STAGE 2, NOT A DECISION HERE. Same code with different wording is either a
    rewording or a different demand filed under one template, and Stage 1 cannot tell which —
    guessing would either merge two real conditions or duplicate one, silently."""
    first, loan_file, _ = await _draft(db_session)
    await import_round(db_session, round_=first)
    (original,) = await _conditions(db_session, loan_file.id)

    second = await _second_round(
        db_session, first=first, rows=[_row(verbatim_text="Provide the paid invoice instead.")]
    )
    outcome = await import_round(db_session, round_=second)

    assert outcome.created == 1
    assert len(await _conditions(db_session, loan_file.id)) == 2

    (created,) = [
        e
        for e in await _events(db_session, second.id)
        if e.kind is ConditionEventKind.CONDITION_CREATED
    ]
    assert created.detail["possible_match"] == str(original.id)


async def test_a_condition_missing_from_the_new_sheet_is_not_touched(
    db_session: AsyncSession,
) -> None:
    """⚠️ ADR-404. Stage 1 never clears, removes or merges away a condition. Absence is Stage 2's
    evidence to weigh, and only against a sheet claiming to be complete."""
    first, loan_file, _ = await _draft(db_session)
    await import_round(db_session, round_=first)
    (kept,) = await _conditions(db_session, loan_file.id)

    second = await _second_round(
        db_session, first=first, rows=[_row(verbatim_text=HOI, lender_code="0006")]
    )
    await import_round(db_session, round_=second)

    conditions = await _conditions(db_session, loan_file.id)
    assert kept.id in {c.id for c in conditions}, "not removed"
    assert kept.deleted_at is None, "not soft-deleted"
    assert kept.last_seen_round_id == first.id, "and not claimed by a sheet it was not on"


async def test_the_two_status_fields_are_never_moved(db_session: AsyncSession) -> None:
    """ADR-404: our preparation and the lender's answer are created with defaults and nothing in
    Stage 1 moves either."""
    round_, loan_file, _ = await _draft(db_session)

    await import_round(db_session, round_=round_)

    (condition,) = await _conditions(db_session, loan_file.id)
    assert condition.prep_status is ConditionPrepStatus.TO_DO
    assert condition.lender_status is ConditionLenderStatus.OPEN


# --------------------------------------------------------------------------- #
# Step 4 — the code map
# --------------------------------------------------------------------------- #


async def _code_row(db: AsyncSession, lender_id: Any, code: str) -> LenderConditionCode | None:
    return await db.scalar(
        select(LenderConditionCode).where(
            LenderConditionCode.lender_id == lender_id, LenderConditionCode.code == code
        )
    )


async def test_an_unknown_code_is_recorded_rather_than_dropped(
    db_session: AsyncSession,
) -> None:
    """The map grows from what lenders actually send, not from what someone predicted."""
    round_, _file, lender = await _draft(db_session)

    outcome = await import_round(db_session, round_=round_)

    assert outcome.unmapped_codes == ["7086"]
    row = await _code_row(db_session, lender.id, "7086")
    assert row is not None
    assert row.status is LenderCodeStatus.OBSERVED_UNMAPPED
    assert row.times_seen == 1
    # The label is the code itself: an unknown code has no meaning, and anything else here would
    # read as a mapping somebody made.
    assert row.label == "7086"


async def test_a_mapped_code_is_counted_but_never_demoted(db_session: AsyncSession) -> None:
    """⚠️ "BUMP THE COUNTERS, NEVER RESET THE MEANING". A person reviewed this code; a sheet
    mentioning it again is not a reason to forget that."""
    round_, _file, lender = await _draft(db_session)
    db_session.add(
        LenderConditionCode(
            lender_id=lender.id,
            code="7086",
            label="Short funds to close",
            status=LenderCodeStatus.MAPPED,
            times_seen=5,
            canonical_type_id="funds_to_close",
            info_only=False,
        )
    )
    await db_session.flush()

    outcome = await import_round(db_session, round_=round_)

    row = await _code_row(db_session, lender.id, "7086")
    assert row is not None
    assert row.status is LenderCodeStatus.MAPPED, "a human decision outranks a sheet"
    assert row.times_seen == 6
    assert outcome.unmapped_codes == [], "a mapped code is not in the backlog"


async def test_the_map_fills_only_the_hint_the_sheet_did_not_give(
    db_session: AsyncSession,
) -> None:
    """⚠️ THE HINTS ARE NOT EQUALLY GOOD. A marker the lender typed is far stronger evidence than a
    default looked up from the map, and overwriting the first with the second would destroy the
    better answer while leaving the field just as populated."""
    rows = [
        _row(sequence=1, lender_code="7086"),
        _row(
            sequence=2,
            lender_code="0006",
            verbatim_text=HOI,
            owner_hint=OwnerHint.BORROWER,
            owner_hint_source=OwnerHintSource.PREFIX,
        ),
    ]
    round_, loan_file, lender = await _draft(db_session, rows=rows)
    for code in ("7086", "0006"):
        db_session.add(
            LenderConditionCode(
                lender_id=lender.id,
                code=code,
                label=f"Known {code}",
                status=LenderCodeStatus.SEEDED,
                default_owner_hint=OwnerHint.TITLE,
                canonical_type_id=f"type_{code}",
                info_only=True,
            )
        )
    await db_session.flush()

    await import_round(db_session, round_=round_)

    filled, kept = await _conditions(db_session, loan_file.id)
    assert filled.owner_hint is OwnerHint.TITLE
    assert filled.owner_hint_source is OwnerHintSource.CODE_MAP
    assert filled.canonical_type_id == "type_7086"
    assert filled.info_only is True

    assert kept.owner_hint is OwnerHint.BORROWER, "the lender's own marker stands"
    assert kept.owner_hint_source is OwnerHintSource.PREFIX


async def test_a_file_with_no_lender_still_imports(db_session: AsyncSession) -> None:
    """⚠️ A REAL STATE, NOT AN EDGE CASE. `(lender, code)` is meaningless without the lender, so the
    code-map step is skipped rather than guessed at — the conditions still land."""
    round_, loan_file, _ = await _draft(db_session, with_lender=False)

    outcome = await import_round(db_session, round_=round_)

    assert outcome.created == 1
    assert outcome.unmapped_codes == []
    (condition,) = await _conditions(db_session, loan_file.id)
    assert condition.lender_code == "7086", "the code is still carried as printed"
    assert condition.lender_id is None


# --------------------------------------------------------------------------- #
# Numbering, and the race the lock does not prevent
# --------------------------------------------------------------------------- #


async def test_the_second_import_takes_the_next_number(db_session: AsyncSession) -> None:
    first, _file, _ = await _draft(db_session)
    await import_round(db_session, round_=first)

    second = await _second_round(db_session, first=first, rows=[_row(verbatim_text=HOI)])
    outcome = await import_round(db_session, round_=second)

    assert outcome.round_number == 2


async def test_the_import_recovers_when_another_claims_its_number(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """⚠️ THE RACE `loan_file_needs_lock` DOES NOT PREVENT. The lock is advisory — it yields
    `bool(acquired)`, every call site binds nothing, and its 30s timeout auto-expires a HELD lock —
    so two imports can compute the same `max + 1`. The unique index refuses the second, and this is
    the path that catches it, rolls back the savepoint, reloads the expired round and recomputes.

    Driven by making the first computation return a number that is already taken, which is exactly
    what the losing import would compute on its own.
    """
    first, _file, _ = await _draft(db_session)
    await import_round(db_session, round_=first)  # takes number 1

    second = await _second_round(db_session, first=first, rows=[_row(verbatim_text=HOI)])

    real = condition_import._next_round_number
    calls: list[int] = []

    async def stale_then_real(db: AsyncSession, *, loan_file_id: Any) -> int:
        calls.append(1)
        if len(calls) == 1:
            return 1  # the number the other import already holds
        return await real(db, loan_file_id=loan_file_id)

    monkeypatch.setattr(condition_import, "_next_round_number", stale_then_real)

    outcome = await import_round(db_session, round_=second)

    assert outcome.round_number == 2, "it recomputed rather than failing"
    assert len(calls) == 2, "the retry actually ran"
    assert second.status is ConditionRoundStatus.IMPORTED
    assert second.draft_rows is None


async def test_the_retry_is_bounded(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """⚠️ NEVER AN UNBOUNDED LOOP. `max + 1` recomputed under contention can lose twice, and an
    unbounded retry would outlive the 30-second lock it holds — the very failure it exists to
    prevent. A typed refusal, not a silent give-up."""
    first, _file, _ = await _draft(db_session)
    await import_round(db_session, round_=first)

    second = await _second_round(db_session, first=first, rows=[_row(verbatim_text=HOI)])

    async def always_taken(db: AsyncSession, *, loan_file_id: Any) -> int:
        return 1

    monkeypatch.setattr(condition_import, "_next_round_number", always_taken)

    with pytest.raises(RoundNotImportable) as refused:
        await import_round(db_session, round_=second)
    assert "Try again" in refused.value.reason


# --------------------------------------------------------------------------- #
# What may not be imported
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "status",
    [
        ConditionRoundStatus.PARSING,
        ConditionRoundStatus.PARSE_FAILED,
        ConditionRoundStatus.IMPORTED,
        ConditionRoundStatus.DISCARDED,
    ],
)
async def test_only_a_draft_can_be_imported(
    db_session: AsyncSession, status: ConditionRoundStatus
) -> None:
    """Every other state has its own meaning, and the refusal says which one it is in rather than
    "cannot import"."""
    round_, _file, _ = await _draft(db_session, status=status)

    with pytest.raises(RoundNotImportable) as refused:
        await import_round(db_session, round_=round_)
    assert refused.value.reason

    assert round_.round_number is None, "a refused import consumes no number"


async def test_a_round_with_no_rows_is_refused(db_session: AsyncSession) -> None:
    """Importing nothing would consume a round number and produce a round claiming to be the
    lender's list while holding none of it. Discarding is the operation actually wanted."""
    round_, _file, _ = await _draft(db_session, rows=[])

    with pytest.raises(RoundNotImportable) as refused:
        await import_round(db_session, round_=round_)
    assert "Discard" in refused.value.reason
    assert round_.round_number is None


async def test_a_sheet_listing_one_demand_twice_creates_one_condition(
    db_session: AsyncSession,
) -> None:
    """The reader drops duplicates, but an edited draft can reintroduce them — and a row matched
    against one created moments earlier in the same import must not become a second row."""
    round_, loan_file, _ = await _draft(db_session, rows=[_row(sequence=1), _row(sequence=2)])

    outcome = await import_round(db_session, round_=round_)

    assert outcome.created == 1
    assert outcome.seen_again == 1
    assert len(await _conditions(db_session, loan_file.id)) == 1

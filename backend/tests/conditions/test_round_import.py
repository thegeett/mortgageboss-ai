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
from app.models.condition_round import (
    ConditionRound,
    ConditionRoundCompleteness,
    ConditionRoundStatus,
)
from app.models.lender_condition_code import LenderCodeStatus, LenderConditionCode
from app.schemas.condition import DraftRowPublic
from app.services import condition_import
from app.services.condition_import import RoundNotImportable, import_round
from sqlalchemy import event, select
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


#: "Not given", so an explicitly passed `None` still means "this round has no lender" rather than
#: "use the first round's". A plain `None` default would collapse those two, and one of the tests
#: below is precisely about a round that genuinely has none.
_KEEP = object()


async def _second_round(
    db: AsyncSession,
    *,
    first: ConditionRound,
    rows: list[dict[str, Any]],
    lender_id: Any = _KEEP,
    completeness: ConditionRoundCompleteness = ConditionRoundCompleteness.FULL,
) -> ConditionRound:
    """Another sheet for the same file — built directly, because `make_round` takes a Company and
    the first round already carries the ids this needs."""
    round_ = ConditionRound(
        company_id=first.company_id,
        loan_file_id=first.loan_file_id,
        lender_id=first.lender_id if lender_id is _KEEP else lender_id,
        status=ConditionRoundStatus.DRAFT,
        completeness=completeness,
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


async def test_a_partial_round_does_not_renumber_the_file(db_session: AsyncSession) -> None:
    """⚠️ S1-08, AS IT BROKE IN A BROWSER (LP-909 §5). A partial paste numbers its rows from the top of
    the fragment, so writing those numbers over a full list's interleaved two sheets: round 2's
    conditions took 1-2 while the one it did not carry kept 2, and the file's list — ordered by
    `sequence` — split one heading into fragments around it.

    Measured on the fixture flow before the fix: after importing the six-row round-2 paste over round
    1's eleven, sequences read 1,2,2,3,3,4,4,5,5,6,6.
    """
    rows = [
        _row(sequence=1, lender_code="1228", verbatim_text="Final inspection is required."),
        _row(sequence=2, lender_code="7086", verbatim_text="Short funds to close."),
        _row(sequence=3, lender_code="0006", verbatim_text=INVOICE),
    ]
    first, loan_file, _ = await _draft(db_session, rows=rows)
    await import_round(db_session, round_=first)

    # The processor pastes two of the three — the first and the LAST — so the paste numbers them 1, 2.
    second = await _second_round(
        db_session,
        first=first,
        rows=[rows[0], {**rows[2], "sequence": 2}],
        completeness=ConditionRoundCompleteness.PARTIAL,
    )
    outcome = await import_round(db_session, round_=second)
    assert (outcome.created, outcome.seen_again) == (0, 2)

    by_code = {c.lender_code: c.sequence for c in await _conditions(db_session, loan_file.id)}
    assert by_code == {"1228": 1, "7086": 2, "0006": 3}, "round 1's order stands"

    # And the event does not claim a move that did not happen.
    seen = [
        e
        for e in await _events(db_session, second.id)
        if e.kind is ConditionEventKind.CONDITION_SEEN_AGAIN
    ]
    assert all("sequence" not in e.detail["changed"] for e in seen)


async def test_a_full_round_still_renumbers(db_session: AsyncSession) -> None:
    """The other half: a FULL list is the lender's current order, so its positions do move a
    condition — the spec's step 2 as written, and `test_a_returning_condition_is_seen_again`'s
    "its place on the LATEST sheet"."""
    rows = [
        _row(sequence=1, lender_code="1228", verbatim_text="Final inspection is required."),
        _row(sequence=2, lender_code="0006", verbatim_text=INVOICE),
    ]
    first, loan_file, _ = await _draft(db_session, rows=rows)
    await import_round(db_session, round_=first)

    second = await _second_round(
        db_session,
        first=first,
        rows=[{**rows[1], "sequence": 1}, {**rows[0], "sequence": 2}],
        completeness=ConditionRoundCompleteness.FULL,
    )
    await import_round(db_session, round_=second)

    by_code = {c.lender_code: c.sequence for c in await _conditions(db_session, loan_file.id)}
    assert by_code == {"0006": 1, "1228": 2}


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


async def test_two_lenders_on_one_file_do_not_share_a_condition(
    db_session: AsyncSession,
) -> None:
    """⚠️ SPEC STEP 2 SCOPES BOTH PASSES TO "the same file **and lender**", AND THE WORDING PASS DID
    NOT. Measured before the fix: lender B's sheet carrying lender A's exact wording produced
    `created=0 seen_again=1` — one condition, still owned by lender A, recorded as having appeared
    on lender B's round and carrying its chip. No error and no warning.

    The same import disagreed with itself three ways: the code map recorded `(lender B, "7086")` as
    a brand-new OBSERVED_UNMAPPED entry in the very transaction where this pass declared the
    condition identical. Lender-specific in the code map, lender-specific in pass 1, lender-agnostic
    in pass 2.

    Reachable rather than theoretical: `loan_file.lender_id` is nullable and mutable, and a round
    takes the FILE's lender.
    """
    company = await make_company(db_session)
    loan_file = await make_loan_file(db_session, company=company)
    lender_a = await make_lender(db_session, company=company, name="UWM")
    lender_b = await make_lender(db_session, company=company, name="Champions")

    round_a = await make_round(db_session, company=company, loan_file=loan_file, lender=lender_a)
    round_a.draft_rows = [_row()]
    await db_session.flush()
    await import_round(db_session, round_=round_a)

    round_b = await make_round(db_session, company=company, loan_file=loan_file, lender=lender_b)
    round_b.draft_rows = [_row()]
    await db_session.flush()
    outcome = await import_round(db_session, round_=round_b)

    assert outcome.created == 1, "another lender's demand is its own condition"
    assert outcome.seen_again == 0
    conditions = await _conditions(db_session, loan_file.id)
    assert len(conditions) == 2
    assert {c.lender_id for c in conditions} == {lender_a.id, lender_b.id}


async def test_a_condition_recorded_before_the_lender_was_known_is_adopted(
    db_session: AsyncSession,
) -> None:
    """⚠️ `None` MEANS "NOT KNOWN YET", NEVER "A DIFFERENT LENDER", and the two need opposite
    handling. Refusing to match across `None` would duplicate the demand the moment the file's
    lender was set — the failure the fingerprint pass exists to prevent.

    But matching and leaving it at `None` is the other half of the defect, and it is the half that
    was silent: pass 1 could then never find the condition by `(lender, code)` again, so it would
    depend on identical wording forever and drift apart the first time the lender rephrased.
    Measured before the fix: `lender_id` stayed `None` permanently.
    """
    company = await make_company(db_session)
    loan_file = await make_loan_file(db_session, company=company)
    lender = await make_lender(db_session, company=company)

    first = await make_round(db_session, company=company, loan_file=loan_file, lender=None)
    first.draft_rows = [_row()]
    await db_session.flush()
    await import_round(db_session, round_=first)

    second = await _second_round(db_session, first=first, rows=[_row()], lender_id=lender.id)
    outcome = await import_round(db_session, round_=second)

    assert outcome.seen_again == 1, "the same demand, not a duplicate"
    (condition,) = await _conditions(db_session, loan_file.id)
    assert condition.lender_id == lender.id, "adopted by the lender that claimed it"

    (event,) = [
        e
        for e in await _events(db_session, second.id)
        if e.kind is ConditionEventKind.CONDITION_SEEN_AGAIN
    ]
    assert event.detail["changed"]["lender_adopted"] is True


async def test_a_round_with_no_lender_matches_a_condition_that_has_one(
    db_session: AsyncSession,
) -> None:
    """Compatibility runs both ways. A round whose file has no lender set does not know a DIFFERENT
    lender — it knows none — so it must match rather than duplicate, and must not blank the lender
    the condition already carries."""
    first, loan_file, lender = await _draft(db_session)
    await import_round(db_session, round_=first)

    second = await _second_round(db_session, first=first, rows=[_row()], lender_id=None)
    outcome = await import_round(db_session, round_=second)

    assert outcome.seen_again == 1
    (condition,) = await _conditions(db_session, loan_file.id)
    assert condition.lender_id == lender.id, "and it keeps the lender it had"


async def test_possible_match_names_the_oldest_condition_under_a_shared_code(
    db_session: AsyncSession,
) -> None:
    """⚠️ TWO CONDITIONS CAN SHARE `(lender, code)` BY DESIGN — a same-code/different-wording row
    creates a second one, which is what `possible_match` exists for. The lookup keeps the FIRST of
    them, and `_existing_conditions` had no `ORDER BY` at all, so "first" was whatever the planner
    returned: the id in `possible_match` could differ from run to run on identical data.
    """
    first, loan_file, _ = await _draft(db_session)
    await import_round(db_session, round_=first)
    (original,) = await _conditions(db_session, loan_file.id)

    second = await _second_round(
        db_session, first=first, rows=[_row(verbatim_text="Reworded once.")]
    )
    await import_round(db_session, round_=second)
    assert len(await _conditions(db_session, loan_file.id)) == 2, "same code, different words"

    third = await _second_round(
        db_session, first=first, rows=[_row(verbatim_text="Reworded twice.")]
    )
    await import_round(db_session, round_=third)

    (created,) = [
        e
        for e in await _events(db_session, third.id)
        if e.kind is ConditionEventKind.CONDITION_CREATED
    ]
    assert created.detail["possible_match"] == str(original.id), (
        "the original, not whichever row the planner happened to return last"
    )


async def test_the_conditions_lookup_orders_deterministically(db_session: AsyncSession) -> None:
    """⚠️ THE ONE MUTATION A BEHAVIOURAL TEST CANNOT CATCH, PINNED BY READING THE EMITTED SQL.

    Removing the `ORDER BY` from `_existing_conditions` left all 27 tests green. That is not a gap in
    the tests above; it is unobservable behaviourally. The review session measured why: they forced a
    tuple relocation — a row physically moved past another in the heap, `(0,1)` to `(0,3)` — and the
    unordered result STILL came back in creation order, because an index on `loan_file_id` serves
    this query rather than a heap scan. There is no arrangement of rows a test may legitimately
    construct that makes the missing clause show.

    So the test reads the statement instead. ⚠️ AND THIS IS NOT THE METADATA ASSERTION REJECTED FOR
    `uq_condition_rounds_file_number`: there, the model declaration and the database were two
    artifacts free to disagree, and asserting the declaration existed would have passed against one
    that never reached any database — which was the entire failure. Here the captured string IS what
    was sent to the server. It pins the statement, not that Postgres honours it; SQL semantics are
    not this test's job.

    ⚠️ THE STRICT CLAUSE, NOT A PREFIX. `"ORDER BY conditions.created_at"` would also be true of
    `... DESC`, and true of a version that dropped the `conditions.id` tiebreak — and that tiebreak
    is what makes two rows with identical `created_at` deterministic, which is reachable inside a
    single import where several conditions are created in one flush.
    """
    company = await make_company(db_session)
    loan_file = await make_loan_file(db_session, company=company)

    statements: list[str] = []

    def capture(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
    ) -> None:
        statements.append(statement)

    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", capture)
    try:
        await condition_import._existing_conditions(db_session, loan_file_id=loan_file.id)
    finally:
        event.remove(bind, "before_cursor_execute", capture)

    selects = [sql for sql in statements if "FROM conditions" in sql]
    # ⚠️ WITHOUT THIS THE TEST PASSES BY PROVING NOTHING. A listener that never fires leaves
    # `selects` empty, every assertion below is vacuously skipped, and the test reads as rigorous
    # while checking no statement at all — the exact shape this ticket has now corrected four times.
    assert selects, "no SELECT was captured: the listener never fired, so this test proves nothing"

    assert any("ORDER BY conditions.created_at, conditions.id" in sql for sql in selects), (
        "the lookup must order oldest-first with an id tiebreak, or `possible_match` names "
        f"whichever row the planner returned: {selects[-1][-160:]}"
    )


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
    prevent. A typed refusal, not a silent give-up.

    ⚠️ THE ATTEMPTS ARE COUNTED, AND WITHOUT THAT THIS TEST WAS BLIND TO ITS OWN SUBJECT (review).
    It asserted only that a refusal carrying "Try again" came out — which is true of a bound of 3, of
    25, or of 250. Measured: with `MAX_NUMBER_ATTEMPTS = 25` this test still passed, and the only
    failure anywhere came from the recovery test noticing incidentally at a bound of 1.

    The uncaught direction is the harmful one. A vanished bound is loud; an INFLATED bound is silent
    and is exactly what outlives the advisory lock. The assertion was downstream of the property
    rather than of its negation — the third time that shape has appeared in this ticket, after a
    reach assertion that could not fail and an exemption test that never invoked the walk.
    """
    first, _file, _ = await _draft(db_session)
    await import_round(db_session, round_=first)

    second = await _second_round(db_session, first=first, rows=[_row(verbatim_text=HOI)])

    calls: list[int] = []

    async def always_taken(db: AsyncSession, *, loan_file_id: Any) -> int:
        calls.append(1)
        return 1

    monkeypatch.setattr(condition_import, "_next_round_number", always_taken)

    with pytest.raises(RoundNotImportable) as refused:
        await import_round(db_session, round_=second)
    assert "Try again" in refused.value.reason
    assert len(calls) == condition_import.MAX_NUMBER_ATTEMPTS, (
        "it tried exactly the stated number of times — not merely 'it gave up eventually'"
    )
    # ⚠️ AND A CEILING, BECAUSE THE LINE ABOVE MOVES WITH THE CONSTANT IT CHECKS. Comparing the
    # attempt count to `MAX_NUMBER_ATTEMPTS` is true for ANY value of it — measured: setting the
    # constant to 25 left all 27 tests green, including this one, AFTER it had already been
    # corrected once for being blind to the bound. Same shape, one level down.
    #
    # The property is not "it tried the number it says". It is "the number it says is small enough
    # to finish inside the advisory lock it is holding". The lock auto-expires at 30 seconds and one
    # attempt is a flush plus a query, so a handful is defensible and a hundred is not.
    #
    # A ceiling rather than the exact value on purpose: `== 3` would be the guessed constant this
    # ticket was already caught on, and would fail when someone legitimately moves 3 to 4. This
    # fails only when the bound stops being a bound.
    assert condition_import.MAX_NUMBER_ATTEMPTS <= 5, (
        "a bound this large outlives the 30-second lock the retry holds — the failure it exists "
        "to prevent"
    )


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

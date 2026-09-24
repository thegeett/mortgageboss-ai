"""Attaching the lender's PDF to a round that was pasted (LP-907 section 2, spec §LP-907).

⚠️ THE ACCEPTANCE PROPERTY IS "NO SECOND ROUND AND NOTHING REMOVED" (spec §8 step 3), so that is what
most of these assert. The rest pin the guard, which is deliberately not `status = DRAFT`.
"""

from __future__ import annotations

import pytest
from app.conditions.fingerprint import fingerprint
from app.models.condition import BucketKind, Condition
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_round import (
    ConditionRound,
    ConditionRoundCompleteness,
    ConditionRoundStatus,
    ConditionSheetFormat,
    ConditionSourceKind,
)
from app.services.condition_enrich import (
    ConditionSheetRejected,
    RoundNotEnrichable,
    enrich_round_with_pdf,
)
from app.services.condition_rounds import create_round_from_paste
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.fixture_helpers import UWM_ROUND_2, portal_excerpt
from tests.conditions.uwm_pdf_fixture import render_uwm_pdf
from tests.models.conftest_helpers import make_company, make_loan_file


async def _pasted_round(
    db: AsyncSession, *, text: str | None = None
) -> tuple[ConditionRound, object]:
    """A round 2 pasted as "just some" — the state spec §8 step 2 leaves behind."""
    company = await make_company(db)
    loan_file = await make_loan_file(db, company=company)
    round_ = await create_round_from_paste(
        db,
        loan_file=loan_file,
        text=text if text is not None else portal_excerpt(),
        completeness=ConditionRoundCompleteness.PARTIAL,
    )
    return round_, loan_file


def _round_2_pdf() -> bytes:
    return render_uwm_pdf(UWM_ROUND_2)


async def test_the_pdf_fills_the_letter_details_a_paste_could_not_carry(
    db_session: AsyncSession,
) -> None:
    """Spec §8 step 3: after attaching, the round has `date_printed` 2026-09-10, the header and the
    expiry dates — none of which a copied excerpt contains."""
    round_, _file = await _pasted_round(db_session)
    assert round_.header is None and round_.date_printed is None

    result = await enrich_round_with_pdf(db_session, round_=round_, content=_round_2_pdf())

    assert result.filled_header and result.filled_expiry and result.filled_date_printed
    assert round_.date_printed is not None
    assert round_.date_printed.isoformat() == "2026-09-10"
    assert round_.header
    assert round_.expiry_dates
    assert round_.expiry_dates["close_by"] == "2026-11-03"


async def test_no_second_round_is_created(db_session: AsyncSession) -> None:
    """⚠️ THE WHOLE POINT OF THE TICKET. A second round would put round 2 on the strip twice and
    split one sheet's conditions across both."""
    round_, loan_file = await _pasted_round(db_session)

    await enrich_round_with_pdf(db_session, round_=round_, content=_round_2_pdf())

    rounds = (
        (
            await db_session.execute(
                select(ConditionRound).where(ConditionRound.loan_file_id == loan_file.id)  # type: ignore[attr-defined]
            )
        )
        .scalars()
        .all()
    )
    assert len(rounds) == 1
    assert rounds[0].id == round_.id


async def test_the_sources_are_appended_not_replaced(db_session: AsyncSession) -> None:
    """S1-09's chips read `Pasted` then `PDF upload`, in arrival order."""
    round_, _file = await _pasted_round(db_session)

    await enrich_round_with_pdf(db_session, round_=round_, content=_round_2_pdf())

    assert [source["kind"] for source in round_.sources] == [
        ConditionSourceKind.PASTE.value,
        ConditionSourceKind.PDF_UPLOAD.value,
    ]
    # The PDF's bytes are stored; the paste's source still carries no path.
    assert "storage_path" not in round_.sources[0]
    assert round_.sources[1]["storage_path"]


async def test_matching_rows_are_not_duplicated(db_session: AsyncSession) -> None:
    """⚠️ THE FINGERPRINT DOING ITS JOB. The pasted rows and the PDF's rows are the same six
    conditions; the merge must recognise them rather than append a second copy of each."""
    round_, _file = await _pasted_round(db_session)
    before = len(round_.draft_rows or [])

    result = await enrich_round_with_pdf(db_session, round_=round_, content=_round_2_pdf())

    assert before == 6
    assert result.added == 0, "the PDF carries the same six conditions the paste did"
    assert len(round_.draft_rows or []) == 6


async def test_a_pasted_row_the_pdf_does_not_carry_is_kept(db_session: AsyncSession) -> None:
    """⚠️ ADR-404: A PARTIAL SOURCE MAY ADD AND UPDATE, NEVER REMOVE. The extra row stays and is
    reported in a warning so the processor can look, rather than vanishing."""
    extra = (
        "Closing (PTF)\n 9999         Invoice                       Provide the parking receipt."
    )
    round_, _file = await _pasted_round(db_session, text=f"{portal_excerpt()}\n{extra}")
    assert len(round_.draft_rows or []) == 7

    result = await enrich_round_with_pdf(db_session, round_=round_, content=_round_2_pdf())

    texts = [row["verbatim_text"] for row in round_.draft_rows or []]
    assert "Provide the parking receipt." in texts
    assert result.unmatched_existing
    assert any("kept, not removed" in warning for warning in result.warnings)


async def test_a_pdf_row_the_paste_missed_is_added_to_this_round(
    db_session: AsyncSession,
) -> None:
    """The paste was partial, so the PDF's extra conditions belong to the SAME round."""
    two_rows = "\n".join(portal_excerpt().splitlines()[:4])
    round_, _file = await _pasted_round(db_session, text=two_rows)
    before = len(round_.draft_rows or [])

    result = await enrich_round_with_pdf(db_session, round_=round_, content=_round_2_pdf())

    assert result.added > 0
    assert len(round_.draft_rows or []) == before + result.added


async def test_the_merge_never_overwrites_wording_the_processor_can_see(
    db_session: AsyncSession,
) -> None:
    """⚠️ OUR RULE, NOT THE SPEC'S — recorded in the ticket. The PDF may fill a hole; it never
    replaces a value already on the row, and `verbatim_text` is never touched by a merge."""
    round_, _file = await _pasted_round(db_session)
    rows = list(round_.draft_rows or [])
    rows[3]["lender_category"] = "Edited by the processor"
    round_.draft_rows = rows
    await db_session.flush()

    await enrich_round_with_pdf(db_session, round_=round_, content=_round_2_pdf())

    assert (round_.draft_rows or [])[3]["lender_category"] == "Edited by the processor"


async def test_the_format_is_upgraded_from_pasted_text(db_session: AsyncSession) -> None:
    """A pasted round's format was inferred from row shapes; the PDF names the layout outright.

    ⚠️ A NUMBERED LIST RATHER THAN PROSE, and the difference is LP-908 §2. Prose sets `needs_ai`, so
    the paste now opens `PARSING` and enrich refuses it — correctly, because the split task owns that
    state. A numbered list is structure the generic reader recognises, so the round lands `DRAFT`
    with `PASTED_TEXT`, which is the state this test is actually about.
    """
    round_, _file = await _pasted_round(
        db_session,
        text="1. Provide the final settlement statement.\n2. Provide the signed note.",
    )
    assert round_.status is ConditionRoundStatus.DRAFT
    assert round_.sheet_format is ConditionSheetFormat.PASTED_TEXT

    await enrich_round_with_pdf(db_session, round_=round_, content=_round_2_pdf())

    assert round_.sheet_format is ConditionSheetFormat.UWM_APPROVAL_LETTER


async def test_enriching_writes_a_round_enriched_event(db_session: AsyncSession) -> None:
    round_, _file = await _pasted_round(db_session)

    await enrich_round_with_pdf(db_session, round_=round_, content=_round_2_pdf())

    events = (
        (
            await db_session.execute(
                select(ConditionEvent).where(
                    ConditionEvent.round_id == round_.id,
                    ConditionEvent.kind == ConditionEventKind.ROUND_ENRICHED,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1
    # ⚠️ Counts and names only — never the sheet's text (spec §9.5).
    assert set(events[0].detail) == {
        "reader",
        "matched",
        "added",
        "unmatched_existing",
        "filled_header",
        "filled_expiry",
    }


async def test_attaching_a_second_pdf_is_refused(db_session: AsyncSession) -> None:
    """⚠️ THE GUARD IS "NO PDF SOURCE YET", so this is the same shape of refusal the forward door
    now gives a repeated forward — and it is what stops one sheet being merged twice."""
    round_, _file = await _pasted_round(db_session)
    await enrich_round_with_pdf(db_session, round_=round_, content=_round_2_pdf())

    with pytest.raises(RoundNotEnrichable) as refused:
        await enrich_round_with_pdf(db_session, round_=round_, content=_round_2_pdf())

    assert "already has the lender's PDF" in refused.value.reason


@pytest.mark.parametrize(
    "status", [ConditionRoundStatus.PARSING, ConditionRoundStatus.PARSE_FAILED]
)
async def test_a_round_that_is_not_active_cannot_be_enriched(
    db_session: AsyncSession, status: ConditionRoundStatus
) -> None:
    """⚠️ `PARSING` IS EXCLUDED DELIBERATELY. The parse task owns that state through a compare-and-set
    guarded on it; enriching a round mid-parse would race the task that is writing it."""
    round_, _file = await _pasted_round(db_session)
    round_.status = status
    await db_session.flush()

    with pytest.raises(RoundNotEnrichable) as refused:
        await enrich_round_with_pdf(db_session, round_=round_, content=_round_2_pdf())

    assert status.value in refused.value.reason


async def test_an_imported_round_merges_into_its_conditions(db_session: AsyncSession) -> None:
    """Spec: "Works for DRAFT and IMPORTED rounds" — and S1-08 puts the button on an imported card.

    An imported round's rows are `Condition` rows with identity, so the merge fills those instead of
    `draft_rows`, and must still not duplicate them.
    """
    round_, loan_file = await _pasted_round(db_session)
    rows = list(round_.draft_rows or [])
    for index, row in enumerate(rows, start=1):
        db_session.add(
            Condition(
                company_id=round_.company_id,
                loan_file_id=round_.loan_file_id,
                first_round_id=round_.id,
                last_seen_round_id=round_.id,
                sequence=index,
                # ⚠️ NO CODE, which is the realistic state: a pasted excerpt often has none, and
                # filling it from the PDF is the enrichment the spec asks for.
                lender_code=None,
                bucket_heading=row["bucket_heading"],
                bucket_kind=BucketKind(row["bucket_kind"]),
                verbatim_text=row["verbatim_text"],
                text_fingerprint=fingerprint(row["verbatim_text"]),
                underwriter_notes=[],
            )
        )
    round_.status = ConditionRoundStatus.IMPORTED
    round_.round_number = 2
    round_.draft_rows = None
    await db_session.flush()

    result = await enrich_round_with_pdf(db_session, round_=round_, content=_round_2_pdf())

    conditions = (
        (
            await db_session.execute(
                select(Condition).where(Condition.loan_file_id == loan_file.id)  # type: ignore[attr-defined]
            )
        )
        .scalars()
        .all()
    )
    assert len(conditions) == 6, "matched by fingerprint, so no condition is duplicated"
    assert result.added == 0
    # The codes the paste could not carry are now filled from the letter.
    assert sorted(c.lender_code or "" for c in conditions) == [
        "0006",
        "0007",
        "1228",
        "1582",
        "1947",
        "6378",
    ]


async def test_a_condition_the_pdf_adds_to_an_imported_round_records_that_it_appeared(
    db_session: AsyncSession,
) -> None:
    """⚠️ IMPORT IS NOT THE ONLY WRITER OF CONDITIONS, AND THIS IS THE SECOND ONE.

    "Which rounds did a condition appear on" is derived from `CONDITION_CREATED` /
    `CONDITION_SEEN_AGAIN` events (spec §LP-909) — the `R1 R2` chips, and the round card's own
    count. A condition created here WITHOUT that event gets no chips at all, while its own
    `first_round_id` and `last_seen_round_id` both point at this very round, and the round
    undercounts itself by exactly the number added.

    Reachable rather than theoretical: paste, import, then attach the lender's PDF — the flow
    `attach-pdf` exists for, reached from the review screen's own "Attach the lender's PDF" action.
    Nothing pinned it until this test: the `added` assertions above are the DRAFT path, which
    correctly has no events because a draft has no conditions yet.
    """
    round_, loan_file = await _pasted_round(db_session)
    # Import only the FIRST two rows, so the PDF brings four the round has never seen.
    rows = list(round_.draft_rows or [])[:2]
    for index, row in enumerate(rows, start=1):
        db_session.add(
            Condition(
                company_id=round_.company_id,
                loan_file_id=round_.loan_file_id,
                first_round_id=round_.id,
                last_seen_round_id=round_.id,
                sequence=index,
                lender_code=row["lender_code"],
                bucket_heading=row["bucket_heading"],
                bucket_kind=BucketKind(row["bucket_kind"]),
                verbatim_text=row["verbatim_text"],
                text_fingerprint=fingerprint(row["verbatim_text"]),
                underwriter_notes=[],
            )
        )
    round_.status = ConditionRoundStatus.IMPORTED
    round_.round_number = 2
    round_.draft_rows = None
    await db_session.flush()

    result = await enrich_round_with_pdf(db_session, round_=round_, content=_round_2_pdf())

    assert result.added == 4, "the PDF carries four conditions this round had not imported"

    created = (
        (
            await db_session.execute(
                select(ConditionEvent).where(
                    ConditionEvent.round_id == round_.id,
                    ConditionEvent.kind == ConditionEventKind.CONDITION_CREATED,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(created) == result.added, "every added condition records that it appeared here"
    # Each event names a real condition, so the chips and the count can be derived from it.
    condition_ids = set(
        (
            await db_session.execute(
                select(Condition.id).where(Condition.loan_file_id == loan_file.id)  # type: ignore[attr-defined]
            )
        )
        .scalars()
        .all()
    )
    assert {event.condition_id for event in created} <= condition_ids
    # ⚠️ Counts and codes only — never the lender's wording (spec §9.5).
    assert all(set(event.detail) == {"source", "lender_code"} for event in created)


async def test_something_that_is_not_a_pdf_is_refused(db_session: AsyncSession) -> None:
    """The same typed refusal the upload door gives, for the same reason (spec §9.8)."""
    round_, _file = await _pasted_round(db_session)

    with pytest.raises(ConditionSheetRejected):
        await enrich_round_with_pdf(db_session, round_=round_, content=b"this is not a pdf")

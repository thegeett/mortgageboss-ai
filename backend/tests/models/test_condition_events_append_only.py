"""`condition_events` is append-only, and this is the guard `finding_events` never had (LP-904).

WHY THIS EXISTS AT ALL. The spec says to copy `models/finding_event.py` **and its tests**. The
model is there; the tests are not. Every test in the suite that touches `FindingEvent` only READS
event rows to assert a lifecycle sequence — `tests/services/test_finding_reconcile_runs.py` and
`tests/services/test_unidentified_document_lifecycle_lp640.py`. Nothing anywhere asserts that an
event cannot be updated or deleted. So this is written from scratch rather than copied.

WHAT "APPEND-ONLY" MEANS HERE, PRECISELY. It is not a runtime check and there is no trigger. It is
enforced by the SHAPE of the row: the model inherits `Base, UUIDMixin` and nothing else, so there is
no `updated_at` to touch and no `deleted_at` to set. A mutation is not refused — it is
*inexpressible*, which is the stronger property and the one that cannot be forgotten by a later
caller.

AND WHAT THIS TEST DOES NOT CHECK, stated rather than implied. LP-904's done-when says the guard
should show the rows cannot be changed "through the service layer". **There is no service layer
yet** — LP-904 is models, schemas and a migration. So the assertions below are about the mechanism
that makes a mutating service impossible to write, not about a service refusing one. When LP-909's
import service lands, the test that belongs beside it is "the only operation this service performs on
condition_events is an insert", and that is a different test from this one.
"""

from __future__ import annotations

from app.models.base import SoftDeleteMixin, TimestampMixin
from app.models.condition_event import ConditionEvent, ConditionEventKind
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.models.conftest_helpers import make_company, make_loan_file


def test_the_row_has_nowhere_to_record_a_change() -> None:
    """No `updated_at` and no `deleted_at` — the columns a mutation would need.

    Asserted on the table rather than on the class, because the mixins are what would add them and
    the question is what the DATABASE has. A later edit that added `TimestampMixin` "for consistency"
    would give every row an `updated_at` that can only ever lie: either it equals `occurred_at`
    forever, or something updated a row that must not be updated.
    """
    columns = {column.name for column in ConditionEvent.__table__.columns}

    assert "updated_at" not in columns, (
        "condition_events gained an updated_at. On an append-only row that column can only lie — "
        "see the model docstring and finding_events, which deliberately has neither."
    )
    assert "deleted_at" not in columns, (
        "condition_events gained a deleted_at, which makes a mutating soft-delete expressible. "
        "Append-only means the row is inserted and never touched again."
    )
    # `occurred_at` is the row's own time and replaces both.
    assert "occurred_at" in columns


def test_it_does_not_inherit_the_mixins_that_would_permit_mutation() -> None:
    """The mechanism, not just its symptom.

    The column test above would also pass if someone added the mixins and then dropped the columns by
    hand, which is a state nobody should be able to reach. This asserts the inheritance itself, so
    the two together say "no mixin, and therefore no column".
    """
    assert not issubclass(ConditionEvent, TimestampMixin), (
        "ConditionEvent inherits TimestampMixin, which adds updated_at"
    )
    assert not issubclass(ConditionEvent, SoftDeleteMixin), (
        "ConditionEvent inherits SoftDeleteMixin, which permits a mutating delete"
    )


async def test_events_accumulate_rather_than_replace(db_session: AsyncSession) -> None:
    """Two events on one round are two rows. The positive half of append-only.

    Without this, a future "upsert the latest event" would satisfy every assertion above — no column
    changed, no mixin added — while destroying the history the table exists for.
    """
    company = await make_company(db_session)
    loan_file = await make_loan_file(db_session, company=company)

    first = ConditionEvent(
        company_id=company.id,
        loan_file_id=loan_file.id,
        round_id=None,
        condition_id=None,
        kind=ConditionEventKind.ROUND_RECEIVED,
        detail={"source": "pdf_upload"},
    )
    second = ConditionEvent(
        company_id=company.id,
        loan_file_id=loan_file.id,
        round_id=None,
        condition_id=None,
        kind=ConditionEventKind.ROUND_PARSED,
        detail={"reader": "uwm", "rows": 11},
    )
    db_session.add_all([first, second])
    await db_session.flush()

    rows = (
        await db_session.scalars(
            select(ConditionEvent)
            .where(ConditionEvent.loan_file_id == loan_file.id)
            .order_by(ConditionEvent.occurred_at)
        )
    ).all()

    assert [row.kind for row in rows] == [
        ConditionEventKind.ROUND_RECEIVED,
        ConditionEventKind.ROUND_PARSED,
    ]
    assert rows[0].id != rows[1].id


async def test_a_round_event_needs_no_condition_and_the_reverse(db_session: AsyncSession) -> None:
    """Both foreign keys are nullable, and both directions are legitimate.

    A `ROUND_RECEIVED` has no condition — none exist yet. A `CONDITION_EDITED` outside an import has
    no round. Modelling either as required would force a caller to invent a value, which is how a
    history stops being trustworthy.
    """
    company = await make_company(db_session)
    loan_file = await make_loan_file(db_session, company=company)

    event = ConditionEvent(
        company_id=company.id,
        loan_file_id=loan_file.id,
        kind=ConditionEventKind.CONDITION_EDITED,
        detail={"field": "verbatim_text"},
    )
    db_session.add(event)
    await db_session.flush()

    assert event.round_id is None
    assert event.condition_id is None
    assert event.occurred_at is not None


def test_no_event_kind_can_state_a_clearing_on_its_own() -> None:
    """ADR-404 and ADR-408, asserted rather than trusted to prose.

    NOTHING MAY CLEAR A CONDITION BY EXISTING. A `condition_cleared` member added "for later" would
    be writable immediately, by anything, with no verdict recorded and no UI showing it — and the
    whole architecture of the two tracks rests on `cleared` being reachable only through a recorded
    verdict naming who said so and where. That is why the clearing kinds stay out of this enum
    *permanently*, not until some later stage earns them: the mechanism that clears is
    `CONDITION_VERDICT_RECORDED`, whose detail carries the verdict, and a bare
    `condition_cleared` would be the app asserting the lender's answer without its provenance.

    THE TEST TO APPLY BEFORE ADDING AN EVENT KIND — a question, not a category:
    **could a reader of this row infer that the lender answered, WITHOUT the row saying where the
    lender said it?**

    (Sharpened in LP-912's review. The first wording was "infer that the lender answered, from the row
    alone", and `condition_came_back` fails that as written: it does state the lender's answer, "not
    satisfied". What makes it allowed is that it carries its provenance, a verdict sourced to the
    `underwriter_note` with that note's date, exactly as `CONDITION_VERDICT_RECORDED` does. Part 2 must
    assert that detail on the event it writes, or `came_back` becomes the bare claim this test exists
    to forbid.)

      * `condition_cleared` / `condition_waived` / `condition_removed` — yes, each STATES one. Always
        forbidden.
      * `CONDITION_VERDICT_RECORDED` — no, and this is the distinction that matters. It says a verdict
        was recorded; WHAT the lender said is in the verdict, with its source and its date. The row is
        a pointer to evidence rather than a claim standing on its own.
      * `ROUND_COMPARED` — no longer forbidden, and this test was NARROWED to let it in (LP-912).
        Stage 1's version of this test forbade it on the argument that comparison "MANUFACTURES" a
        lender answer, and that was right while nothing could confirm one: the row's existence would
        have been the only evidence the inference ran. LP-915 adds it with the confirm step that earns
        it — the comparison PROPOSES and the processor's click is what records a verdict — so the
        inference is no longer readable off the row, because the row no longer decides anything. Its
        own docstring anticipated this: "Stage 2 adds the member together with the comparison that
        earns it."
      * `ROUND_ENRICHED` — no. It says a second arrival merged into a round, and merging provenance
        cannot be read as the lender speaking.

    An earlier version of this reasoning said the forbidden kinds were "verdicts about a condition's
    fate". That rule fails on its own list: `round_compared` was not a verdict about any condition's
    fate, which is exactly how it would have slipped in under the wrong rule rather than the right one.
    """
    kinds = {kind.value for kind in ConditionEventKind}

    # PERMANENTLY FORBIDDEN, unlike `round_compared` above. No stage earns these, because each would
    # state the lender's answer with nothing attached saying where it came from.
    forbidden = {"condition_cleared", "condition_removed", "condition_waived"}
    assert not (kinds & forbidden), (
        f"ConditionEventKind gained {sorted(kinds & forbidden)}. Nothing may state a clearing on its "
        "own (ADR-404, ADR-408): a cleared or waived condition is recorded as "
        "CONDITION_VERDICT_RECORDED carrying a verdict with its source and date, so that 'cleared' is "
        "always answerable with 'who said so, and where'."
    )

    # AND THE MECHANISM THAT REPLACES THEM MUST BE PRESENT, or the paragraph above describes nothing.
    # Asserting the absence alone would pass just as happily against an enum that cannot record a
    # verdict either — which would mean the product simply could not express what the lender said.
    assert "condition_verdict_recorded" in kinds, (
        "CONDITION_VERDICT_RECORDED is missing, so the clearing kinds are absent with nothing in "
        "their place. ADR-408 makes the verdict the only way to say the lender cleared something."
    )

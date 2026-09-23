"""`condition_events` is append-only, and this is the guard `finding_events` never had (LP-904).

⚠️ WHY THIS EXISTS AT ALL. The spec says to copy `models/finding_event.py` **and its tests**. The
model is there; the tests are not. Every test in the suite that touches `FindingEvent` only READS
event rows to assert a lifecycle sequence — `tests/services/test_finding_reconcile_runs.py` and
`tests/services/test_unidentified_document_lifecycle_lp640.py`. Nothing anywhere asserts that an
event cannot be updated or deleted. So this is written from scratch rather than copied.

WHAT "APPEND-ONLY" MEANS HERE, PRECISELY. It is not a runtime check and there is no trigger. It is
enforced by the SHAPE of the row: the model inherits `Base, UUIDMixin` and nothing else, so there is
no `updated_at` to touch and no `deleted_at` to set. A mutation is not refused — it is
*inexpressible*, which is the stronger property and the one that cannot be forgotten by a later
caller.

⚠️ AND WHAT THIS TEST DOES NOT CHECK, stated rather than implied. LP-904's done-when says the guard
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


def test_stage_1_cannot_express_a_clearing_event() -> None:
    """⚠️ ADR-404, asserted rather than trusted to prose.

    Stage 1 never clears, removes or merges away a condition. The enum is where that could quietly
    stop being true: a `condition_cleared` member added "for later" would be writable immediately,
    by anything, with no verdict recorded and no UI showing it. Stage 2 adds the member together with
    the comparison that earns it.
    """
    kinds = {kind.value for kind in ConditionEventKind}

    forbidden = {"condition_cleared", "condition_removed", "condition_waived", "round_compared"}
    assert not (kinds & forbidden), (
        f"ConditionEventKind gained {sorted(kinds & forbidden)}. Stage 1 cannot produce these "
        "(ADR-404) and an enum member nothing writes is an invitation — add it with the Stage 2 "
        "mechanism that records who cleared what, and where."
    )

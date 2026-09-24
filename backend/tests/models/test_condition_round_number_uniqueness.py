"""One round number per file — the index that IS the rule (LP-904, LP-909 §2).

⚠️ THIS INDEX EXISTED IN PRODUCTION AND IN NO TEST DATABASE, AND NOTHING NOTICED. LP-904's migration
creates `uq_condition_rounds_file_number` with raw SQL; `ConditionRound.__table_args__` did not
declare it. The suite builds its schema with `Base.metadata.create_all`, not with migrations, so for
the whole of Stage 1 two rounds numbered 2 on one file inserted cleanly in every test — measured, not
inferred, before the declaration was added.

That is the exact mirror of the trap LP-904 documented and then fell into. Its own ticket says
`str_enum`'s CHECK "only materialises through `Base.metadata.create_all` — which is what the suite
builds from, and precisely why an enum/database mismatch is invisible to it". An index that lives
only in a migration is invisible the same way, in the other direction. `tests/test_activity_type_
migrations.py` guards the enum half; this file guards this index.

WHY IT IS NOT MERELY TIDINESS. `loan_file_needs_lock` is ADVISORY, not mutual exclusion: it yields
`bool(acquired)`, all three existing call sites bind nothing, and its `timeout=30` auto-expires a
HELD lock, so a long import loses it mid-transaction while still working. Nothing else stops two
concurrent imports computing the same `max + 1`. This index is what actually prevents it, and
LP-909's import catches the violation and recomputes against it.

THE TESTS ARE BEHAVIOURAL, NOT METADATA ASSERTIONS. Checking that the `Index` object is present in
`__table_args__` would pass against a declaration that never reaches the database — which is the
failure being guarded. Provoking the violation is the only check that cannot be satisfied by an
index that exists on paper.
"""

from __future__ import annotations

import datetime as dt

import pytest
from app.models.base import utcnow
from app.models.condition_round import ConditionRound, ConditionRoundStatus
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from tests.models.conftest_helpers import make_company, make_loan_file

#: The index LP-904 creates. Named here because a test that accepted ANY `IntegrityError` would pass
#: on a NOT NULL violation, a foreign key, or a different unique index entirely — and would go on
#: passing after the index it exists to guard was removed.
INDEX = "uq_condition_rounds_file_number"


def _round(
    *,
    company_id: object,
    loan_file_id: object,
    number: int | None,
    status: ConditionRoundStatus = ConditionRoundStatus.IMPORTED,
) -> ConditionRound:
    return ConditionRound(
        company_id=company_id,
        loan_file_id=loan_file_id,
        round_number=number,
        status=status,
        round_date=dt.date(2026, 9, 24),
    )


def _violated_constraint(error: IntegrityError) -> str | None:
    """The constraint that actually failed.

    ⚠️ MEASURED, BECAUSE THE OBVIOUS PLACE IS EMPTY. `error.orig` is SQLAlchemy's
    `asyncpg.IntegrityError` wrapper and carries NO `constraint_name` at all; the name lives on its
    `__cause__`, the underlying `asyncpg.UniqueViolationError`. Reading `error.orig.constraint_name`
    returns nothing and a comparison against it is quietly always False — a check that reads as
    rigorous and can never fire.
    """
    cause = getattr(error.orig, "__cause__", None)
    return getattr(cause, "constraint_name", None)


async def test_two_imported_rounds_cannot_share_a_number_on_one_file(
    db_session: AsyncSession,
) -> None:
    """⚠️ THE PROPERTY THE WHOLE IMPORT RETRY IS BUILT ON. Two sheets both recorded as "round 2"
    would put one file's history in two places with nothing able to tell them apart."""
    company = await make_company(db_session)
    loan_file = await make_loan_file(db_session, company=company)

    db_session.add(_round(company_id=company.id, loan_file_id=loan_file.id, number=2))
    await db_session.flush()

    savepoint = await db_session.begin_nested()
    db_session.add(_round(company_id=company.id, loan_file_id=loan_file.id, number=2))
    with pytest.raises(IntegrityError) as caught:
        await db_session.flush()
    await savepoint.rollback()

    assert _violated_constraint(caught.value) == INDEX


async def test_the_same_number_on_a_different_file_is_fine(db_session: AsyncSession) -> None:
    """The index is per FILE. Every file has its own round 1, and a global constraint would be
    wrong on its second loan file."""
    company = await make_company(db_session)
    # No identifiers passed: `make_loan_file` goes through `create_loan_file`, which generates
    # `display_id` and `inbox_token` itself (ADR-036/ADR-050). Its docstring is emphatic about this
    # and I passed a `display_id` it does not accept — the helper exists because a bare
    # `LoanFile(...)` dies in SETUP before a single assertion runs.
    one = await make_loan_file(db_session, company=company)
    two = await make_loan_file(db_session, company=company)

    db_session.add(_round(company_id=company.id, loan_file_id=one.id, number=1))
    db_session.add(_round(company_id=company.id, loan_file_id=two.id, number=1))
    await db_session.flush()  # no violation


async def test_numberless_drafts_do_not_collide(db_session: AsyncSession) -> None:
    """⚠️ WHY THE INDEX IS PARTIAL. Numbers are assigned on import, so a file can hold several
    drafts at once — an upload and a paste — all with `round_number` NULL. A non-partial unique
    index would refuse the second one and break the paste door."""
    company = await make_company(db_session)
    loan_file = await make_loan_file(db_session, company=company)

    for _ in range(3):
        db_session.add(
            _round(
                company_id=company.id,
                loan_file_id=loan_file.id,
                number=None,
                status=ConditionRoundStatus.DRAFT,
            )
        )
    await db_session.flush()  # no violation


async def test_a_discarded_round_keeps_its_number(db_session: AsyncSession) -> None:
    """⚠️ `status = 'imported'` IS DELIBERATELY NOT IN THE PREDICATE, and LP-904's migration records
    why it was removed in review: `condition_events` is append-only, so a discarded round's
    ROUND_IMPORTED event survives forever. Freeing its number for reuse would leave two different
    sheets both recorded as "round 2" in an immutable history."""
    company = await make_company(db_session)
    loan_file = await make_loan_file(db_session, company=company)

    first = _round(company_id=company.id, loan_file_id=loan_file.id, number=1)
    db_session.add(first)
    await db_session.flush()
    first.status = ConditionRoundStatus.DISCARDED
    await db_session.flush()

    savepoint = await db_session.begin_nested()
    db_session.add(_round(company_id=company.id, loan_file_id=loan_file.id, number=1))
    with pytest.raises(IntegrityError) as caught:
        await db_session.flush()
    await savepoint.rollback()

    assert _violated_constraint(caught.value) == INDEX


async def test_a_soft_deleted_round_releases_its_number(db_session: AsyncSession) -> None:
    """`deleted_at IS NULL` STAYS in the predicate, and the difference from DISCARDED is the point:
    a soft delete is an explicit act by a person, so releasing the number is the visible consequence
    of a deliberate decision rather than a side effect of a status change."""
    company = await make_company(db_session)
    loan_file = await make_loan_file(db_session, company=company)

    first = _round(company_id=company.id, loan_file_id=loan_file.id, number=1)
    db_session.add(first)
    await db_session.flush()
    first.deleted_at = utcnow()
    await db_session.flush()

    db_session.add(_round(company_id=company.id, loan_file_id=loan_file.id, number=1))
    await db_session.flush()  # the number is free again


async def test_the_session_survives_the_violation_and_can_recompute(
    db_session: AsyncSession,
) -> None:
    """⚠️ THE EXACT SHAPE LP-909's IMPORT RETRY DEPENDS ON, pinned here rather than discovered there.

    After the violation, asyncpg refuses every further statement on the transaction until the
    savepoint is unwound — so a recompute issued without rolling back never runs at all, and the
    failure looks like the retry silently not happening. This asserts the recompute works AFTER the
    rollback, which is what makes "catch, recompute, succeed" a real strategy rather than a hope.
    """
    from sqlalchemy import func, select

    company = await make_company(db_session)
    loan_file = await make_loan_file(db_session, company=company)

    db_session.add(_round(company_id=company.id, loan_file_id=loan_file.id, number=1))
    await db_session.flush()

    savepoint = await db_session.begin_nested()
    db_session.add(_round(company_id=company.id, loan_file_id=loan_file.id, number=1))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await savepoint.rollback()

    highest = await db_session.scalar(
        select(func.max(ConditionRound.round_number)).where(
            ConditionRound.loan_file_id == loan_file.id
        )
    )
    assert highest == 1

    db_session.add(_round(company_id=company.id, loan_file_id=loan_file.id, number=highest + 1))
    await db_session.flush()  # the retry succeeds

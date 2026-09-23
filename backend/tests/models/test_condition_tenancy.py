"""One company cannot reach another's rounds or conditions (LP-904 done-when).

THE REASON THESE TABLES CARRY `company_id` AT ALL. Most file-owned children do not — a `Document` is
scoped transitively through its loan file (ADR-052), because it is only ever reached *through* one.
A round and a condition are different: `/api/condition-rounds/{round_id}` and
`/api/condition-rounds/{id}/import` take an id straight from the path, so there is no parent in the
request to scope against. The column is what `scope_to_company` filters on, and without it the only
thing standing between two tenants would be a join somebody has to remember to write.

`lender_condition_codes` deliberately has NO `company_id` and is not tested here: it is reached only
through its lender, which carries one, so it scopes transitively like a document does. That asymmetry
is the thing worth understanding, and it is the reason each table's scoping is stated in its model.
"""

from __future__ import annotations

from app.models.condition import Condition
from app.models.condition_round import ConditionRound
from app.models.helpers import only_active, scope_to_company
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.models.conftest_helpers import (
    make_company,
    make_condition,
    make_lender,
    make_loan_file,
    make_round,
)


async def test_a_companys_rounds_are_invisible_to_another(db_session: AsyncSession) -> None:
    """The query a list endpoint runs, against a database holding two tenants' rounds."""
    acme = await make_company(db_session, name="Acme Processing")
    rival = await make_company(db_session, name="Rival Processing")
    acme_file = await make_loan_file(db_session, company=acme)
    rival_file = await make_loan_file(db_session, company=rival)
    acme_round = await make_round(db_session, company=acme, loan_file=acme_file)
    rival_round = await make_round(db_session, company=rival, loan_file=rival_file)

    stmt = scope_to_company(select(ConditionRound), ConditionRound, acme.id)
    visible = (await db_session.scalars(only_active(stmt, ConditionRound))).all()

    ids = {row.id for row in visible}
    assert acme_round.id in ids
    assert rival_round.id not in ids, "a round leaked across companies"


async def test_a_companys_conditions_are_invisible_to_another(db_session: AsyncSession) -> None:
    """The same, for the table holding the lender's words — where a leak costs most."""
    acme = await make_company(db_session, name="Acme Processing")
    rival = await make_company(db_session, name="Rival Processing")
    acme_file = await make_loan_file(db_session, company=acme)
    rival_file = await make_loan_file(db_session, company=rival)
    acme_lender = await make_lender(db_session, company=acme)
    rival_lender = await make_lender(db_session, company=rival)
    acme_round = await make_round(db_session, company=acme, loan_file=acme_file, lender=acme_lender)
    rival_round = await make_round(
        db_session, company=rival, loan_file=rival_file, lender=rival_lender
    )
    mine = await make_condition(
        db_session,
        company=acme,
        loan_file=acme_file,
        round_=acme_round,
        lender=acme_lender,
        verbatim_text="Provide copy of invoice for credit report.",
    )
    theirs = await make_condition(
        db_session,
        company=rival,
        loan_file=rival_file,
        round_=rival_round,
        lender=rival_lender,
        verbatim_text="Provide the final Seller Closing Disclosure.",
    )

    stmt = scope_to_company(select(Condition), Condition, acme.id)
    visible = (await db_session.scalars(only_active(stmt, Condition))).all()

    ids = {row.id for row in visible}
    assert mine.id in ids
    assert theirs.id not in ids, "a condition — and the lender's wording on it — leaked"


async def test_scoping_is_not_satisfied_by_the_loan_file_alone(db_session: AsyncSession) -> None:
    """⚠️ THE MISTAKE THIS COLUMN PREVENTS, made deliberately so the test has something to catch.

    A query that filters only on `loan_file_id` looks correct and is correct *for that file* — but it
    is the shape that cannot be written at all for the flat routes, where no loan file is in the
    request. Here the unscoped query returns both tenants' rows, which is what a missing
    `scope_to_company` produces the moment two companies share the table.
    """
    acme = await make_company(db_session, name="Acme Processing")
    rival = await make_company(db_session, name="Rival Processing")
    acme_round = await make_round(
        db_session, company=acme, loan_file=await make_loan_file(db_session, company=acme)
    )
    rival_round = await make_round(
        db_session, company=rival, loan_file=await make_loan_file(db_session, company=rival)
    )

    unscoped = (await db_session.scalars(select(ConditionRound))).all()
    both = {acme_round.id, rival_round.id}

    assert both <= {row.id for row in unscoped}, (
        "the fixture failed to create two tenants' rounds, so the assertion below proves nothing"
    )
    scoped = (
        await db_session.scalars(scope_to_company(select(ConditionRound), ConditionRound, acme.id))
    ).all()
    assert {row.id for row in scoped} == {acme_round.id}


async def test_soft_deleted_rounds_are_excluded_by_only_active(db_session: AsyncSession) -> None:
    """`scope_to_company` and `only_active` compose; neither substitutes for the other."""
    from app.models.base import utcnow

    acme = await make_company(db_session)
    loan_file = await make_loan_file(db_session, company=acme)
    kept = await make_round(db_session, company=acme, loan_file=loan_file)
    dropped = await make_round(db_session, company=acme, loan_file=loan_file)
    dropped.deleted_at = utcnow()
    await db_session.flush()

    stmt = only_active(
        scope_to_company(select(ConditionRound), ConditionRound, acme.id), ConditionRound
    )
    visible = (await db_session.scalars(stmt)).all()

    assert {row.id for row in visible} == {kept.id}

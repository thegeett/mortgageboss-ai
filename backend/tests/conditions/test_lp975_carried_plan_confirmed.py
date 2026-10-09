"""LP-975 — a carried condition's plan is in force only if she confirmed it.

Whether a plan was in force was asked of the condition's LAST-SEEN round, and a condition seen again moves
to the new round. Two directions, both reproduced here before the fix:

1. Round 1 confirmed, round 2 imported: the plan she confirmed stopped counting — round 1's email for a
   condition round 2 listed again was refused ("Confirm the plan for round 2 first").
2. Round 1 NOT confirmed, round 2 imported and confirmed: the carried plan came into force though she was
   never shown it (the screen half is the panel's; the server half is the stamp it reads).

Round 1 and round 2 of the fictional UWM file (six conditions seen again).
"""

from __future__ import annotations

from typing import Any

import pytest
from app.models.condition import Condition
from app.models.condition_draft import ConditionDraft
from app.models.condition_round import ConditionRound, ConditionSourceKind
from app.models.loan_file import LoanFile
from app.schemas.condition import ConditionCreateRequest
from app.services import condition_reading
from app.services.condition_drafts import draft_ready_plan, unconfirmed_rounds_for
from app.services.condition_import import create_manual_condition, import_round
from app.services.condition_plan import (
    build_plan,
    confirm_round_plan,
    plan_confirmed,
    round_plan_blockers,
)
from app.services.condition_reading import ConfirmedItem, confirm_reading, read_round
from app.services.condition_rounds import SheetBytes, create_round_from_sheet
from app.tasks.conditions import parse_round
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.fixture_helpers import UWM_ROUND_2
from tests.conditions.reading_fixture import fake_complete
from tests.conditions.test_condition_plan import _actor, _conditions, _items, _planned_round_one
from tests.conditions.uwm_pdf_fixture import render_uwm_pdf


@pytest.fixture(autouse=True)
def _mocked_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(condition_reading, "complete", fake_complete())


async def _confirm(
    db: AsyncSession, round_: ConditionRound, loan_file: LoanFile, actor: Any
) -> None:
    """Confirm the round's plan, confirming first any reading that blocks it (0132 on round 1)."""
    by_code = await _conditions(db, loan_file)
    for code in await round_plan_blockers(db, round_=round_):
        condition = by_code[code]
        await confirm_reading(
            db,
            condition=condition,
            items=[
                ConfirmedItem(name=i.name, performers=(i.performer,), key=i.key)
                for i in await _items(db, condition)
            ],
            actor_user_id=actor,
        )
    await confirm_round_plan(db, round_=round_, actor_user_id=actor)


async def _round_two(db: AsyncSession, loan_file: LoanFile) -> ConditionRound:
    round_2 = await create_round_from_sheet(
        db,
        loan_file=loan_file,
        sheet=SheetBytes(
            content=render_uwm_pdf(UWM_ROUND_2), source_kind=ConditionSourceKind.PDF_UPLOAD
        ),
    )
    await db.flush()
    await parse_round(db, round_2.id)
    await db.refresh(round_2)
    await import_round(db, round_=round_2)
    await read_round(db, round_id=round_2.id)
    await build_plan(db, round_id=round_2.id)
    await draft_ready_plan(db, round_id=round_2.id)
    return round_2


async def _seen_again(
    db: AsyncSession, loan_file: LoanFile, round_2: ConditionRound
) -> list[Condition]:
    rows = (await _conditions(db, loan_file)).values()
    seen = [
        c for c in rows if c.last_seen_round_id == round_2.id and c.first_round_id != round_2.id
    ]
    assert seen, "round 2 lists conditions from round 1 again"
    return seen


async def test_confirm_stamps_every_condition_on_the_round(db_session: AsyncSession) -> None:
    loan_file, round_1 = await _planned_round_one(db_session)
    actor = await _actor(db_session, loan_file)
    conditions = (await _conditions(db_session, loan_file)).values()
    assert all(c.plan_confirmed_at is None for c in conditions)  # THE CONTROL: nothing before

    await _confirm(db_session, round_1, loan_file, actor)

    assert all(c.plan_confirmed_at == round_1.plan_confirmed_at for c in conditions)


async def test_a_plan_she_confirmed_stays_in_force_when_round_two_lists_it_again(
    db_session: AsyncSession,
) -> None:
    """Direction 1 above. Before LP-975 this asked round 2, unconfirmed, and refused the send."""
    loan_file, round_1 = await _planned_round_one(db_session)
    actor = await _actor(db_session, loan_file)
    await _confirm(db_session, round_1, loan_file, actor)
    drafts = list(
        await db_session.scalars(
            select(ConditionDraft).where(ConditionDraft.round_id == round_1.id)
        )
    )
    assert drafts
    for draft in drafts:  # THE CONTROL: before round 2, nothing is held
        assert (
            await unconfirmed_rounds_for(db_session, communication_id=draft.communication_id) == []
        )

    round_2 = await _round_two(db_session, loan_file)

    assert round_2.plan_confirmed_at is None
    for condition in await _seen_again(db_session, loan_file, round_2):
        assert await plan_confirmed(db_session, condition)
    for draft in drafts:
        assert (
            await unconfirmed_rounds_for(db_session, communication_id=draft.communication_id) == []
        )


async def test_a_plan_she_never_confirmed_is_not_in_force_until_she_confirms_the_round_it_is_on(
    db_session: AsyncSession,
) -> None:
    """Direction 2 above: round 1 left unconfirmed, round 2 arrives. The panel shows such a condition
    (it has no stamp); confirming round 2 is then her confirming it, and stamps it."""
    loan_file, _ = await _planned_round_one(db_session)
    actor = await _actor(db_session, loan_file)
    round_2 = await _round_two(db_session, loan_file)
    carried = await _seen_again(db_session, loan_file, round_2)
    for condition in carried:
        assert condition.plan_confirmed_at is None
        assert not await plan_confirmed(db_session, condition)

    await _confirm(db_session, round_2, loan_file, actor)

    for condition in carried:
        assert condition.plan_confirmed_at == round_2.plan_confirmed_at
        assert await plan_confirmed(db_session, condition)


async def test_an_earlier_stamp_is_kept_when_a_later_round_is_confirmed(
    db_session: AsyncSession,
) -> None:
    loan_file, round_1 = await _planned_round_one(db_session)
    actor = await _actor(db_session, loan_file)
    await _confirm(db_session, round_1, loan_file, actor)
    round_2 = await _round_two(db_session, loan_file)
    carried = await _seen_again(db_session, loan_file, round_2)

    await _confirm(db_session, round_2, loan_file, actor)

    assert round_2.plan_confirmed_at != round_1.plan_confirmed_at
    assert all(c.plan_confirmed_at == round_1.plan_confirmed_at for c in carried)


async def test_a_condition_added_after_confirm_is_in_force_without_a_stamp(
    db_session: AsyncSession,
) -> None:
    """THE FALLBACK. No confirm will ever stamp a condition added to a confirmed round (confirm returns
    early on one), so a stamp-only rule would hold its steps and its emails for ever."""
    loan_file, round_1 = await _planned_round_one(db_session)
    actor = await _actor(db_session, loan_file)
    await _confirm(db_session, round_1, loan_file, actor)

    added = await create_manual_condition(
        db_session,
        loan_file=loan_file,
        payload=ConditionCreateRequest(verbatim_text="Provide the final HOA certificate."),
        actor_user_id=actor,
    )

    assert added.plan_confirmed_at is None
    assert added.last_seen_round_id == round_1.id
    assert await plan_confirmed(db_session, added)


async def test_the_payload_carries_the_stamp(db_session: AsyncSession) -> None:
    from app.models.condition import OwnerHint, OwnerHintSource
    from app.schemas.condition import ConditionPublic

    loan_file, round_1 = await _planned_round_one(db_session)
    actor = await _actor(db_session, loan_file)
    condition = next(iter((await _conditions(db_session, loan_file)).values()))

    def public() -> ConditionPublic:
        return ConditionPublic.from_model(
            condition,
            effective_owner=OwnerHint.UNKNOWN,
            effective_owner_source=OwnerHintSource.NONE,
            is_open=True,
            days_open=0,
        )

    assert public().plan_confirmed_at is None
    await _confirm(db_session, round_1, loan_file, actor)
    assert public().plan_confirmed_at == round_1.plan_confirmed_at

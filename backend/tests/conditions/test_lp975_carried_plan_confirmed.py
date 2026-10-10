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
from app.models.condition_draft import ConditionDraft, DraftRecipient
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


# LP-976 — `test_a_condition_added_after_confirm_is_in_force_without_a_stamp` lived here. It pinned LP-975's
# round fallback, which LP-976 removes on purpose: a condition added after confirm now waits for her to
# confirm its plan. Its replacement, asserting the opposite, is in `test_lp976_added_after_confirm.py`.


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


async def test_the_upload_link_follows_the_send_not_the_round(db_session: AsyncSession) -> None:
    """LP-975 REVIEW — the send went condition-level and the borrower's upload link stayed round-level.

    The gate on minting the link is justified, at its call site, by the send guard: "nothing is sent
    before confirm (`unconfirmed_rounds_for`), so there is no reason for the link to exist before it
    either". This ticket changed that guard, so the two stopped agreeing: round 1 confirmed and its
    borrower email sent, round 2 imported, a new ask on a condition round 2 carried, and round 2's
    borrower draft holds only conditions she has confirmed. The send is allowed — and the email asked
    the borrower to upload with no link to upload to, because round 2 itself is not confirmed.
    """
    from app.models.communication import Communication
    from app.models.condition_vocabulary import Performer, PlanOption
    from app.services.condition_drafts import (
        _plan_confirmed_for,
        mark_sent,
        resync_file,
    )
    from app.services.condition_plan import add_item
    from tests.conditions.test_condition_drafts import _people

    loan_file, round_1 = await _planned_round_one(db_session)
    actor = await _actor(db_session, loan_file)
    await _people(db_session, loan_file)
    await db_session.flush()
    await _confirm(db_session, round_1, loan_file, actor)

    sent_borrower = None
    for draft in await db_session.scalars(
        select(ConditionDraft).where(ConditionDraft.round_id == round_1.id)
    ):
        if draft.recipient is DraftRecipient.BORROWER:
            sent_borrower = await db_session.get(Communication, draft.communication_id)
            await mark_sent(db_session, loan_file=loan_file, draft=draft, actor_user_id=actor)
    # THE POSITIVE CONTROL: the link mechanism works, and round 1's email carried one.
    assert sent_borrower is not None and sent_borrower.upload_link_url

    round_2 = await _round_two(db_session, loan_file)
    # Round 2's plan is READY only if something on it was planned (`build_plan`: `if outcome.planned`),
    # and its six conditions are all carried — so a condition she adds is what gives round 2 drafts.
    await create_manual_condition(
        db_session,
        loan_file=loan_file,
        payload=ConditionCreateRequest(verbatim_text="Provide the final HOA certificate."),
        actor_user_id=actor,
    )
    await read_round(db_session, round_id=round_2.id)
    await build_plan(db_session, round_id=round_2.id)
    carried = (await _seen_again(db_session, loan_file, round_2))[0]
    assert carried.plan_confirmed_at is not None
    await add_item(
        db_session,
        condition=carried,
        name="Provide the signed letter of explanation",
        performers=[Performer.BORROWER],
        option=PlanOption.ASK_BORROWER,
        actor_user_id=actor,
    )
    await draft_ready_plan(db_session, round_id=round_2.id)
    await resync_file(db_session, loan_file_id=loan_file.id, actor_user_id=actor)
    await db_session.flush()

    r2_draft = await db_session.scalar(
        select(ConditionDraft).where(
            ConditionDraft.round_id == round_2.id,
            ConditionDraft.recipient == DraftRecipient.BORROWER,
        )
    )
    assert r2_draft is not None, "the new ask on a carried condition makes round 2 a borrower draft"
    await db_session.refresh(round_2)
    assert round_2.plan_confirmed_at is None, "and round 2's own plan is not confirmed"
    communication_id = r2_draft.communication_id
    assert await unconfirmed_rounds_for(db_session, communication_id=communication_id) == [], (
        "nothing holds this email back: every condition in it carries her stamp"
    )
    assert await _plan_confirmed_for(db_session, r2_draft), "so the link must exist too"
    message = await db_session.get(Communication, communication_id)
    assert message is not None and message.upload_link_url, (
        "the email it asks uploads in has a link"
    )

    # THE NEGATIVE CONTROL, so the gate is not simply true now: take the stamp away and the send is
    # held again — and the link is refused with it, by the same question.
    carried.plan_confirmed_at = None
    await db_session.flush()
    assert await unconfirmed_rounds_for(db_session, communication_id=communication_id) == [2]
    assert not await _plan_confirmed_for(db_session, r2_draft)


async def test_a_task_she_cancelled_leaves_an_earlier_rounds_draft(
    db_session: AsyncSession,
) -> None:
    """LP-975 REVIEW — the sync maintained only the items of the conditions ITS round lists.

    A condition seen again moves to the newer round, and a re-listing that adds nothing new never has a
    ready plan (`build_plan` sets `plan_ready_at` only `if outcome.planned`), so it gets no drafts of its
    own. Its asks stay in the earlier round's unsent drafts, which that round's sync no longer iterates —
    so "Not needed" left the task in the email (against `update_item`'s "the task leaves the plan and its
    draft"), and this ticket's condition-level send then allows that email to go.
    """
    from app.models.condition_item import ConditionItem
    from app.models.condition_vocabulary import ConditionItemStatus
    from app.services.condition_drafts import _draft_items
    from app.services.condition_plan import update_item
    from tests.conditions.test_condition_drafts import _people

    loan_file, round_1 = await _planned_round_one(db_session)
    actor = await _actor(db_session, loan_file)
    await _people(db_session, loan_file)
    await db_session.flush()
    await _confirm(db_session, round_1, loan_file, actor)
    round_2 = await _round_two(db_session, loan_file)
    carried = {c.id: c for c in await _seen_again(db_session, loan_file, round_2)}
    await db_session.refresh(round_2)
    # The state that strands them: round 2 lists these again and plans nothing new of its own.
    assert round_2.plan_ready_at is None and round_2.plan_confirmed_at is None

    found: tuple[ConditionDraft, ConditionItem] | None = None
    for draft in await db_session.scalars(
        select(ConditionDraft).where(ConditionDraft.round_id == round_1.id)
    ):
        for item in await _draft_items(db_session, draft):
            if item.condition_id in carried and found is None:
                found = (draft, item)
    assert found is not None, "round 1's unsent drafts ask for a condition round 2 listed again"
    draft, item = found
    condition = carried[item.condition_id]
    assert condition.plan_confirmed_at is not None, "she confirmed this plan on round 1"
    others = [i.id for i in await _draft_items(db_session, draft) if i.id != item.id]
    assert others, (
        "the positive control for the control below: this email asks for more than one thing"
    )

    await update_item(
        db_session,
        condition=condition,
        item=item,
        option=None,
        name=None,
        performers=None,
        due_date=None,
        actor_user_id=actor,
        status=ConditionItemStatus.NOT_NEEDED,
        note="The lender waived it on the phone.",
    )
    await db_session.flush()

    left = [i.id for i in await _draft_items(db_session, draft)]
    assert item.status is ConditionItemStatus.NOT_NEEDED
    assert item.id not in left, "the task she cancelled is out of the email that asked for it"
    # THE CONTROL: the sync did not empty the draft — the tasks still asked are still in it.
    assert [i for i in others if i in left] == others


def _backfill_sql() -> str:
    """The migration's own backfill statement, captured from its `upgrade()` rather than copied, so this
    test cannot pass against a second spelling of the SQL."""
    import importlib.util
    from pathlib import Path

    path = next((Path(__file__).parents[2] / "alembic" / "versions").glob("*_40f6b9efb93c_*.py"))
    spec = importlib.util.spec_from_file_location("lp975_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    captured: list[str] = []

    class _Op:
        def add_column(self, *_: Any, **__: Any) -> None:  # the column exists: create_all made it
            return None

        def execute(self, sql: str) -> None:
            captured.append(sql)

    setattr(module, "op", _Op())  # noqa: B010 — the module's own `op` name, replaced for the capture
    module.upgrade()
    (sql,) = captured
    return sql


async def test_the_backfill_stamps_the_first_confirm_as_the_code_does(
    db_session: AsyncSession,
) -> None:
    """LP-975 REVIEW — the backfill took `max`, the LATEST confirm, while `confirm_round_plan` keeps the
    EARLIEST. Run the migration's statement on two confirmed rounds and compare it with what the code
    wrote: they must agree, for the carried conditions and for the new ones."""
    from sqlalchemy import text

    loan_file, round_1 = await _planned_round_one(db_session)
    actor = await _actor(db_session, loan_file)
    await _confirm(db_session, round_1, loan_file, actor)
    round_2 = await _round_two(db_session, loan_file)
    await _confirm(db_session, round_2, loan_file, actor)
    conditions = list((await _conditions(db_session, loan_file)).values())
    written = {c.id: c.plan_confirmed_at for c in conditions}
    carried = await _seen_again(db_session, loan_file, round_2)
    assert written[carried[0].id] == round_1.plan_confirmed_at  # THE PREMISE: two different dates
    assert round_1.plan_confirmed_at != round_2.plan_confirmed_at

    for condition in conditions:
        condition.plan_confirmed_at = None
    await db_session.flush()
    await db_session.execute(text(_backfill_sql()))
    for condition in conditions:
        await db_session.refresh(condition)

    assert {c.id: c.plan_confirmed_at for c in conditions} == written


async def test_the_backfill_is_never_later_than_the_code_in_either_confirm_order(
    db_session: AsyncSession,
) -> None:
    """LP-975 FOLLOW-UP REVIEW — `min` makes the two agree in one order and not in the other.

    The test above confirms round 1 BEFORE round 2 is imported, and there the backfill reproduces the
    code exactly. Reverse it — round 2 imported first, so the conditions have already moved, then round 1
    confirmed, then round 2 — and they differ: `confirm_round_plan` stamps a carried condition with ROUND
    2's time, because round 1's confirm no longer matched it (`last_seen_round_id == round_.id`), while
    the backfill sees an appearance event on round 1 and takes round 1's earlier time. Measured: all six
    carried conditions, round 1's confirm 144ms before round 2's.

    Which is right is a judgement — the code's stamp is "the first confirm that covered this condition",
    the backfill's is "the earliest confirm of a round it appeared on" — and only whether the stamp is
    SET is read today (`plan_confirmed`, and the frontend's `!row.plan_confirmed_at`), so neither answer
    changes what she sees. What must hold either way is asserted here: the backfill never leaves a
    condition the code stamped unstamped, and is never LATER than the code's stamp, so no condition can
    lose force or gain it late through the backfill. The strict case is deliberately not asserted, so
    making the two agree exactly stays an improvement rather than a failure.
    """
    from sqlalchemy import text

    loan_file, round_1 = await _planned_round_one(db_session)
    actor = await _actor(db_session, loan_file)
    # ROUND 2 FIRST: the conditions move to it before she confirms anything.
    round_2 = await _round_two(db_session, loan_file)
    await _confirm(db_session, round_1, loan_file, actor)
    await _confirm(db_session, round_2, loan_file, actor)
    conditions = list((await _conditions(db_session, loan_file)).values())
    written = {c.id: c.plan_confirmed_at for c in conditions}
    stamped = [c for c in conditions if written[c.id] is not None]
    assert stamped, "the control: the code stamped something, so the comparison has subjects"

    for condition in conditions:
        condition.plan_confirmed_at = None
    await db_session.flush()
    await db_session.execute(text(_backfill_sql()))
    for condition in conditions:
        await db_session.refresh(condition)

    for condition in stamped:
        code_stamp = written[condition.id]
        assert code_stamp is not None
        assert condition.plan_confirmed_at is not None, (
            "the backfill stamps every condition the code stamped: none loses force"
        )
        assert condition.plan_confirmed_at <= code_stamp, (
            "and never later than the code's own stamp"
        )


async def test_the_backfill_needs_its_seen_again_half_and_nothing_else_covers_it(
    db_session: AsyncSession,
) -> None:
    """LP-975 FOLLOW-UP REVIEW — the branch the ticket is FOR was the one no test held.

    The backfill's stamp is a UNION of three readings: a `condition_created` event on a confirmed round,
    a `condition_seen_again` event on one, and the condition's last-seen round if that is confirmed. In
    both of the tests above every condition was CREATED on a round that ends up confirmed, and the
    last-seen half catches whatever is left — so dropping `'condition_seen_again'` from the `kind` filter
    passes them both, which is exactly the "a different spelling of the SQL would pass" risk the capture
    was meant to close. The capture closes it for a second statement, not for a narrower one.

    THE SHAPE THAT ISOLATES IT needs three rounds, because the condition must have appeared on a
    CONFIRMED round that is neither where it was created nor where it was last seen: created on round 1
    (left unconfirmed), seen again on round 2 (confirmed — this is the stamp the code writes, since the
    condition sat on round 2 at that moment), seen again on round 3 (left unconfirmed, so the last-seen
    half contributes nothing). Only the seen-again branch can stamp it, and that branch is the one the
    ticket exists for: "a condition seen again after a confirmed round".
    """
    from sqlalchemy import text

    loan_file, round_1 = await _planned_round_one(db_session)
    actor = await _actor(db_session, loan_file)
    round_2 = await _round_two(db_session, loan_file)  # round 1 is deliberately left unconfirmed
    await _confirm(db_session, round_2, loan_file, actor)
    round_3 = await _round_two(
        db_session, loan_file
    )  # the same sheet again: every row is seen again

    carried = [
        c
        for c in await _seen_again(db_session, loan_file, round_3)
        if c.first_round_id == round_1.id
    ]
    assert carried, "round 3 lists conditions first seen on round 1 again"
    assert round_1.plan_confirmed_at is None and round_3.plan_confirmed_at is None, (
        "the premise: neither the created round nor the last-seen round is confirmed"
    )
    written = {c.id: c.plan_confirmed_at for c in carried}
    assert all(at == round_2.plan_confirmed_at for at in written.values()), (
        "the code stamped them at round 2's confirm, when they sat on round 2"
    )

    for condition in carried:
        condition.plan_confirmed_at = None
    await db_session.flush()
    await db_session.execute(text(_backfill_sql()))
    for condition in carried:
        await db_session.refresh(condition)

    assert {c.id: c.plan_confirmed_at for c in carried} == written, (
        "the seen-again branch is what puts the stamp back"
    )

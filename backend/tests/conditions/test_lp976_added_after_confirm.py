"""LP-976 — conditions added after a plan is confirmed get a plan she checks.

LP-975 left a fallback: a condition with no stamp was in force when its round's plan was confirmed. The
LP-975 review measured who that let through, all in force at once with a plan the reading proposed and no
screen showed: conditions merged in from a PDF (`condition_enrich._merge_conditions`), forwarded into a
round from the inbox (the same merge), or typed in by hand. Now a condition is in force by its own stamp
alone, and a second confirm on the round stamps them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from app.conditions.fingerprint import fingerprint
from app.models.activity_log import ActivityLog, ActivityType
from app.models.condition import BucketKind, Condition
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_round import ConditionRoundStatus
from app.models.condition_vocabulary import Performer, PlanOption
from app.models.loan_file import LoanFile
from app.schemas.condition import ConditionCreateRequest, ConditionRoundPublic
from app.services import condition_reading
from app.services.condition_drafts import unconfirmed_rounds_for
from app.services.condition_enrich import enrich_round_with_pdf
from app.services.condition_import import create_manual_condition
from app.services.condition_plan import add_item, confirm_round_plan, plan_confirmed
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.reading_fixture import fake_complete
from tests.conditions.test_condition_plan import _actor, _planned_round_one
from tests.conditions.test_lp975_carried_plan_confirmed import _confirm
from tests.conditions.test_round_enrich import _pasted_round, _round_2_pdf


@pytest.fixture(autouse=True)
def _mocked_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(condition_reading, "complete", fake_complete())


async def _round_events(db: AsyncSession, round_id: Any) -> int:
    return int(
        await db.scalar(
            select(func.count()).where(
                ConditionEvent.round_id == round_id,
                ConditionEvent.kind == ConditionEventKind.ROUND_PLAN_CONFIRMED,
            )
        )
        or 0
    )


async def test_a_pdf_merged_into_a_confirmed_round_waits_for_her(db_session: AsyncSession) -> None:
    """THE REPRODUCTION (the LP-975 review's finding 3). Under LP-975's fallback these four were in force
    the moment they were created; now they wait, and a second confirm stamps them."""
    round_, pasted_file = await _pasted_round(db_session)
    assert isinstance(pasted_file, LoanFile)
    actor = await _actor(db_session, pasted_file)
    # Import two rows and confirm the round's plan: the state a processor is in when the lender's PDF
    # arrives with four conditions the paste did not carry.
    confirmed_at = datetime(2026, 9, 1, 15, tzinfo=UTC)
    for index, row in enumerate(list(round_.draft_rows or [])[:2], start=1):
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
                plan_confirmed_at=confirmed_at,
            )
        )
    round_.status = ConditionRoundStatus.IMPORTED
    round_.round_number = 2
    round_.draft_rows = None
    round_.plan_confirmed_at = confirmed_at
    await db_session.flush()

    result = await enrich_round_with_pdf(db_session, round_=round_, content=_round_2_pdf())
    assert result.added == 4  # THE PREMISE

    added = list(
        await db_session.scalars(
            select(Condition).where(
                Condition.loan_file_id == round_.loan_file_id,
                Condition.plan_confirmed_at.is_(None),
            )
        )
    )
    assert len(added) == 4
    for condition in added:
        assert not await plan_confirmed(db_session, condition)

    await confirm_round_plan(db_session, round_=round_, actor_user_id=actor)

    for condition in added:
        assert condition.plan_confirmed_at is not None
        assert (
            condition.plan_confirmed_at > confirmed_at
        )  # the confirm that covers it, not the first
        assert await plan_confirmed(db_session, condition)
    # The round's own record is the first confirm's.
    assert round_.plan_confirmed_at == confirmed_at
    assert await _round_events(db_session, round_.id) == 0  # this fixture set the round by hand


async def test_a_condition_typed_in_after_confirm_waits_and_its_email_is_held(
    db_session: AsyncSession,
) -> None:
    """Replaces LP-975's `test_a_condition_added_after_confirm_is_in_force_without_a_stamp`, which pinned
    the fallback: she typed the words, but its plan comes from the reading, which she has not seen."""
    loan_file, round_1 = await _planned_round_one(db_session)
    actor = await _actor(db_session, loan_file)
    await _confirm(db_session, round_1, loan_file, actor)
    events_before = await _round_events(db_session, round_1.id)
    assert events_before == 1

    added = await create_manual_condition(
        db_session,
        loan_file=loan_file,
        payload=ConditionCreateRequest(verbatim_text="Provide the final HOA certificate."),
        actor_user_id=actor,
    )
    ask = await add_item(
        db_session,
        condition=added,
        name="The final HOA certificate",
        performers=[Performer.HOA],
        option=PlanOption.ASK_THIRD_PARTY,
        actor_user_id=actor,
    )
    assert ask.draft_id is not None  # THE PREMISE: it is in an email
    from app.models.condition_draft import ConditionDraft

    draft = await db_session.get(ConditionDraft, ask.draft_id)
    assert draft is not None

    assert added.plan_confirmed_at is None
    assert not await plan_confirmed(db_session, added)
    assert await unconfirmed_rounds_for(db_session, communication_id=draft.communication_id) == [1]

    await confirm_round_plan(db_session, round_=round_1, actor_user_id=actor)

    assert added.plan_confirmed_at is not None
    assert added.plan_confirmed_at > round_1.plan_confirmed_at
    assert await unconfirmed_rounds_for(db_session, communication_id=draft.communication_id) == []
    # THE ROUND'S RECORD IS NOT WRITTEN TWICE: one ROUND_PLAN_CONFIRMED, from the first confirm.
    assert await _round_events(db_session, round_1.id) == 1
    rows = list(
        await db_session.scalars(
            select(ActivityLog).where(
                ActivityLog.loan_file_id == loan_file.id,
                ActivityLog.activity_type == ActivityType.CONDITION_PLAN_CONFIRMED,
            )
        )
    )
    assert [row.summary for row in rows if "added" in row.summary] == [
        "Plan confirmed for 1 condition added to round 1"
    ]


async def test_a_borrower_ask_added_after_confirm_gets_its_link_at_the_second_confirm(
    db_session: AsyncSession,
) -> None:
    """The second confirm syncs the drafts as the first does. The borrower's upload link is minted only
    once the send guard lets the email go (`_plan_confirmed_for`, LP-975 review), so without the sync her
    late ask stays in a draft with no link, and `render_borrower` drops the paragraph."""
    from app.models.communication import Communication
    from app.models.condition_draft import ConditionDraft

    loan_file, round_1 = await _planned_round_one(db_session)
    actor = await _actor(db_session, loan_file)
    await _confirm(db_session, round_1, loan_file, actor)
    added = await create_manual_condition(
        db_session,
        loan_file=loan_file,
        payload=ConditionCreateRequest(verbatim_text="Provide a signed letter of explanation."),
        actor_user_id=actor,
    )
    ask = await add_item(
        db_session,
        condition=added,
        name="A signed letter of explanation",
        performers=[Performer.BORROWER],
        option=PlanOption.ASK_BORROWER,
        actor_user_id=actor,
    )
    draft = await db_session.get(ConditionDraft, ask.draft_id)
    assert draft is not None
    message = await db_session.get(Communication, draft.communication_id)
    assert message is not None
    # Round 1's borrower email was already confirmed, so it may carry a link for round 1's asks; what
    # matters is that sending now waits for the added condition.
    assert await unconfirmed_rounds_for(db_session, communication_id=draft.communication_id) == [1]
    message.upload_link_url = None  # as a draft first rendered while the guard held it
    await db_session.flush()

    await confirm_round_plan(db_session, round_=round_1, actor_user_id=actor)

    await db_session.refresh(message)
    assert message.upload_link_url, "the second confirm re-renders the borrower's email with a link"


async def test_a_second_confirm_with_nothing_added_changes_nothing(
    db_session: AsyncSession,
) -> None:
    """THE CONTROL: on a confirmed round with every condition stamped, confirm still does nothing."""
    loan_file, round_1 = await _planned_round_one(db_session)
    actor = await _actor(db_session, loan_file)
    await _confirm(db_session, round_1, loan_file, actor)
    activities = await db_session.scalar(
        select(func.count()).where(ActivityLog.loan_file_id == loan_file.id)
    )

    await confirm_round_plan(db_session, round_=round_1, actor_user_id=actor)

    assert (
        await db_session.scalar(
            select(func.count()).where(ActivityLog.loan_file_id == loan_file.id)
        )
        == activities
    )


async def test_the_round_payload_says_whether_its_plan_is_confirmed(
    db_session: AsyncSession,
) -> None:
    loan_file, round_1 = await _planned_round_one(db_session)
    assert ConditionRoundPublic.from_model(round_1).plan_confirmed_at is None
    await _confirm(db_session, round_1, loan_file, await _actor(db_session, loan_file))
    assert ConditionRoundPublic.from_model(round_1).plan_confirmed_at == round_1.plan_confirmed_at


def _backfill_sql() -> str:
    """The LP-976 migration's statement, captured from its `upgrade()` (as LP-975's backfill test does)."""
    import importlib.util
    from pathlib import Path

    path = next((Path(__file__).parents[2] / "alembic" / "versions").glob("*_253c4c8df883_*.py"))
    spec = importlib.util.spec_from_file_location("lp976_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    captured: list[str] = []

    class _Op:
        def execute(self, sql: str) -> None:
            captured.append(sql)

    setattr(module, "op", _Op())  # noqa: B010 — the module's own `op` name, replaced for the capture
    module.upgrade()
    (sql,) = captured
    return sql


async def test_the_backfill_stamps_what_the_fallback_held_in_force(
    db_session: AsyncSession,
) -> None:
    """Without it, dropping the fallback would take those plans out of force on deploy. Stamped with the
    time each came into force under the old rule: the later of the round's confirm and its creation."""
    loan_file, round_1 = await _planned_round_one(db_session)
    actor = await _actor(db_session, loan_file)
    await _confirm(db_session, round_1, loan_file, actor)
    added = await create_manual_condition(
        db_session,
        loan_file=loan_file,
        payload=ConditionCreateRequest(verbatim_text="Provide the final HOA certificate."),
        actor_user_id=actor,
    )
    stamped = list(
        await db_session.scalars(
            select(Condition).where(
                Condition.loan_file_id == loan_file.id, Condition.plan_confirmed_at.is_not(None)
            )
        )
    )
    # A stamp unlike anything the backfill would write, so an overwrite cannot pass by coincidence.
    stamped[0].plan_confirmed_at = datetime(2026, 1, 2, 3, tzinfo=UTC)
    await db_session.flush()
    before = {c.id: c.plan_confirmed_at for c in stamped}
    assert added.plan_confirmed_at is None and before  # THE PREMISE

    await db_session.execute(text(_backfill_sql()))
    await db_session.refresh(added)
    for condition in stamped:
        await db_session.refresh(condition)

    assert round_1.plan_confirmed_at is not None
    assert added.plan_confirmed_at == max(round_1.plan_confirmed_at, added.created_at)
    # A stamp a confirm wrote is left as it was.
    assert {c.id: c.plan_confirmed_at for c in stamped} == before


async def test_the_round_list_carries_every_round_a_condition_can_be_on(
    db_session: AsyncSession,
) -> None:
    """THE COUPLING THE SCREEN DEPENDS ON (LP-976 review). The panel finds a late condition by joining
    its `last_seen_round_id` to the confirmed rounds in the list the screen receives. A round missing
    from that list drops its late conditions off the panel, with nothing failing and their emails held.

    Unreachable today, for reasons that all live on the server: `list_rounds` filters no status (its
    docstring says DISCARDED is included on purpose), no `ConditionRound` is ever soft-deleted,
    `discard_round` refuses an IMPORTED round, and a condition's last-seen round is always IMPORTED (the
    manual door's own round is made IMPORTED by `_assign_round_number`). This is the test a status or
    deleted filter on the rounds query will break first."""
    from app.models.condition_round import ConditionRoundCompleteness
    from app.services.condition_rounds import create_round_from_paste, discard_round
    from app.services.conditions import list_rounds
    from tests.conditions.fixture_helpers import portal_excerpt

    loan_file, round_1 = await _planned_round_one(db_session)
    actor = await _actor(db_session, loan_file)
    await _confirm(db_session, round_1, loan_file, actor)
    await create_manual_condition(
        db_session,
        loan_file=loan_file,
        payload=ConditionCreateRequest(verbatim_text="Provide the final HOA certificate."),
        actor_user_id=actor,
    )
    thrown = await create_round_from_paste(
        db_session,
        loan_file=loan_file,
        text=portal_excerpt(),
        completeness=ConditionRoundCompleteness.PARTIAL,
    )
    await discard_round(db_session, round_=thrown, actor_user_id=actor)

    listed = {r.id for r in await list_rounds(db_session, loan_file_id=loan_file.id)}
    last_seen = set(
        await db_session.scalars(
            select(Condition.last_seen_round_id).where(Condition.loan_file_id == loan_file.id)
        )
    )
    assert last_seen <= listed, "every round a condition is on reaches the screen"
    assert thrown.id in listed, "a discarded round is listed too: the screen filters, not the query"

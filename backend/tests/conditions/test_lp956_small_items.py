"""LP-956 — small items from the 2026-09-30 staging trial (10a and 12).

10a: "Waiting on Processor" is refused; the processor stays a valid owner. 12: the readonly views (pinned in
`tests/test_readonly_query.py`).
"""

from __future__ import annotations

import pytest
from app.models.condition import ConditionPrepStatus, OwnerHint
from app.schemas.condition import BulkAction, BulkRequest, PrepStatusRequest
from app.services import condition_reading
from app.services.condition_status import (
    ConditionRefused,
    RefusalCode,
    apply_bulk,
    move_prep_status,
)
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.reading_fixture import fake_complete
from tests.conditions.test_condition_plan import _actor
from tests.conditions.test_lp949_lender_on_the_file import _by_code, _file_without_lender


@pytest.fixture(autouse=True)
def _model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(condition_reading, "complete", fake_complete())


async def test_waiting_on_the_processor_is_refused(db_session: AsyncSession) -> None:
    loan_file, _ = await _file_without_lender(db_session)
    condition = (await _by_code(db_session, loan_file))["0006"]
    actor = await _actor(db_session, loan_file)
    with pytest.raises(ConditionRefused) as refused:
        await move_prep_status(
            db_session,
            condition=condition,
            payload=PrepStatusRequest(
                to=ConditionPrepStatus.WAITING,
                waiting_on=OwnerHint.PROCESSOR,
                expected_updated_at=condition.updated_at,
            ),
            actor_user_id=actor,
        )
    assert refused.value.code is RefusalCode.WAITING_ON_SELF
    assert condition.prep_status is ConditionPrepStatus.TO_DO

    # The positive control: waiting on someone else moves it.
    await move_prep_status(
        db_session,
        condition=condition,
        payload=PrepStatusRequest(
            to=ConditionPrepStatus.WAITING,
            waiting_on=OwnerHint.BROKER,
            expected_updated_at=condition.updated_at,
        ),
        actor_user_id=actor,
    )
    assert getattr(condition, "prep_status") is ConditionPrepStatus.WAITING  # noqa: B009 (narrowing)
    assert condition.waiting_on is OwnerHint.BROKER


async def test_a_bulk_move_refuses_the_row_whose_owner_is_the_processor(
    db_session: AsyncSession,
) -> None:
    """The bulk door sends each row's own owner when none is chosen; a processor-owned row is refused
    with the sentence, and a row with another owner still moves."""
    loan_file, _ = await _file_without_lender(db_session)
    conditions = await _by_code(db_session, loan_file)
    actor = await _actor(db_session, loan_file)
    mine, theirs = conditions["0006"], conditions["1947"]
    mine.owner_override = OwnerHint.PROCESSOR
    theirs.owner_override = OwnerHint.TITLE
    await db_session.flush()
    result = await apply_bulk(
        db_session,
        loan_file_id=loan_file.id,
        payload=BulkRequest(
            condition_ids=[mine.id, theirs.id],
            action=BulkAction.PREP_STATUS,
            to=ConditionPrepStatus.WAITING,
        ),
        actor_user_id=actor,
    )
    assert [(cid, code) for cid, code, _ in result.refused] == [
        (mine.id, RefusalCode.WAITING_ON_SELF)
    ]
    assert result.applied == [theirs.id]
    assert mine.prep_status is ConditionPrepStatus.TO_DO
    assert theirs.prep_status is ConditionPrepStatus.WAITING

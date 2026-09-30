"""LP-947: one source for "waiting on".

The server sends, with each condition, who it WILL be Waiting on once its next email is marked sent
(S3-01's "Becomes Waiting on Borrower when the borrower email is marked sent."). The client renders
that value; it no longer keeps its own map of performers to owners. The test that matters is that the
prediction IS the move: mark every email sent, and each condition waits on whom it said it would.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from app.models.condition import OwnerHint
from app.models.condition_vocabulary import ConditionItemStatus, Performer, PlanOption
from app.services.condition_drafts import mark_sent, waiting_on_when_sent
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.test_condition_drafts import (  # noqa: F401
    _confirmed,
    _drafts,
    _drop_db_override,
)


def _ask(performers: list[str], status: str = "open") -> Any:
    return SimpleNamespace(
        option=PlanOption.ASK_THIRD_PARTY,
        performer=Performer(performers[0]),
        performers=performers,
        status=ConditionItemStatus(status),
    )


@pytest.mark.usefixtures("_drop_db_override")
async def test_the_prediction_is_the_move(db_session: AsyncSession) -> None:
    from tests.conditions.test_condition_reading import _client_for

    db = db_session
    loan_file, _, _, actor = await _confirmed(db)
    client, headers = await _client_for(db, loan_file)
    url = f"/api/v1/loan-files/{loan_file.id}/conditions"
    async with client:
        before = {
            row["lender_code"]: row for row in (await client.get(url, headers=headers)).json()
        }
        predicted = {
            code: row["waiting_on_when_sent"]
            for code, row in before.items()
            if row["prep_status"] == "to_do" and row["waiting_on_when_sent"] is not None
        }
        # The positive control: the round predicts three different owners, including the LO relay.
        assert predicted["6637"] == "borrower"
        assert predicted["0132"] == "broker"
        assert predicted["6178"] == "lender"  # the question to the underwriter

        for draft, _ in (await _drafts(db, loan_file)).values():
            await mark_sent(db, loan_file=loan_file, draft=draft, actor_user_id=actor)

        after = {row["lender_code"]: row for row in (await client.get(url, headers=headers)).json()}
    assert {code: after[code]["waiting_on"] for code in predicted} == predicted
    assert all(after[code]["prep_status"] == "waiting" for code in predicted)


def test_the_first_open_ask_decides() -> None:
    assert waiting_on_when_sent(None, [_ask(["title"]), _ask(["borrower"])]) is OwnerHint.TITLE
    # A done or dropped ask is not the next email; the next open one is.
    done = [_ask(["title"], "done"), _ask(["borrower"])]
    assert waiting_on_when_sent(None, done) is OwnerHint.BORROWER
    assert waiting_on_when_sent(None, [_ask(["title"], "not_needed")]) is None


def test_the_appraisers_ask_waits_on_the_lender() -> None:
    """LP-942: the appraiser's ask is in the lender's email; the client's map once drifted on this."""
    assert waiting_on_when_sent(None, [_ask(["appraiser"])]) is OwnerHint.LENDER


def test_a_question_waits_on_the_lender_and_her_task_on_no_one() -> None:
    assert waiting_on_when_sent(PlanOption.PUSH_BACK, []) is OwnerHint.LENDER
    task = SimpleNamespace(
        option=PlanOption.I_WILL_DO_IT,
        performer=Performer.PROCESSOR,
        performers=["processor"],
        status=ConditionItemStatus.OPEN,
    )
    assert waiting_on_when_sent(None, [task]) is None

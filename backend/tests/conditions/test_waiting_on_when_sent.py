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


def _ask(performers: list[str], status: str = "open", sent: bool = False) -> Any:
    return SimpleNamespace(
        option=PlanOption.ASK_THIRD_PARTY,
        performer=Performer(performers[0]),
        performers=performers,
        status=ConditionItemStatus(status),
        draft=SimpleNamespace(status="sent") if sent else None,
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
        draft=None,
    )
    assert waiting_on_when_sent(None, [task]) is None


@pytest.mark.usefixtures("_drop_db_override")
async def test_marking_only_the_named_email_sent_waits_on_whom_it_said(
    db_session: AsyncSession,
) -> None:
    """LP-947 review: the sentence names ONE email ("…when the LO email is marked sent"). With two
    unsent emails, mark only THAT one sent: the condition waits on the predicted owner. Marking every
    draft sent (the test above) cannot tell "the first open ask" from "the first ask whose email went"."""
    from tests.conditions.test_condition_reading import _client_for

    db = db_session
    loan_file, _, _, actor = await _confirmed(db)
    client, headers = await _client_for(db, loan_file)
    url = f"/api/v1/loan-files/{loan_file.id}/conditions"
    async with client:
        before = {r["lender_code"]: r for r in (await client.get(url, headers=headers)).json()}
        # The premise: 0132 has asks in TWO emails, neither sent (the LO's disclosure first).
        drafts = await _drafts(db, loan_file)
        assert {d.id for d, m in drafts.values() if m.status.value == "draft"} >= {
            drafts["lo"][0].id,
            drafts["title_attorney"][0].id,
        }
        assert before["0132"]["waiting_on_when_sent"] == "broker"
        await mark_sent(db, loan_file=loan_file, draft=drafts["lo"][0], actor_user_id=actor)
        after = {r["lender_code"]: r for r in (await client.get(url, headers=headers)).json()}
    assert after["0132"]["waiting_on"] == "broker"


def test_the_prediction_is_the_moves_rule_one_send_ahead() -> None:
    """An earlier ask whose email already went decides the move, so it decides the prediction too:
    one rule (`first_asked_owner`), not "the first open ask" beside "the first ask whose email went"."""
    items = [_ask(["title"], "done", sent=True), _ask(["borrower"])]
    assert waiting_on_when_sent(None, items) is OwnerHint.TITLE


def test_a_dropped_ask_decides_nothing_even_if_its_email_went() -> None:
    """The move reads live items only (`_condition_items` leaves out NOT_NEEDED), so the rule does."""
    items = [_ask(["title"], "not_needed", sent=True), _ask(["borrower"])]
    assert waiting_on_when_sent(None, items) is OwnerHint.BORROWER

"""An item is not done while its own finding is open (LP-923 review).

WHY THIS EXISTS. `_open_finding` guards two different decisions in `condition_evidence`: whether the
CONDITION may move to Ready to send, and whether the ITEM may be marked done. The first is pinned by
`test_accepting_a_statement_does_not_answer_its_deposit` — removing it fails that test. The second was
pinned by nothing: deleting it from the per-item rule left the whole `tests/conditions/` suite green,
so an edit could have marked items done over an open finding and no test would have said so.

WHAT THAT WOULD LOOK LIKE. S3-08's statement passes every check — right account, right period, right
borrower, inside the lender's dates, all 12 pages, enough for closing — and still carries the
$4,000.00 deposit that needs sourcing. Without this guard the item reads "done" on the sheet and drops
out of her open work, while the condition itself stays held by the other guard. The screen would say
the asked-for thing had arrived and been dealt with, which is the one thing it must not say while the
borrower still owes an explanation.
"""

from __future__ import annotations

import pytest
from app.models.condition_evidence import ConditionEvidence
from app.models.condition_item import ConditionItem
from app.models.condition_vocabulary import ConditionItemStatus
from app.services import condition_reading
from app.services.condition_evidence import answer_finding, check_document
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.reading_fixture import fake_complete
from tests.conditions.statement_fixture import add_statement, july_and_august
from tests.conditions.test_condition_evidence import TODAY, _asked, _evidence, _results

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _mocked_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """The same stub the sibling module uses. Without it `_asked` reaches the real API: the reading
    runs inside it, and the mock lives in that module rather than in `conftest`."""
    monkeypatch.setattr(condition_reading, "complete", fake_complete())


async def _statements_evidence(
    db: AsyncSession, condition: object
) -> tuple[ConditionEvidence, ConditionItem]:
    """The evidence row for 7086's `statements` item, with its item."""
    rows = await _evidence(db, condition)  # type: ignore[arg-type]
    for row in rows:
        item = await db.get(ConditionItem, row.item_id)
        if item is not None and item.key == "statements":
            return row, item
    raise AssertionError("no evidence for the statements item")


async def test_every_check_passed_and_the_item_is_still_not_done(db_session: AsyncSession) -> None:
    """S3-08 exactly: nothing failed, and the deposit is still unanswered."""
    _loan_file, conditions, _actor = await _asked(db_session)
    both = await add_statement(db_session, _loan_file, july_and_august())
    await check_document(db_session, document_id=both.id, today=TODAY)

    row, item = await _statements_evidence(db_session, conditions["7086"])

    # The premise, asserted rather than assumed: this is the all-passed case, not a failed check.
    assert {result for result, _reason in _results(row).values()} - {"failed"} == {"passed"}
    assert [result for result, _ in _results(row).values()].count("failed") <= 1, _results(row)
    assert row.findings, "the $4,000.00 deposit should be an open finding"
    assert row.findings[0].get("status") != "explained"

    assert item.status is not ConditionItemStatus.DONE


async def test_answering_the_finding_lets_the_item_be_done(db_session: AsyncSession) -> None:
    """The positive control. Without it, a guard that never marked anything done would pass above."""
    _loan_file, conditions, actor = await _asked(db_session)
    both = await add_statement(db_session, _loan_file, july_and_august())
    await check_document(db_session, document_id=both.id, today=TODAY)
    row, _item = await _statements_evidence(db_session, conditions["7086"])

    await answer_finding(
        db_session,
        condition=conditions["7086"],
        evidence_id=row.id,
        index=0,
        answer="explained",
        reason="payroll from her employer, shown on the same statement",
        actor_user_id=actor,
    )

    _row, item = await _statements_evidence(db_session, conditions["7086"])
    assert item.status is ConditionItemStatus.DONE

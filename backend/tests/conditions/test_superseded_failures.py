"""LP-937: once a passing document has done an item, the earlier failed checks for that item stop counting.

S3-12's moment first: the 5-page August statement fails 6132, 7086 and 6637's clearance ("Failed a check
3", D1). Then S3-08's complete July-and-August statement arrives. It does 6132's item and 6637's
clearance, so those two failures are superseded ("Replaced by …") and stop counting. 7086's failure
still counts while the deposit is open (its item is not done), and stops once the deposit is explained.

The rule has two statements, and this file asserts they agree at every step: `has_failed_check()` (SQL,
behind the count and the filter) and `superseded_by` (Python, behind the sheet and the list's token).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.models.condition import Condition
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_item import ConditionItem
from app.models.loan_file import LoanFile
from app.services import condition_evidence
from app.services.condition_evidence import check_document, evidence_public_for_file
from app.services.condition_plan import remove_item
from app.services.conditions import ConditionFilters, condition_summary, list_conditions_filtered
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.statement_fixture import add_statement, august, july, july_and_august
from tests.conditions.test_condition_evidence import TODAY, _asked, _evidence

BOTH = "Capital One statements ··9912 · July and August 2026 · 12 pages"


async def _drop_other_accounts(db: AsyncSession, condition: Condition, actor: Any) -> None:
    other = next(
        i
        for i in (
            await db.execute(
                select(ConditionItem).where(ConditionItem.condition_id == condition.id)
            )
        ).scalars()
        if i.key == "other_accounts"
    )
    await remove_item(db, condition=condition, item=other, actor_user_id=actor)


async def _failing(db: AsyncSession, loan_file: LoanFile) -> tuple[set[str], set[str], int]:
    """(the filter's codes, the codes whose sheet shows a live failure, the summary's count)."""
    rows, _ = await list_conditions_filtered(
        db, loan_file_id=loan_file.id, filters=ConditionFilters(failed_check=True)
    )
    public = await evidence_public_for_file(db, loan_file_id=loan_file.id)
    codes: dict[UUID, str] = {
        c.id: c.lender_code
        for c in (
            await db.execute(select(Condition).where(Condition.loan_file_id == loan_file.id))
        ).scalars()
    }
    shown = {codes[cid] for cid, cards in public.items() if any(card.failed for card in cards)}
    summary = await condition_summary(db, loan_file_id=loan_file.id)
    return {c.lender_code for c in rows}, shown, summary.failed_check


async def test_a_failure_stops_counting_once_a_passing_document_does_its_item(
    db_session: AsyncSession,
) -> None:
    db = db_session
    loan_file, conditions, actor = await _asked(db)
    await _drop_other_accounts(db, conditions["7086"], actor)
    await check_document(
        db, document_id=(await add_statement(db, loan_file, july(), via_link=False)).id, today=TODAY
    )
    short = await add_statement(db, loan_file, august(pages_present=5))
    await check_document(db, document_id=short.id, today=TODAY)
    # S3-12's moment (D1): three failures, and the count, the filter and the sheet agree.
    assert await _failing(db, loan_file) == ({"6132", "7086", "6637"},) * 2 + (3,)

    both = await add_statement(db, loan_file, july_and_august())
    await check_document(db, document_id=both.id, today=TODAY)
    # 6132's item and 6637's clearance are done by the complete statement; 7086 waits on its deposit.
    assert await _failing(db, loan_file) == ({"7086"}, {"7086"}, 1)

    public = await evidence_public_for_file(db, loan_file_id=loan_file.id)
    (six,) = [c for c in public[conditions["6132"].id] if c.document_id == short.id]
    assert (six.failed, six.superseded, six.reask, six.replaced) == (
        False,
        f"Replaced by {BOTH}",
        None,
        True,
    )
    # The checks are shown as they were: the history of what arrived is not rewritten.
    assert [c.result for c in six.checks if c.check == "all_pages"] == ["failed"]

    (row,) = [e for e in await _evidence(db, conditions["7086"]) if e.document_id == both.id]
    await condition_evidence.answer_finding(
        db,
        condition=conditions["7086"],
        evidence_id=row.id,
        index=0,
        answer="explained",
        reason="Gift from a relative",
        actor_user_id=actor,
    )
    assert await _failing(db, loan_file) == (set(), set(), 0)

    # The history keeps what happened when the 5-page statement arrived.
    checked = (
        await db.execute(
            select(ConditionEvent.detail).where(
                ConditionEvent.condition_id == conditions["6132"].id,
                ConditionEvent.kind == ConditionEventKind.CONDITION_EVIDENCE_CHECKED,
            )
        )
    ).scalars()
    assert {"document_id": str(short.id), "failed": 1} in [
        {"document_id": d["document_id"], "failed": d["failed"]} for d in checked
    ]


async def test_a_failure_still_counts_while_its_item_is_not_done(db_session: AsyncSession) -> None:
    """The positive control for the rule: no passing document yet, so nothing is superseded."""
    loan_file, _, _ = await _asked(db_session)
    short = await add_statement(db_session, loan_file, august(pages_present=5))
    await check_document(db_session, document_id=short.id, today=TODAY)
    codes, shown, count = await _failing(db_session, loan_file)
    assert codes == shown and count == len(codes) > 0
    public = await evidence_public_for_file(db_session, loan_file_id=loan_file.id)
    assert all(card.superseded is None for cards in public.values() for card in cards)


async def test_a_statement_short_on_its_own_is_completed_not_replaced(
    db_session: AsyncSession,
) -> None:
    """July alone fails only "Enough for closing". August completes it; July is still evidence (it goes
    in the package), so the sheet says "together with", never "replaced by"."""
    db = db_session
    loan_file, conditions, actor = await _asked(db)
    await _drop_other_accounts(db, conditions["7086"], actor)
    first = await add_statement(db, loan_file, july(), name="july.pdf")
    await check_document(db, document_id=first.id, today=TODAY)
    second = await add_statement(db, loan_file, august(), name="august.pdf")
    await check_document(db, document_id=second.id, today=TODAY)
    (row,) = [e for e in await _evidence(db, conditions["7086"]) if e.document_id == second.id]
    await condition_evidence.answer_finding(
        db,
        condition=conditions["7086"],
        evidence_id=row.id,
        index=0,
        answer="explained",
        reason="Gift from a relative",
        actor_user_id=actor,
    )
    public = await evidence_public_for_file(db, loan_file_id=loan_file.id)
    (card,) = [c for c in public[conditions["7086"].id] if c.document_id == first.id]
    assert [c.check for c in card.checks if c.result == "failed"] == ["covers_required_funds"]
    # Not "together with": one account, so August met the total by itself (`_verified` takes its latest
    # balance). July is still evidence because the lender asked for two months (LP-937 review).
    assert card.superseded == (
        "Still evidence — enough for closing was met by "
        "Capital One statement ··9912 · August 2026 · 6 pages"
    )
    assert card.replaced is False
    assert card.failed is False
    assert "7086" not in (await _failing(db, loan_file))[0]


async def test_the_sheet_names_the_document_that_passed_not_a_later_failure(
    db_session: AsyncSession,
) -> None:
    """5-page August (fails pages), then another account's August (fails account), then the complete
    statement. Both failures are replaced by the complete one: the second failure is later than the
    first, but it passed nothing, so it replaced nothing."""
    db = db_session
    loan_file, conditions, _ = await _asked(db)
    short = await add_statement(db, loan_file, august(pages_present=5), name="short.pdf")
    await check_document(db, document_id=short.id, today=TODAY)
    wrong = await add_statement(db, loan_file, august(last4="4471"), name="other.pdf")
    await check_document(db, document_id=wrong.id, today=TODAY)
    both = await add_statement(db, loan_file, july_and_august(), name="both.pdf")
    await check_document(db, document_id=both.id, today=TODAY)
    public = await evidence_public_for_file(db, loan_file_id=loan_file.id)
    cards = {c.document_id: c for c in public[conditions["6132"].id]}
    assert cards[short.id].superseded == f"Replaced by {BOTH}"
    assert cards[wrong.id].superseded == f"Replaced by {BOTH}"


async def test_a_done_item_takes_no_new_evidence(db_session: AsyncSession) -> None:
    """THE INVARIANT THE SQL HALF RESTS ON. `has_failed_check()` also asks that the later row passes and
    is for the same item. Both are implied here: a done item is never checked against a new upload,
    so every failed row on a done item came before the document that did it. If that ever changes,
    this fails, and the two clauses stop being redundant."""
    db = db_session
    loan_file, conditions, _ = await _asked(db)
    both = await add_statement(db, loan_file, july_and_august())
    await check_document(db, document_id=both.id, today=TODAY)
    item = (
        await db.execute(
            select(ConditionItem).where(ConditionItem.condition_id == conditions["6132"].id)
        )
    ).scalar_one()
    assert item.status.value == "done"  # the positive control
    late = await add_statement(db, loan_file, august(pages_present=5), name="late.pdf")
    await check_document(db, document_id=late.id, today=TODAY)
    assert [e.document_id for e in await _evidence(db, conditions["6132"])] == [both.id]


async def test_the_deposit_holding_the_condition_stays_on_the_sheet(
    db_session: AsyncSession,
) -> None:
    """THE LP-937 REVIEW'S FINDING, from its reproduction. July is short on its own and carries a $4,000.00
    deposit; August meets the total by itself and is clean. July is superseded (its only failure is
    the funds total) but is still evidence, so its open deposit holds 7086. That deposit must stay on
    the sheet and answerable: `replaced` is false, and only a replaced row's findings are hidden."""
    from datetime import date
    from decimal import Decimal

    from app.ai.extraction.bank_statement import Transaction
    from app.models.condition import ConditionPrepStatus
    from tests.conditions.statement_fixture import AUGUST, JULY

    db = db_session
    loan_file, conditions, actor = await _asked(db)
    await _drop_other_accounts(db, conditions["7086"], actor)
    deposit = Transaction(
        date=date(2026, 7, 21),
        description="Mobile Deposit",
        amount=Decimal("4000.00"),
        transaction_type="deposit",
    )
    first = await add_statement(db, loan_file, july(transactions=[*JULY, deposit]), name="july.pdf")
    await check_document(db, document_id=first.id, today=TODAY)
    clean = [t for t in AUGUST if t.description != "Mobile Deposit"]
    second = await add_statement(db, loan_file, august(transactions=clean), name="august.pdf")
    await check_document(db, document_id=second.id, today=TODAY)
    # The premise: the condition is held, by July's deposit.
    assert conditions["7086"].prep_status is ConditionPrepStatus.WAITING

    public = await evidence_public_for_file(db, loan_file_id=loan_file.id)
    (card,) = [c for c in public[conditions["7086"].id] if c.document_id == first.id]
    assert card.superseded is not None and card.replaced is False
    # What the sheet renders (evidence-section hides findings on replaced rows only).
    shown = [
        f
        for c in public[conditions["7086"].id]
        if not c.replaced
        for f in c.findings
        if f.status == "open" and f.needed
    ]
    assert [(f.date, f.amount) for f in shown] == [(date(2026, 7, 21), Decimal("4000.00"))]

    # And answering it there releases the condition.
    (row,) = [e for e in await _evidence(db, conditions["7086"]) if e.document_id == first.id]
    await condition_evidence.answer_finding(
        db,
        condition=conditions["7086"],
        evidence_id=row.id,
        index=0,
        answer="explained",
        reason="Gift from a relative",
        actor_user_id=actor,
    )
    assert conditions["7086"].prep_status is ConditionPrepStatus.READY

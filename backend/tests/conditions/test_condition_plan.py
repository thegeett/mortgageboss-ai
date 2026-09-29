"""LP-920's "Done when", through the database: round 1's plan is plan §6, and round 2 keeps it.

The model is MOCKED (`reading_fixture`), the lender is UWM (so its canonical settings apply: the lender
orders the final inspection, decision 1), and the file holds one fictional document — a credit report
invoice dated 07/15 — so 0006 is "Already in the file", as S3-02 draws it.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import uuid4

import pytest
from app.models.activity_log import ActivityLog, ActivityType
from app.models.condition import Condition, ConditionReadingStatus
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_item import ConditionItem
from app.models.condition_round import ConditionRound, ConditionSourceKind
from app.models.condition_vocabulary import ConditionItemStatus, PlanOption
from app.models.document import Document, DocumentStatus
from app.models.loan_file import LoanFile
from app.models.needs_item import NeedsItem, NeedsItemOrigin
from app.services import condition_reading
from app.services.condition_import import import_round
from app.services.condition_plan import (
    PlanRefused,
    build_plan,
    carry_plan,
    confirm_round_plan,
    round_plan_summary,
    set_lender_processing,
)
from app.services.condition_reading import ConfirmedItem, confirm_reading, read_round
from app.services.condition_rounds import SheetBytes, create_round_from_sheet
from app.tasks.conditions import parse_round
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.fixture_helpers import UWM_ROUND_2
from tests.conditions.reading_fixture import fake_complete
from tests.conditions.test_condition_reading import _file_with_round
from tests.conditions.uwm_pdf_fixture import render_uwm_pdf


@pytest.fixture(autouse=True)
def _mocked_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(condition_reading, "complete", fake_complete())


async def _credit_invoice(db: AsyncSession, loan_file: LoanFile) -> Document:
    doc = Document(
        id=uuid4(),
        loan_file_id=loan_file.id,
        original_filename="invoice.pdf",
        mime_type="application/pdf",
        file_size_bytes=10,
        storage_path=f"{loan_file.company_id}/{loan_file.id}/invoice.pdf",
        document_type="service_invoice",
        document_name="Credit invoice 07/15",
        status=DocumentStatus.COMPLETED,
        upload_source="user_upload",
    )
    db.add(doc)
    await db.flush()
    return doc


async def _actor(db: AsyncSession, loan_file: LoanFile) -> Any:
    from app.core.security import hash_password
    from app.models import User, UserRole

    user = User(
        company_id=loan_file.company_id,
        email=f"a-{uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("irrelevant"),
        first_name="Priya",
        last_name="Raman",
        role=UserRole.PROCESSOR,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user.id


async def _planned_round_one(db: AsyncSession) -> tuple[LoanFile, ConditionRound]:
    loan_file, round_ = await _file_with_round(db)
    await _credit_invoice(db, loan_file)
    await read_round(db, round_id=round_.id)
    await build_plan(db, round_id=round_.id, today=date(2026, 8, 28))
    return loan_file, round_


async def _conditions(db: AsyncSession, loan_file: LoanFile) -> dict[str, Condition]:
    rows = (
        await db.execute(select(Condition).where(Condition.loan_file_id == loan_file.id))
    ).scalars()
    return {row.lender_code or "": row for row in rows}


async def _items(db: AsyncSession, condition: Condition) -> list[ConditionItem]:
    return list(
        (
            await db.execute(
                select(ConditionItem)
                .where(
                    ConditionItem.condition_id == condition.id, ConditionItem.deleted_at.is_(None)
                )
                .order_by(ConditionItem.sequence)
            )
        ).scalars()
    )


async def test_round_one_plan_is_plan_section_6(db_session: AsyncSession) -> None:
    loan_file, round_ = await _planned_round_one(db_session)
    by_code = await _conditions(db_session, loan_file)

    async def options(code: str) -> list[str]:
        return [item.option.value for item in await _items(db_session, by_code[code])]

    # 1228 — lender is doing it: UWM orders the final inspection (decision 1).
    assert by_code["1228"].next_step is PlanOption.LENDER_DOING_IT
    assert by_code["1228"].plan_reason == "Ordered through the lender — confirm on your files"
    # 7086, 6132 — ask the borrower; 7086's reason is code's arithmetic.
    assert set(await options("7086")) == {"ask_borrower"}
    assert by_code["7086"].plan_reason == "Shortfall computed by code"
    assert await options("6132") == ["ask_borrower"]
    # 6637 — borrower email + title email.
    assert await options("6637") == ["ask_borrower", "ask_third_party", "ask_borrower"]
    # 6178 — push back, nothing to collect.
    assert by_code["6178"].next_step is PlanOption.PUSH_BACK
    assert by_code["6178"].plan_reason == "Reason from the letter"
    assert all(
        i.status is ConditionItemStatus.NOT_NEEDED
        for i in await _items(db_session, by_code["6178"])
    )
    # 0132 — LO email + attorney email, and she must confirm the reading.
    assert set(await options("0132")) == {"ask_third_party"}
    assert by_code["0132"].plan_reason == "Please confirm how we read this"
    # 1947, 6378 — title email; 6378 is information to pass on.
    assert await options("1947") == ["ask_third_party"]
    assert await options("6378") == ["ask_third_party"]
    assert by_code["6378"].plan_reason == "Added to the title email"
    # 1582, 0007 — her tasks; 0007 waits on 1228.
    assert await options("1582") == ["i_will_do_it"]
    assert await options("0007") == ["i_will_do_it"]
    assert (await _items(db_session, by_code["0007"]))[0].waits_on_condition_id == by_code[
        "1228"
    ].id
    assert by_code["0007"].plan_reason == "Waits on 1228"
    # 0006 — already in the file (credit invoice 07/15, page 1), and not the processing invoice's.
    invoice = (await _items(db_session, by_code["0006"]))[0]
    assert invoice.option is PlanOption.ALREADY_IN_FILE and invoice.document_page == 1
    assert by_code["0006"].plan_reason == "Found: Credit invoice 07/15, page 1"
    assert (await _items(db_session, by_code["1582"]))[0].document_id is None

    # No condition is left without a plan.
    for code, condition in by_code.items():
        assert condition.next_step is not None or await _items(db_session, condition), code

    summary = await round_plan_summary(db_session, round_=round_)
    assert [d.label for d in summary.drafts] == ["Borrower", "Title/attorney", "LO"]
    assert [d.codes for d in summary.drafts] == [
        ["6132", "6637", "7086"],
        ["0132", "1947", "6378", "6637"],
        ["0132"],
    ]
    assert (summary.your_tasks, summary.already_in_file, summary.push_back) == (2, 1, 1)
    assert (summary.lender_doing_it, summary.needs_confirmation) == (1, 1)
    assert summary.blocking_codes == ["0132"]


async def test_the_borrowers_statements_are_asked_for_once(db_session: AsyncSession) -> None:
    """§4a change 2: 7086's statements, 6132's next month and 6637's source and clearance are ONE need,
    and 6637's items pick up the account from it (S3-01's "Capital One ··9912")."""
    loan_file, _ = await _planned_round_one(db_session)
    by_code = await _conditions(db_session, loan_file)
    statement_items = [
        item
        for code in ("7086", "6132", "6637")
        for item in await _items(db_session, by_code[code])
        if item.documents[:1] == ["bank_statement"] and item.key != "other_accounts"
    ]
    assert len(statement_items) == 4
    assert len({item.need_id for item in statement_items}) == 1
    need = await db_session.get(NeedsItem, statement_items[0].need_id)
    assert need is not None and need.origin is NeedsItemOrigin.CONDITION
    assert need.title == "Capital One ··9912 statements, July and August 2026"
    assert all(item.specifics.get("account_last4") == "9912" for item in statement_items)
    # And nothing on the round is asked twice: one need per distinct ask.
    needs = (
        (await db_session.execute(select(NeedsItem).where(NeedsItem.loan_file_id == loan_file.id)))
        .scalars()
        .all()
    )
    assert len({(n.needs_type, n.title) for n in needs}) == len(needs)


async def test_round_two_keeps_the_plan_for_conditions_seen_again(db_session: AsyncSession) -> None:
    loan_file, _ = await _planned_round_one(db_session)
    before = {
        c.lender_code: [i.id for i in await _items(db_session, c)]
        for c in (await _conditions(db_session, loan_file)).values()
    }
    needs_before = await db_session.scalar(
        select(func.count()).where(NeedsItem.loan_file_id == loan_file.id)
    )

    round_2 = await create_round_from_sheet(
        db_session,
        loan_file=loan_file,
        sheet=SheetBytes(
            content=render_uwm_pdf(UWM_ROUND_2), source_kind=ConditionSourceKind.PDF_UPLOAD
        ),
    )
    await db_session.flush()
    await parse_round(db_session, round_2.id)
    await db_session.refresh(round_2)
    await import_round(db_session, round_=round_2)
    await read_round(db_session, round_id=round_2.id)
    await build_plan(db_session, round_id=round_2.id)

    by_code = await _conditions(db_session, loan_file)
    seen_again = [c for c in by_code.values() if c.last_seen_round_id == round_2.id]
    assert len(seen_again) == 6
    for condition in seen_again:
        assert [i.id for i in await _items(db_session, condition)] == before[condition.lender_code]
    assert (
        await db_session.scalar(select(func.count()).where(NeedsItem.loan_file_id == loan_file.id))
        == needs_before
    )


async def test_the_file_switch_turns_third_party_asks_into_the_lenders(
    db_session: AsyncSession,
) -> None:
    loan_file, _ = await _planned_round_one(db_session)
    by_code = await _conditions(db_session, loan_file)
    actor = await _actor(db_session, loan_file)
    moved = await set_lender_processing(
        db_session, loan_file=loan_file, on=True, actor_user_id=actor
    )
    assert moved > 0
    assert [i.option for i in await _items(db_session, by_code["1947"])] == [
        PlanOption.LENDER_DOING_IT
    ]
    # The borrower's own asks are untouched.
    assert {i.option for i in await _items(db_session, by_code["6132"])} == {
        PlanOption.ASK_BORROWER
    }
    await set_lender_processing(db_session, loan_file=loan_file, on=False, actor_user_id=actor)
    assert [i.option for i in await _items(db_session, by_code["1947"])] == [
        PlanOption.ASK_THIRD_PARTY
    ]


async def test_the_plan_cannot_be_confirmed_past_a_reading_that_needs_her(
    db_session: AsyncSession,
) -> None:
    loan_file, round_ = await _planned_round_one(db_session)
    actor = await _actor(db_session, loan_file)
    with pytest.raises(
        PlanRefused, match=r"Confirm 0132's reading first — one condition still needs you\."
    ):
        await confirm_round_plan(db_session, round_=round_, actor_user_id=actor)

    condition = (await _conditions(db_session, loan_file))["0132"]
    await confirm_reading(
        db_session,
        condition=condition,
        items=[
            ConfirmedItem(name=i.name, performers=(i.performer,), key=i.key)
            for i in await _items(db_session, condition)
        ],
        actor_user_id=actor,
    )
    assert condition.reading_status is ConditionReadingStatus.CONFIRMED
    await confirm_round_plan(db_session, round_=round_, actor_user_id=actor)
    assert round_.plan_confirmed_at is not None
    assert (
        await db_session.scalar(
            select(func.count()).where(
                ConditionEvent.round_id == round_.id,
                ConditionEvent.kind == ConditionEventKind.ROUND_PLAN_CONFIRMED,
            )
        )
        == 1
    )
    kinds = (
        (
            await db_session.execute(
                select(ActivityLog.activity_type).where(ActivityLog.loan_file_id == loan_file.id)
            )
        )
        .scalars()
        .all()
    )
    assert (
        ActivityType.CONDITION_PLAN_READY in kinds
        and ActivityType.CONDITION_PLAN_CONFIRMED in kinds
    )


async def test_every_planned_condition_has_an_event(db_session: AsyncSession) -> None:
    _, round_ = await _planned_round_one(db_session)
    count = await db_session.scalar(
        select(func.count()).where(
            ConditionEvent.round_id == round_.id,
            ConditionEvent.kind == ConditionEventKind.CONDITION_PLANNED,
        )
    )
    assert count == 11


async def test_a_replaced_condition_hands_its_plan_on(db_session: AsyncSession) -> None:
    loan_file, _ = await _planned_round_one(db_session)
    by_code = await _conditions(db_session, loan_file)
    old = by_code["1947"]
    new = by_code["6378"]
    for item in await _items(db_session, new):
        item.deleted_at = item.created_at  # empty the successor so the carry is observable
    new.next_step = None
    await db_session.flush()
    carried = await carry_plan(db_session, from_condition=old, to_condition=new, actor_user_id=None)
    assert carried == 1
    items = await _items(db_session, new)
    assert [i.key for i in items] == ["seller_cd"] and items[0].origin.value == "carried"
    assert new.reading_status is ConditionReadingStatus.NEEDS_CONFIRMATION


# --------------------------------------------------------------------------------------------- #
# Her edits through the API, and tenancy
# --------------------------------------------------------------------------------------------- #


async def test_she_can_change_any_part_of_the_plan(db_session: AsyncSession) -> None:
    from app.core.database import get_db
    from app.main import app
    from tests.conditions.test_condition_reading import _client_for

    loan_file, _ = await _planned_round_one(db_session)
    condition = (await _conditions(db_session, loan_file))["1947"]
    client, auth = await _client_for(db_session, loan_file)
    other_file, _ = await _file_with_round(db_session)
    other_client, other_auth = await _client_for(db_session, other_file)
    try:
        async with client:
            base = f"/api/v1/conditions/{condition.id}"
            item_id = str((await _items(db_session, condition))[0].id)
            changed = await client.patch(
                f"{base}/items/{item_id}", headers=auth, json={"option": "ask_underwriter"}
            )
            assert changed.status_code == 200, changed.text
            assert changed.json()["items"][0]["option"] == "ask_underwriter"
            added = await client.post(
                f"{base}/items",
                headers=auth,
                json={"name": "Payoff letter", "performers": ["title"]},
            )
            assert added.status_code == 200 and len(added.json()["items"]) == 2
            step = await client.put(
                f"{base}/next-step", headers=auth, json={"next_step": "push_back"}
            )
            assert step.json()["next_step"] == "push_back"
            removed = await client.delete(f"{base}/items/{item_id}", headers=auth)
            assert len(removed.json()["items"]) == 1
            events = await db_session.scalar(
                select(func.count()).where(
                    ConditionEvent.condition_id == condition.id,
                    ConditionEvent.kind == ConditionEventKind.CONDITION_PLAN_CHANGED,
                )
            )
            assert events == 4
        async with other_client:
            refused = await other_client.patch(
                f"/api/v1/conditions/{condition.id}/items/{item_id}",
                headers=other_auth,
                json={"option": "push_back"},
            )
            assert refused.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)


async def test_the_sheet_sees_which_items_are_asked_for_once(db_session: AsyncSession) -> None:
    """S3-01's "Same statement as 7086 and 6132 — asked for once", in sheet order, and the account the
    shared need carries on 6637's items."""
    from app.services.condition_plan import items_public_for_file

    loan_file, _ = await _planned_round_one(db_session)
    by_code = await _conditions(db_session, loan_file)
    items = (await items_public_for_file(db_session, loan_file_id=loan_file.id))[by_code["6637"].id]
    assert items[0].shared_with_codes == ["7086", "6132"]
    assert items[1].shared_with_codes == []  # the receipt is title's own ask
    assert items[0].specifics.account_last4 == "9912"
    assert items[0].need_title == "Capital One ··9912 statements, July and August 2026"

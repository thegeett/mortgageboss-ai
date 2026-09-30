"""LP-940: a condition added by hand and entered in error can be withdrawn, with a reason, and put back.

Withdrawal is the soft delete plus a `condition_withdrawn` event. It takes the condition out of the list,
the counts, the plan, the drafts and the package, and keeps it in a "Withdrawn (n)" section with Undo.
Refused for a sheet condition (ADR-404), for one the lender answered on, and for one in a submitted
package.

TWO TESTS MARK A SHEET CONDITION AS HAND-ADDED (`origin = manual`), and say so. That is the only way to
put a hand-added condition into a confirmed plan's draft, or into a package, without building stored
rows by hand. Everything else uses a real hand-added condition (`create_manual_condition`).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from app.models.condition import Condition, ConditionLenderStatus, ConditionOrigin
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_item import ConditionItem
from app.models.loan_file import LoanFile
from app.schemas.condition import ConditionCreateRequest, VerdictRequest, VerdictSourceKind
from app.services import condition_package, condition_withdraw
from app.services.condition_import import create_manual_condition
from app.services.condition_status import record_verdict
from app.services.condition_withdraw import WithdrawRefused
from app.services.conditions import condition_summary, list_conditions
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.test_condition_drafts import _confirmed, _drafts
from tests.conditions.test_condition_package import _model_writes, _ready

REASON = "Added twice by mistake — 1582 already asks for it"


async def _hand_added(db: AsyncSession, loan_file: LoanFile, actor: Any) -> Condition:
    return await create_manual_condition(
        db,
        loan_file=loan_file,
        payload=ConditionCreateRequest(
            verbatim_text="Provide a copy of the processing invoice.", lender_code="9001"
        ),
        actor_user_id=actor,
    )


async def _codes(db: AsyncSession, loan_file: LoanFile) -> set[str | None]:
    return {c.lender_code for c in await list_conditions(db, loan_file_id=loan_file.id)}


async def test_a_hand_added_condition_is_withdrawn_and_put_back(db_session: AsyncSession) -> None:
    db = db_session
    loan_file, _, _, actor = await _confirmed(db)
    added = await _hand_added(db, loan_file, actor)
    assert "9001" in await _codes(db, loan_file)  # the positive control
    before = (await condition_summary(db, loan_file_id=loan_file.id)).open

    await condition_withdraw.withdraw(
        db, condition=added, reason=f"  {REASON}  ", actor_user_id=actor
    )
    # Off the list and the counts; still a row, with its history.
    assert "9001" not in await _codes(db, loan_file)
    assert (await condition_summary(db, loan_file_id=loan_file.id)).open == before - 1
    assert added.deleted_at is not None
    (event,) = (
        await db.execute(
            select(ConditionEvent).where(
                ConditionEvent.condition_id == added.id,
                ConditionEvent.kind == ConditionEventKind.CONDITION_WITHDRAWN,
            )
        )
    ).scalars()
    assert event.detail == {"reason": REASON} and event.actor_user_id == actor
    (row,) = await condition_withdraw.withdrawn_for_file(db, loan_file_id=loan_file.id)
    assert (row.id, row.lender_code, row.reason) == (added.id, "9001", REASON)

    # Undo: back on the list and the counts, out of the section, with its own event.
    await condition_withdraw.restore(db, condition=added, actor_user_id=actor)
    assert "9001" in await _codes(db, loan_file)
    assert (await condition_summary(db, loan_file_id=loan_file.id)).open == before
    assert await condition_withdraw.withdrawn_for_file(db, loan_file_id=loan_file.id) == []
    kinds = list(
        (
            await db.execute(
                select(ConditionEvent.kind)
                .where(ConditionEvent.condition_id == added.id)
                .order_by(ConditionEvent.occurred_at)
            )
        ).scalars()
    )
    assert kinds[-2:] == [
        ConditionEventKind.CONDITION_WITHDRAWN,
        ConditionEventKind.CONDITION_RESTORED,
    ]
    # Undo refuses a condition that is not withdrawn.
    with pytest.raises(WithdrawRefused, match="not withdrawn"):
        await condition_withdraw.restore(db, condition=added, actor_user_id=actor)


async def test_each_refusal_says_why(db_session: AsyncSession) -> None:
    db = db_session
    loan_file, _, conditions, actor = await _confirmed(db)
    # A sheet condition: ADR-404 — only the lender clears it.
    with pytest.raises(WithdrawRefused) as sheet:
        await condition_withdraw.withdraw(
            db, condition=conditions["1582"], reason=REASON, actor_user_id=actor
        )
    assert sheet.value.reason == condition_withdraw.NOT_HAND_ADDED
    added = await _hand_added(db, loan_file, actor)
    # No reason.
    with pytest.raises(WithdrawRefused) as empty:
        await condition_withdraw.withdraw(db, condition=added, reason="   ", actor_user_id=actor)
    assert empty.value.reason == condition_withdraw.NO_REASON
    # The lender answered on it: its word, not hers.
    await record_verdict(
        db,
        condition=added,
        payload=VerdictRequest(
            status=ConditionLenderStatus.CLEARED,
            source_kind=VerdictSourceKind.PORTAL,
            source_date=date(2026, 9, 10),
        ),
        actor_user_id=actor,
    )
    with pytest.raises(WithdrawRefused) as answered:
        await condition_withdraw.withdraw(db, condition=added, reason=REASON, actor_user_id=actor)
    assert answered.value.reason == condition_withdraw.LENDER_ANSWERED
    # Nothing was withdrawn by any refusal.
    assert added.deleted_at is None and conditions["1582"].deleted_at is None


async def test_it_leaves_the_unsent_draft_and_returns_on_undo(db_session: AsyncSession) -> None:
    """7086, MARKED HAND-ADDED here (see the module docstring), sits in the unsent borrower email."""
    db = db_session
    loan_file, _, conditions, actor = await _confirmed(db)
    seven = conditions["7086"]
    seven.origin = ConditionOrigin.MANUAL

    async def in_borrower_email() -> bool:
        draft, _ = (await _drafts(db, loan_file))["borrower"]
        items = (
            await db.execute(select(ConditionItem).where(ConditionItem.draft_id == draft.id))
        ).scalars()
        return any(item.condition_id == seven.id for item in items)

    assert await in_borrower_email()  # the positive control
    await condition_withdraw.withdraw(db, condition=seven, reason=REASON, actor_user_id=actor)
    assert not await in_borrower_email()
    await condition_withdraw.restore(db, condition=seven, actor_user_id=actor)
    assert await in_borrower_email()


async def test_it_leaves_a_built_package_and_is_refused_once_submitted(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """6178, MARKED HAND-ADDED here (see the module docstring), is Ready and in the built package."""
    _model_writes(monkeypatch, {})
    db = db_session
    loan_file, conditions, actor = await _ready(db)
    six = conditions["6178"]
    six.origin = ConditionOrigin.MANUAL
    package = await condition_package.build(db, loan_file=loan_file, actor_user_id=actor)
    assert "6178" in [r["code"] for r in package.rows]  # the positive control
    await condition_withdraw.withdraw(db, condition=six, reason=REASON, actor_user_id=actor)
    view = await condition_package.view(db, loan_file=loan_file)
    assert view is not None and "6178" not in [r["code"] for r in view.rows]
    # The stored rows are not rewritten; Mark submitted skips the withdrawn one.
    assert "6178" in [r["code"] for r in package.rows]
    moved = await condition_package.submit(
        db, loan_file=loan_file, package=package, actor_user_id=actor
    )
    assert "6178" not in moved
    # Back, and now in a SUBMITTED package's record: it stays on the file.
    await condition_withdraw.restore(db, condition=six, actor_user_id=actor)
    seven = conditions["7086"]
    seven.origin = ConditionOrigin.MANUAL
    with pytest.raises(WithdrawRefused) as sent:
        await condition_withdraw.withdraw(db, condition=seven, reason=REASON, actor_user_id=actor)
    assert sent.value.reason.startswith("It went to the lender in the package submitted on ")
    assert sent.value.reason.endswith(", so it stays on the file.")


@pytest.fixture(autouse=True)
def _drop_db_override() -> Any:
    from app.core.database import get_db
    from app.main import app

    yield
    app.dependency_overrides.pop(get_db, None)


async def test_the_routes(db_session: AsyncSession) -> None:
    from tests.conditions.test_lender_condition_settings import _clients

    db = db_session
    loan_file, _, conditions, actor = await _confirmed(db)
    added = await _hand_added(db, loan_file, actor)
    client, _, headers = await _clients(db, loan_file)
    async with client:
        refused = await client.post(
            f"/api/v1/conditions/{conditions['1582'].id}/withdraw",
            json={"reason": REASON},
            headers=headers,
        )
        assert refused.status_code == 409
        assert refused.json()["error"]["message"] == condition_withdraw.NOT_HAND_ADDED
        done = await client.post(
            f"/api/v1/conditions/{added.id}/withdraw", json={"reason": REASON}, headers=headers
        )
        assert done.status_code == 200, done.text
        assert done.json()["reason"] == REASON
        # Withdrawn: not found by id any more, listed in the section.
        gone = await client.post(
            f"/api/v1/conditions/{added.id}/withdraw", json={"reason": REASON}, headers=headers
        )
        assert gone.status_code == 404
        listed = await client.get(
            f"/api/v1/loan-files/{loan_file.id}/withdrawn-conditions", headers=headers
        )
        assert [r["lender_code"] for r in listed.json()] == ["9001"]
        back = await client.post(
            f"/api/v1/loan-files/{loan_file.id}/conditions/{added.id}/restore", headers=headers
        )
        assert back.status_code == 200, back.text
        assert back.json()["lender_code"] == "9001"


async def test_another_companys_withdrawn_condition_is_not_found(db_session: AsyncSession) -> None:
    from tests.conditions.test_lender_condition_settings import _clients

    db = db_session
    loan_file, _, _, actor = await _confirmed(db)
    added = await _hand_added(db, loan_file, actor)
    await condition_withdraw.withdraw(db, condition=added, reason=REASON, actor_user_id=actor)
    other, _, _, _ = await _confirmed(db)
    client, _, headers = await _clients(db, other)
    async with client:
        # Their file's path with our condition id: not found, and not restored.
        response = await client.post(
            f"/api/v1/loan-files/{other.id}/conditions/{added.id}/restore", headers=headers
        )
        assert response.status_code == 404
        # Our file's path from their company: the file gate refuses it.
        ours = await client.get(
            f"/api/v1/loan-files/{loan_file.id}/withdrawn-conditions", headers=headers
        )
        assert ours.status_code == 404
    assert added.deleted_at is not None


def test_only_a_withdrawal_deletes_a_condition() -> None:
    """THE PREMISE `restore` RESTS ON: it treats any soft-deleted condition as withdrawn, which holds
    only while nothing else sets `conditions.deleted_at`. A second writer fails this, and `restore` then
    needs to tell the two apart."""
    import re
    from pathlib import Path

    app = Path(__file__).resolve().parents[2] / "app"
    writers = sorted(
        str(path.relative_to(app))
        for path in app.rglob("*.py")
        if re.search(r"\bcondition\.deleted_at\s*=", path.read_text(encoding="utf-8"))
    )
    assert writers == ["services/condition_withdraw.py"]


async def test_a_withdrawn_conditions_evidence_proposes_no_figures(
    db_session: AsyncSession,
) -> None:
    """7086, MARKED HAND-ADDED here (see the module docstring), with its statements accepted: the
    figures check proposes its verified assets until it is withdrawn."""
    from app.services import figures_check
    from tests.conditions.test_figures_check import _s3_09

    db = db_session
    loan_file, conditions, actor = await _s3_09(db)
    seven = conditions["7086"]
    seven.origin = ConditionOrigin.MANUAL
    keys = {c.key for c in (await figures_check.figures_check(db, loan_file=loan_file)).changes}
    assert "verified_assets" in keys  # the positive control
    await condition_withdraw.withdraw(db, condition=seven, reason=REASON, actor_user_id=actor)
    keys = {c.key for c in (await figures_check.figures_check(db, loan_file=loan_file)).changes}
    assert "verified_assets" not in keys

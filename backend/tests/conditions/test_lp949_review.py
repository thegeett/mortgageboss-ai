"""LP-949 review — the cases the build's tests did not reach (docs/tickets/LP-949.md, "Review").

Each test here failed on the build commit (86089cf7) before its fix, except where a docstring says it
is a positive control.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.models import Company
from app.models.condition import Condition
from app.models.lender_condition_code import LenderConditionCode
from app.services.condition_lender import (
    LenderRefused,
    file_lender_payload,
    set_file_lender,
)
from app.services.lender_settings import map_code
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.test_lp949_lender_on_the_file import (
    _by_code,
    _company,
    _file_without_lender,
)
from tests.models.conftest_helpers import make_lender

#: ALL SIX of LF-DH8V's codes (the trial brief, item 1), 1582 included: the build's table left it out.
LF_DH8V_TYPES = {
    "0006": "IV-01",
    "0007": "IV-03",
    "1228": "PA-03",
    "1582": "IV-02",
    "1947": "TI-03",
    "6378": "TI-04",
}


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    from app.api import conditions as conditions_api

    calls: list[str] = []
    monkeypatch.setattr(conditions_api, "_enqueue_reading", lambda rid: calls.append(str(rid)))
    return calls


@pytest.fixture(autouse=True)
def _drop_db_override() -> Any:
    from app.core.database import get_db
    from app.main import app

    yield
    app.dependency_overrides.pop(get_db, None)


async def test_all_six_lf_dh8v_codes_get_their_uwm_types(db_session: AsyncSession) -> None:
    loan_file, _ = await _file_without_lender(db_session)
    await set_file_lender(
        db_session, loan_file=loan_file, lender_key="uwm", lender_id=None, actor_user_id=None
    )
    conditions = await _by_code(db_session, loan_file)
    assert {code: conditions[code].canonical_type_id for code in LF_DH8V_TYPES} == LF_DH8V_TYPES


async def test_a_lender_cleared_then_set_still_types_the_untyped(db_session: AsyncSession) -> None:
    """A -> none -> UWM must do what A -> UWM does. The build left A's untyped conditions at A."""
    loan_file, round_ = await _file_without_lender(db_session)
    company = await db_session.get(Company, loan_file.company_id)
    assert company is not None
    wrong = await make_lender(db_session, company=company, name="Wrong Lender")
    await set_file_lender(
        db_session, loan_file=loan_file, lender_key=None, lender_id=wrong.id, actor_user_id=None
    )
    conditions = await _by_code(db_session, loan_file)
    assert conditions["1228"].lender_id == wrong.id  # the premise: A took them, untyped
    assert conditions["1228"].canonical_type_id is None

    from app.schemas.loan_file import LoanFileUpdate
    from app.services.loan_files import update_loan_file

    await update_loan_file(db_session, loan_file=loan_file, data=LoanFileUpdate(lender_id=None))
    await set_file_lender(
        db_session, loan_file=loan_file, lender_key="uwm", lender_id=None, actor_user_id=None
    )
    conditions = await _by_code(db_session, loan_file)
    assert {code: conditions[code].canonical_type_id for code in LF_DH8V_TYPES} == LF_DH8V_TYPES
    assert conditions["1228"].lender_id == loan_file.lender_id
    await db_session.refresh(round_)
    assert round_.lender_id == loan_file.lender_id


async def test_a_patch_to_another_companys_lender_is_refused(
    db_session: AsyncSession, queued: list[str]
) -> None:
    """The hook would otherwise write review rows onto, and type from, another tenant's lender."""
    from tests.conditions.test_lender_condition_settings import _clients

    loan_file, _ = await _file_without_lender(db_session)
    company = await db_session.get(Company, loan_file.company_id)
    assert company is not None
    mine = await make_lender(db_session, company=company, name="Mine")
    theirs = await make_lender(db_session, company=await _company(db_session), name="Theirs")
    client, _, processor = await _clients(db_session, loan_file)
    async with client:
        refused = await client.patch(
            f"/api/v1/loan-files/{loan_file.id}",
            json={"lender_id": str(theirs.id)},
            headers=processor,
        )
        assert refused.status_code == 422, refused.text
        # THE POSITIVE CONTROL: her own lender goes through the same door.
        allowed = await client.patch(
            f"/api/v1/loan-files/{loan_file.id}",
            json={"lender_id": str(mine.id)},
            headers=processor,
        )
        assert allowed.status_code == 200, allowed.text
    rows = await db_session.scalar(
        select(func.count(LenderConditionCode.id)).where(LenderConditionCode.lender_id == theirs.id)
    )
    assert rows == 0
    foreign = await db_session.scalar(
        select(func.count(Condition.id)).where(Condition.lender_id == theirs.id)
    )
    assert foreign == 0
    await db_session.refresh(loan_file)
    assert loan_file.lender_id == mine.id


async def test_a_patch_that_does_not_change_the_lender_queues_nothing(
    db_session: AsyncSession, queued: list[str]
) -> None:
    from tests.conditions.test_lender_condition_settings import _clients

    loan_file, _ = await _file_without_lender(db_session)
    client, _, processor = await _clients(db_session, loan_file)
    async with client:
        same = await client.patch(
            f"/api/v1/loan-files/{loan_file.id}", json={"lender_id": None}, headers=processor
        )
        assert same.status_code == 200, same.text
    assert queued == []


async def test_the_suggestion_says_when_its_lender_has_no_codes(db_session: AsyncSession) -> None:
    """A same-named lender without the key: the banner must not promise a match to the library."""
    loan_file, _ = await _file_without_lender(db_session)
    payload = await file_lender_payload(db_session, loan_file=loan_file)
    assert payload["suggestion"]["has_code_map"] is True  # created with the key and seeded

    company = await db_session.get(Company, loan_file.company_id)
    assert company is not None
    await make_lender(db_session, company=company, name="United Wholesale Mortgage")
    payload = await file_lender_payload(db_session, loan_file=loan_file)
    assert payload["suggestion"]["lender_exists"] is True
    assert payload["suggestion"]["has_code_map"] is False


async def test_a_keyless_lender_has_a_code_map_once_a_code_is_mapped(
    db_session: AsyncSession,
) -> None:
    """The banner said "has no condition codes in the app" for ever, after an admin mapped them."""
    loan_file, _ = await _file_without_lender(db_session)
    company = await db_session.get(Company, loan_file.company_id)
    assert company is not None
    lender = await make_lender(db_session, company=company, name="Small Lender")
    await set_file_lender(
        db_session, loan_file=loan_file, lender_key=None, lender_id=lender.id, actor_user_id=None
    )
    assert (await file_lender_payload(db_session, loan_file=loan_file))["lender"][
        "has_code_map"
    ] is False
    await map_code(db_session, lender=lender, code="0006", canonical_type_id="IV-01")
    assert (await file_lender_payload(db_session, loan_file=loan_file))["lender"][
        "has_code_map"
    ] is True


async def test_only_a_shipped_lender_can_be_added_from_the_tab(db_session: AsyncSession) -> None:
    """A processor may add a lender here (ADR-417), but only one the app ships, by its key."""
    loan_file, _ = await _file_without_lender(db_session)
    with pytest.raises(LenderRefused):
        await set_file_lender(
            db_session, loan_file=loan_file, lender_key="acme", lender_id=None, actor_user_id=None
        )
    from app.models.lender import Lender

    count = await db_session.scalar(
        select(func.count(Lender.id)).where(Lender.company_id == loan_file.company_id)
    )
    assert count == 0


async def test_the_hook_never_applies_another_companys_lender(db_session: AsyncSession) -> None:
    """The second lock: `update_loan_file` is a service any caller reaches, not only the PATCH."""
    from app.schemas.loan_file import LoanFileUpdate
    from app.services.loan_files import update_loan_file

    loan_file, _ = await _file_without_lender(db_session)
    theirs = await make_lender(db_session, company=await _company(db_session), name="Theirs")
    await update_loan_file(
        db_session, loan_file=loan_file, data=LoanFileUpdate(lender_id=theirs.id)
    )
    rows = await db_session.scalar(
        select(func.count(LenderConditionCode.id)).where(LenderConditionCode.lender_id == theirs.id)
    )
    assert rows == 0
    conditions = await _by_code(db_session, loan_file)
    assert all(c.lender_id is None for c in conditions.values())
    # THE POSITIVE CONTROL: her own keyless lender, through the same call, does take them.
    company = await db_session.get(Company, loan_file.company_id)
    assert company is not None
    mine = await make_lender(db_session, company=company, name="Mine")
    await update_loan_file(db_session, loan_file=loan_file, data=LoanFileUpdate(lender_id=mine.id))
    conditions = await _by_code(db_session, loan_file)
    assert all(c.lender_id == mine.id for c in conditions.values() if c.lender_code)

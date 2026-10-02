"""LP-952 — the reading's state and Read again (items 4 and 5 of the 2026-09-30 staging trial).

LF-DH8V's round 1 was imported before the reading existed, so its conditions said "Not read yet" for
ever and nothing on screen said whether a reading was running, had failed, or had never been queued.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.models.condition import ConditionReadingStatus
from app.models.condition_round import ConditionRound
from app.services import condition_reading
from app.services.condition_reading import read_round
from app.services.condition_reading_state import (
    DONE,
    FAILED,
    NOT_QUEUED,
    QUEUED,
    READING,
    is_running,
    mark,
    reading_state,
)
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.reading_fixture import fake_complete
from tests.conditions.test_lp949_lender_on_the_file import _by_code, _file_without_lender


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(condition_reading, "complete", fake_complete(calls))
    return calls


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    from app.api import conditions as conditions_api

    calls: list[str] = []

    def _send(round_id: Any) -> bool:
        calls.append(str(round_id))
        return True

    monkeypatch.setattr(conditions_api, "_enqueue_reading", _send)
    return calls


@pytest.fixture(autouse=True)
def _drop_db_override() -> Any:
    from app.core.database import get_db
    from app.main import app

    yield
    app.dependency_overrides.pop(get_db, None)


def _ago(minutes: int) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat()


# --------------------------------------------------------------------------------------------- #
# The state
# --------------------------------------------------------------------------------------------- #


async def test_lf_dh8v_round_one_reads_as_not_queued(db_session: AsyncSession) -> None:
    """Imported, nothing queued (the import here is the service, not the route), all unread."""
    loan_file, round_ = await _file_without_lender(db_session)
    state = await reading_state(db_session, round_=round_)
    conditions = await _by_code(db_session, loan_file)
    assert state == {"state": NOT_QUEUED, "unread": len(conditions), "error": None}


async def test_a_reading_goes_queued_reading_done(
    db_session: AsyncSession, model: list[str]
) -> None:
    _, round_ = await _file_without_lender(db_session)
    mark(round_, QUEUED)
    assert (await reading_state(db_session, round_=round_))["state"] == QUEUED
    assert is_running(round_)
    mark(round_, READING)
    assert (await reading_state(db_session, round_=round_))["state"] == READING
    await read_round(db_session, round_id=round_.id)
    state = await reading_state(db_session, round_=round_)
    assert state == {"state": DONE, "unread": 0, "error": None}
    assert round_.reading_run is not None and round_.reading_run["state"] == DONE
    assert not is_running(round_)


async def test_a_stale_queued_or_running_reading_is_failed(db_session: AsyncSession) -> None:
    _, round_ = await _file_without_lender(db_session)
    for state in (QUEUED, READING):
        round_.reading_run = {"state": state, "at": _ago(20)}
        got = await reading_state(db_session, round_=round_)
        assert (got["state"], got["error"]) == (FAILED, "stalled")
        assert not is_running(round_)
        # The positive control: a fresh one is still running.
        round_.reading_run = {"state": state, "at": _ago(1)}
        assert is_running(round_)


async def test_a_run_written_before_lp952_reads_as_done(
    db_session: AsyncSession, model: list[str]
) -> None:
    _, round_ = await _file_without_lender(db_session)
    await read_round(db_session, round_id=round_.id)
    assert round_.reading_run is not None
    legacy = {k: v for k, v in round_.reading_run.items() if k != "state"}
    round_.reading_run = legacy
    assert (await reading_state(db_session, round_=round_))["state"] == DONE


# --------------------------------------------------------------------------------------------- #
# The routes
# --------------------------------------------------------------------------------------------- #


async def test_read_conditions_queues_once_and_refuses_while_queued(
    db_session: AsyncSession, queued: list[str]
) -> None:
    from tests.conditions.test_lender_condition_settings import _clients

    loan_file, round_ = await _file_without_lender(db_session)
    client, _, processor = await _clients(db_session, loan_file)
    base = f"/api/v1/condition-rounds/{round_.id}"
    async with client:
        before = await client.get(f"{base}/reading", headers=processor)
        assert before.json()["state"] == NOT_QUEUED

        started = await client.post(f"{base}/read", headers=processor)
        assert started.status_code == 200, started.text
        assert started.json()["state"] == QUEUED

        again = await client.post(f"{base}/read", headers=processor)
        assert again.status_code == 409
        assert again.json()["error"]["data"]["code"] == "reading_running"
    assert queued == [str(round_.id)]


async def test_nothing_unread_is_refused(
    db_session: AsyncSession, model: list[str], queued: list[str]
) -> None:
    from tests.conditions.test_lender_condition_settings import _clients

    loan_file, round_ = await _file_without_lender(db_session)
    await read_round(db_session, round_id=round_.id)
    client, _, processor = await _clients(db_session, loan_file)
    async with client:
        refused = await client.post(f"/api/v1/condition-rounds/{round_.id}/read", headers=processor)
        assert refused.status_code == 409
        assert refused.json()["error"]["data"]["code"] == "nothing_unread"
    assert queued == []


async def test_a_stalled_reading_can_be_read_again(
    db_session: AsyncSession, queued: list[str]
) -> None:
    from tests.conditions.test_lender_condition_settings import _clients

    loan_file, round_ = await _file_without_lender(db_session)
    round_.reading_run = {"state": READING, "at": _ago(30)}
    await db_session.flush()
    client, _, processor = await _clients(db_session, loan_file)
    async with client:
        got = await client.get(f"/api/v1/condition-rounds/{round_.id}/reading", headers=processor)
        assert (got.json()["state"], got.json()["error"]) == (FAILED, "stalled")
        again = await client.post(f"/api/v1/condition-rounds/{round_.id}/read", headers=processor)
        assert again.status_code == 200
    assert queued == [str(round_.id)]


async def test_a_refusing_broker_leaves_the_round_failed(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import conditions as conditions_api
    from tests.conditions.test_lender_condition_settings import _clients

    monkeypatch.setattr(conditions_api, "_enqueue_reading", lambda _rid: False)
    loan_file, round_ = await _file_without_lender(db_session)
    client, _, processor = await _clients(db_session, loan_file)
    async with client:
        got = await client.post(f"/api/v1/condition-rounds/{round_.id}/read", headers=processor)
        assert got.status_code == 200
        assert (got.json()["state"], got.json()["error"]) == (FAILED, "not_queued")


async def test_another_companys_round_is_404(db_session: AsyncSession, queued: list[str]) -> None:
    from app.models import Company
    from tests.conditions.test_lender_condition_settings import _clients
    from tests.models.conftest_helpers import make_loan_file

    _, round_ = await _file_without_lender(db_session)
    stranger_company = Company(name="Stranger", slug="stranger-lp952")
    db_session.add(stranger_company)
    await db_session.flush()
    stranger = await make_loan_file(db_session, company=stranger_company)
    client, _, processor = await _clients(db_session, stranger)
    async with client:
        base = f"/api/v1/condition-rounds/{round_.id}"
        assert (await client.get(f"{base}/reading", headers=processor)).status_code == 404
        assert (await client.post(f"{base}/read", headers=processor)).status_code == 404
    assert queued == []


# --------------------------------------------------------------------------------------------- #
# Never re-read a read or confirmed condition
# --------------------------------------------------------------------------------------------- #


async def test_reading_again_reads_only_the_unread(
    db_session: AsyncSession, model: list[str]
) -> None:
    loan_file, round_ = await _file_without_lender(db_session)
    await read_round(db_session, round_id=round_.id)
    conditions = await _by_code(db_session, loan_file)
    kept = {code: c.reading for code, c in conditions.items() if code != "0006"}
    conditions["0006"].reading_status = ConditionReadingStatus.UNREAD
    conditions["0006"].reading = None
    await db_session.flush()

    outcome = await read_round(db_session, round_id=round_.id)
    assert outcome.condition_ids == [conditions["0006"].id]
    assert conditions["0006"].reading is not None
    assert all(conditions[code].reading == reading for code, reading in kept.items())
    # One model call carried only the one unread condition.
    assert '"code": "0006"' in model[-1] and '"code": "1228"' not in model[-1]


# --------------------------------------------------------------------------------------------- #
# The task's final failure is recorded
# --------------------------------------------------------------------------------------------- #


def test_an_exhausted_reading_marks_the_round_failed_with_the_error_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks import conditions as tasks

    marked: list[tuple[str, str]] = []

    async def _record(round_id: str, error: str) -> None:
        marked.append((round_id, error))

    monkeypatch.setattr(tasks, "_mark_read_failed", _record)
    tasks._read_exhausted("abc", TimeoutError("the lender's words must never travel"))
    assert marked == [("abc", "TimeoutError")]


async def test_import_through_the_route_marks_the_round_queued(
    db_session: AsyncSession, queued: list[str]
) -> None:
    """The import door marks queued too, so the panel shows "Reading" from the moment she imports."""
    from app.models.condition_round import ConditionRoundStatus, ConditionSourceKind
    from app.services.condition_rounds import SheetBytes, create_round_from_sheet
    from app.tasks.conditions import parse_round
    from tests.conditions.fixture_helpers import UWM_ROUND_1
    from tests.conditions.test_lender_condition_settings import _clients
    from tests.conditions.uwm_pdf_fixture import render_uwm_pdf

    loan_file, _ = await _file_without_lender(db_session)
    draft = await create_round_from_sheet(
        db_session,
        loan_file=loan_file,
        sheet=SheetBytes(
            content=render_uwm_pdf(UWM_ROUND_1), source_kind=ConditionSourceKind.PDF_UPLOAD
        ),
    )
    await db_session.flush()
    await parse_round(db_session, draft.id)
    await db_session.refresh(draft)
    assert draft.status is ConditionRoundStatus.DRAFT
    client, _, processor = await _clients(db_session, loan_file)
    async with client:
        imported = await client.post(
            f"/api/v1/condition-rounds/{draft.id}/import", json={}, headers=processor
        )
        assert imported.status_code == 200, imported.text
    refreshed = await db_session.get(ConditionRound, draft.id)
    assert refreshed is not None and refreshed.reading_run is not None
    assert refreshed.reading_run["state"] == QUEUED
    assert queued == [str(draft.id)]

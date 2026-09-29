"""LP-919's "Done when", through the database, with the model MOCKED (`reading_fixture`).

Round 1 comes in as a PDF, parsed by the task body and imported by the service, because a paste has no
letter header and 6178's push-back reads the letter's Must Not Close Before.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from app.ai.client import AIClientError
from app.models import Company
from app.models.condition import Condition, ConditionReadingSource, ConditionReadingStatus
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_round import ConditionRound, ConditionSourceKind
from app.models.lender_condition_code import LenderConditionCode
from app.models.loan_file import LoanFile
from app.scripts.seed_lender_codes import seed_lender_codes
from app.services import condition_reading
from app.services.condition_import import import_round
from app.services.condition_reading import read_round
from app.services.condition_rounds import SheetBytes, create_round_from_sheet
from app.tasks.conditions import parse_round
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.fixture_helpers import UWM_ROUND_1
from tests.conditions.reading_fixture import fake_complete
from tests.conditions.uwm_pdf_fixture import render_uwm_pdf
from tests.models.conftest_helpers import make_lender, make_loan_file


async def _file_with_round(
    db: AsyncSession, fixture: str = UWM_ROUND_1
) -> tuple[LoanFile, ConditionRound]:
    company = Company(name="Reading", slug=f"reading-{uuid4().hex[:6]}")
    db.add(company)
    await db.flush()
    lender = await make_lender(db, company=company)
    lender.canonical_lender_key = "uwm"
    loan_file = await make_loan_file(db, company=company)
    loan_file.lender_id = lender.id
    await db.flush()
    await seed_lender_codes(db)
    round_ = await create_round_from_sheet(
        db,
        loan_file=loan_file,
        sheet=SheetBytes(
            content=render_uwm_pdf(fixture), source_kind=ConditionSourceKind.PDF_UPLOAD
        ),
    )
    await db.flush()
    await parse_round(db, round_.id)
    await db.refresh(round_)
    await import_round(db, round_=round_)
    return loan_file, round_


async def _by_code(db: AsyncSession, loan_file: LoanFile) -> dict[str, Condition]:
    rows = (
        await db.execute(select(Condition).where(Condition.loan_file_id == loan_file.id))
    ).scalars()
    return {row.lender_code or "": row for row in rows}


def _performers(condition: Condition) -> list[list[str]]:
    assert condition.reading is not None
    return [item["performers"] for item in condition.reading["items"]]


@pytest.fixture
def model_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(condition_reading, "complete", fake_complete(calls))
    return calls


async def test_round_one_reads_as_the_plan_says(
    db_session: AsyncSession, model_calls: list[str]
) -> None:
    loan_file, round_ = await _file_with_round(db_session)

    outcome = await read_round(db_session, round_id=round_.id)
    by_code = await _by_code(db_session, loan_file)

    # ONE call for the whole round, not one per condition.
    assert len(model_calls) == 1
    assert outcome.read == 11 and outcome.used_ai and not outcome.fell_back

    # 6637 becomes three items across the borrower and title/escrow.
    assert _performers(by_code["6637"]) == [["borrower"], ["title"], ["borrower"]]
    # The item names the lender's amount, filled by code from the text (S3-01's "Source of the $2,850.00").
    assert by_code["6637"].reading["items"][0]["name"] == "Source of the $2,850.00"  # type: ignore[index]
    assert by_code["6637"].reading_status is ConditionReadingStatus.READY
    assert by_code["6637"].reading_confidence == Decimal("0.93")
    assert by_code["6637"].reading["type_id"] == "AS-04"  # type: ignore[index]

    # 0132 becomes three items across the LO, the borrower and the attorney, and 0.64 is below the bar.
    assert _performers(by_code["0132"]) == [["borrower", "lo"], ["lo"], ["attorney"]]
    assert by_code["0132"].reading_status is ConditionReadingStatus.NEEDS_CONFIRMATION

    # 7086's shortfall is computed by code; the model's own "$27,148.22" is not the lender's and is dropped.
    reading_7086 = by_code["7086"].reading or {}
    assert reading_7086["figures"]["shortfall"] == {
        "required": "38210.40",
        "verified": "11062.18",
        "amount": "27148.22",
    }
    assert reading_7086["summary"] == (
        "Show $27,148.22 more in assets (required $38,210.40, verified $11,062.18)"
    )
    assert reading_7086["items"][0]["specifics"]["amounts"] == ["$38,210.40", "$11,062.18"]

    # 6178 may not apply: the letter says must not close before the date the policy starts.
    assert by_code["6178"].reading["push_back"] == {  # type: ignore[index]
        "must_not_close_before": "2026-09-30",
        "policy_starts": "2026-09-30",
    }
    # The underwriter's "Not in Upload" note is given its meaning by code.
    assert by_code["6637"].reading["note_meaning"] == (  # type: ignore[index]
        "The lender did not find it in the last upload — asked again below."
    )

    # Every condition read, each with an event; the round records one call's cost.
    events = await db_session.scalar(
        select(func.count()).where(
            ConditionEvent.round_id == round_.id,
            ConditionEvent.kind == ConditionEventKind.CONDITION_READ,
        )
    )
    assert events == 11
    assert round_.reading_run is not None and round_.reading_run["cost_estimate"] > 0
    assert round_.reading_run["model"] and round_.reading_run["used_ai"] is True


async def test_the_model_never_sees_the_loan_snapshot(
    db_session: AsyncSession, model_calls: list[str]
) -> None:
    _, round_ = await _file_with_round(db_session)
    await read_round(db_session, round_id=round_.id)
    sent: Any = __import__("json").loads(model_calls[0])
    assert set(sent) == {"file", "conditions"}
    assert set(sent["file"]) <= {
        "borrowers",
        "lender",
        "must_not_close_before",
        "earnest_money",
        "loan_purpose",
    }
    assert all(
        set(entry) <= {"ref", "code", "text", "notes", "type"} for entry in sent["conditions"]
    )


async def test_without_the_ai_the_library_plan_stands_and_asks_her_to_confirm(
    db_session: AsyncSession, model_calls: list[str]
) -> None:
    loan_file, round_ = await _file_with_round(db_session)
    outcome = await read_round(db_session, round_id=round_.id, use_ai=False)
    by_code = await _by_code(db_session, loan_file)

    assert model_calls == [] and not outcome.used_ai
    assert all(
        c.reading_status is ConditionReadingStatus.NEEDS_CONFIRMATION for c in by_code.values()
    )
    assert all(c.reading_source is ConditionReadingSource.LIBRARY for c in by_code.values())
    # The library alone still splits 6637 and still computes 7086's shortfall.
    assert _performers(by_code["6637"]) == [["borrower"], ["title"], ["borrower"]]
    assert by_code["7086"].reading["figures"]["shortfall"]["amount"] == "27148.22"  # type: ignore[index]


async def test_a_failing_model_never_sticks_the_round(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _boom(**_: Any) -> Any:
        raise AIClientError("down")

    monkeypatch.setattr(condition_reading, "complete", _boom)
    loan_file, round_ = await _file_with_round(db_session)
    outcome = await read_round(db_session, round_id=round_.id)

    assert outcome.fell_back and outcome.read == 11
    assert round_.reading_run is not None and round_.reading_run["error"] == "AIClientError"
    by_code = await _by_code(db_session, loan_file)
    assert all(
        c.reading_status is ConditionReadingStatus.NEEDS_CONFIRMATION for c in by_code.values()
    )


async def test_the_page_break_sheets_lender_items_are_the_lenders(
    db_session: AsyncSession, model_calls: list[str]
) -> None:
    """1760 (desk review ordered) and the three 0571 rows (change of circumstance) are "the lender is
    doing it" — from the library and the lender's own heading, not from the model."""
    loan_file, round_ = await _file_with_round(db_session, "uwm_master_pagebreak.txt")
    await read_round(db_session, round_id=round_.id)
    rows = (
        (await db_session.execute(select(Condition).where(Condition.loan_file_id == loan_file.id)))
        .scalars()
        .all()
    )
    lender_rows = [row for row in rows if row.lender_code in {"1760", "0571"}]
    assert sorted(row.lender_code or "" for row in lender_rows) == ["0571", "0571", "0571", "1760"]
    assert all((row.reading or {}).get("lender_doing_it") for row in lender_rows)


async def test_a_confirmed_answer_for_the_code_is_used_next_time(
    db_session: AsyncSession, model_calls: list[str]
) -> None:
    loan_file, round_ = await _file_with_round(db_session)
    code_row = await db_session.scalar(
        select(LenderConditionCode).where(
            LenderConditionCode.lender_id == loan_file.lender_id, LenderConditionCode.code == "0132"
        )
    )
    assert code_row is not None
    code_row.confirmed_reading = {
        "items": [
            {"key": "disclosure", "name": "Re-signed disclosure", "performers": ["borrower", "lo"]},
            {"key": "wire_instructions", "name": "Wire instructions", "performers": ["attorney"]},
        ]
    }
    await db_session.flush()

    await read_round(db_session, round_id=round_.id)
    condition = (await _by_code(db_session, loan_file))["0132"]
    assert condition.reading_status is ConditionReadingStatus.CONFIRMED
    assert _performers(condition) == [["borrower", "lo"], ["attorney"]]
    # And it was not sent to the model at all.
    assert '"code": "0132"' not in model_calls[0]


async def test_a_condition_already_read_is_not_read_again(
    db_session: AsyncSession, model_calls: list[str]
) -> None:
    _, round_ = await _file_with_round(db_session)
    await read_round(db_session, round_id=round_.id)
    second = await read_round(db_session, round_id=round_.id)
    assert second.read == 0 and len(model_calls) == 1


# --------------------------------------------------------------------------------------------- #
# S3-03 through the API
# --------------------------------------------------------------------------------------------- #


async def _client_for(db: AsyncSession, loan_file: LoanFile) -> tuple[Any, dict[str, str]]:
    from app.core.database import get_db
    from app.core.jwt import create_access_token
    from app.core.security import hash_password
    from app.main import app
    from app.models import User, UserRole
    from httpx import ASGITransport, AsyncClient

    user = User(
        company_id=loan_file.company_id,
        email=f"p-{uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("irrelevant"),
        first_name="Priya",
        last_name="Raman",
        role=UserRole.PROCESSOR,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    async def _db() -> Any:
        yield db

    app.dependency_overrides[get_db] = _db
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    return client, {"Authorization": f"Bearer {create_access_token(user.id)}"}


async def test_confirming_0132_saves_her_split_for_the_code_without_specifics(
    db_session: AsyncSession, model_calls: list[str]
) -> None:
    from app.core.database import get_db
    from app.main import app

    loan_file, round_ = await _file_with_round(db_session)
    await read_round(db_session, round_id=round_.id)
    condition = (await _by_code(db_session, loan_file))["0132"]
    client, auth = await _client_for(db_session, loan_file)
    try:
        async with client:
            response = await client.post(
                f"/api/v1/conditions/{condition.id}/reading/confirm",
                headers=auth,
                json={
                    "items": [
                        {
                            "key": "disclosure",
                            "name": "Re-sign the disclosure",
                            "performers": ["borrower", "lo"],
                        },
                        {
                            "key": "attorney",
                            "name": "Choose an approved attorney",
                            "performers": ["lo"],
                        },
                        {
                            "key": "wire_instructions",
                            "name": "Matching wire instructions",
                            "performers": ["attorney"],
                        },
                    ]
                },
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["reading_status"] == "confirmed"
            assert [i["performers"] for i in body["reading"]["items"]] == [
                ["borrower", "lo"],
                ["lo"],
                ["attorney"],
            ]

            refused = await client.post(
                f"/api/v1/conditions/{condition.id}/reading/confirm",
                headers=auth,
                json={"items": [{"name": "  ", "performers": ["lo"]}]},
            )
            assert refused.status_code == 409
    finally:
        app.dependency_overrides.pop(get_db, None)

    code_row = await db_session.scalar(
        select(LenderConditionCode).where(
            LenderConditionCode.lender_id == loan_file.lender_id, LenderConditionCode.code == "0132"
        )
    )
    assert code_row is not None and code_row.confirmed_reading is not None
    saved_items = code_row.confirmed_reading["items"]
    assert saved_items[0]["name"] == "Re-sign the disclosure"
    assert all(set(item) == {"key", "name", "performers", "option"} for item in saved_items)
    events = await db_session.scalar(
        select(func.count()).where(
            ConditionEvent.condition_id == condition.id,
            ConditionEvent.kind == ConditionEventKind.CONDITION_READING_CONFIRMED,
        )
    )
    assert events == 1


async def test_the_library_default_confirms_the_types_items(
    db_session: AsyncSession, model_calls: list[str]
) -> None:
    from app.core.database import get_db
    from app.main import app

    loan_file, round_ = await _file_with_round(db_session)
    await read_round(db_session, round_id=round_.id)
    condition = (await _by_code(db_session, loan_file))["0132"]
    client, auth = await _client_for(db_session, loan_file)
    try:
        async with client:
            response = await client.post(
                f"/api/v1/conditions/{condition.id}/reading/library-default", headers=auth
            )
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reading_status"] == "confirmed"
    assert [i["key"] for i in body["reading"]["items"]] == [
        "disclosure",
        "attorney",
        "wire_instructions",
    ]
    assert (
        body["library_type"]["label"] == "DI-01 State attorney and insurance preference disclosure"
    )

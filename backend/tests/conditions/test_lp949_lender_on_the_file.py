"""LP-949 — the lender on the file: detected from the sheet, set only when she confirms (items 1 and 10b
of the 2026-09-30 staging trial). LP-965 — and nothing about a condition's TYPE comes from the lender any
more: the reading chooses it, fresh every time (ADR-418).

The scenario is LF-DH8V's: a UWM sheet imported onto a file with NO lender. The fixture sheet carries the
same six codes (0006, 0007, 1228, 1582, 1947, 6378) and more.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest
from app.ai.client import AICompletion
from app.conditions.lender_detect import detect_lender
from app.models import Company
from app.models.condition import Condition, ConditionReadingStatus
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_item import ConditionItem
from app.models.condition_round import ConditionRound, ConditionSheetFormat, ConditionSourceKind
from app.models.lender import Lender
from app.models.lender_condition_code import LenderConditionCode
from app.models.loan_file import LoanFile
from app.services import condition_reading
from app.services.condition_import import import_round
from app.services.condition_lender import (
    LenderRefused,
    decline_suggestion,
    file_lender_payload,
    lender_suggestion,
    set_file_lender,
    unread_round_to_read,
)
from app.services.condition_plan import build_plan
from app.services.condition_reading import _ai_input, chosen_type, read_round
from app.services.condition_rounds import SheetBytes, create_round_from_sheet
from app.tasks.conditions import parse_round
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.fixture_helpers import UWM_ROUND_1
from tests.conditions.reading_fixture import canned_response, fake_complete
from tests.conditions.uwm_pdf_fixture import render_uwm_pdf
from tests.models.conftest_helpers import make_lender, make_loan_file

#: The type the (mocked) reading chooses for each fixture code: the one UWM's old shipped map gave it.
UWM_TYPES = {"0006": "IV-01", "0007": "IV-03", "1228": "PA-03", "1947": "TI-03", "6378": "TI-04"}


async def _company(db: AsyncSession) -> Company:
    company = Company(name="Lender on file", slug=f"lof-{uuid4().hex[:6]}")
    db.add(company)
    await db.flush()
    return company


async def _file_without_lender(db: AsyncSession) -> tuple[LoanFile, ConditionRound]:
    """LF-DH8V's state: a UWM sheet imported onto a file that names no lender."""
    company = await _company(db)
    loan_file = await make_loan_file(db, company=company)
    assert loan_file.lender_id is None
    round_ = await create_round_from_sheet(
        db,
        loan_file=loan_file,
        sheet=SheetBytes(
            content=render_uwm_pdf(UWM_ROUND_1), source_kind=ConditionSourceKind.PDF_UPLOAD
        ),
    )
    await db.flush()
    await parse_round(db, round_.id)
    await db.refresh(round_)
    await import_round(db, round_=round_)
    return loan_file, round_


async def _by_code(db: AsyncSession, loan_file: LoanFile) -> dict[str, Condition]:
    rows = await db.scalars(select(Condition).where(Condition.loan_file_id == loan_file.id))
    return {row.lender_code or "": row for row in rows}


async def _events(db: AsyncSession, loan_file: LoanFile, kind: ConditionEventKind) -> list[Any]:
    return list(
        await db.scalars(
            select(ConditionEvent).where(
                ConditionEvent.loan_file_id == loan_file.id, ConditionEvent.kind == kind
            )
        )
    )


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(condition_reading, "complete", fake_complete(calls))
    return calls


# --------------------------------------------------------------------------------------------- #
# Detection (pure)
# --------------------------------------------------------------------------------------------- #


def test_the_reader_names_the_lender() -> None:
    found = detect_lender(ConditionSheetFormat.UWM_APPROVAL_LETTER, None)
    assert found is not None and (found.key, found.source) == ("uwm", "reader")
    assert found.name == "United Wholesale Mortgage"
    champions = detect_lender(ConditionSheetFormat.CHAMPIONS_CERTIFICATE, None)
    assert champions is not None and champions.key == "champions"


def test_the_mortgagee_clause_then_the_header_name_the_lender() -> None:
    clause = detect_lender(
        ConditionSheetFormat.GENERIC,
        {"mortgagee_clause": "United  Wholesale Mortgage ISAOA, ATIMA PO BOX 202175"},
    )
    assert clause is not None and (clause.key, clause.source) == ("uwm", "mortgagee_clause")
    header = detect_lender(
        ConditionSheetFormat.PASTED_TEXT, {"lender_team": {"Lender": "Champions Funding, LLC"}}
    )
    assert header is not None and (header.key, header.source) == ("champions", "header")


def test_a_sheet_that_names_no_lender_or_two_names_none() -> None:
    assert detect_lender(ConditionSheetFormat.GENERIC, None) is None
    assert (
        detect_lender(ConditionSheetFormat.GENERIC, {"mortgagee_clause": "Acme Bank ISAOA"}) is None
    )
    both = {"lender_team": ["United Wholesale Mortgage", "Champions Funding"]}
    assert detect_lender(ConditionSheetFormat.GENERIC, both) is None


# --------------------------------------------------------------------------------------------- #
# The suggestion, and her answer
# --------------------------------------------------------------------------------------------- #


async def test_a_file_with_no_lender_imports_untyped_and_is_offered_the_sheets_lender(
    db_session: AsyncSession,
) -> None:
    loan_file, round_ = await _file_without_lender(db_session)
    conditions = await _by_code(db_session, loan_file)
    assert set(UWM_TYPES) <= set(conditions)
    assert all(c.canonical_type_id is None for c in conditions.values())

    payload = await file_lender_payload(db_session, loan_file=loan_file)
    assert payload["lender"] is None
    assert payload["suggestion"] == {
        "round_id": round_.id,
        "key": "uwm",
        "name": "United Wholesale Mortgage",
        "source": "reader",
        "lender_exists": False,
    }


async def test_nothing_is_set_until_she_confirms(db_session: AsyncSession) -> None:
    loan_file, _ = await _file_without_lender(db_session)
    await file_lender_payload(db_session, loan_file=loan_file)
    await lender_suggestion(db_session, loan_file=loan_file)
    await db_session.refresh(loan_file)
    assert loan_file.lender_id is None
    lenders = await db_session.scalar(
        select(func.count(Lender.id)).where(Lender.company_id == loan_file.company_id)
    )
    assert lenders == 0


async def test_confirming_adds_the_lender_and_moves_the_file_to_it_typing_nothing(
    db_session: AsyncSession,
) -> None:
    loan_file, round_ = await _file_without_lender(db_session)
    await set_file_lender(
        db_session, loan_file=loan_file, lender_key="uwm", lender_id=None, actor_user_id=None
    )

    lender = await db_session.get(Lender, loan_file.lender_id)
    assert lender is not None and lender.canonical_lender_key == "uwm"
    assert lender.company_id == loan_file.company_id
    conditions = await _by_code(db_session, loan_file)
    assert all(c.lender_id == lender.id for c in conditions.values())
    await db_session.refresh(round_)
    assert round_.lender_id == lender.id

    # LP-965 — no code map: nothing typed, nothing seeded, no typing events.
    assert all(c.canonical_type_id is None for c in conditions.values())
    rows = await db_session.scalar(
        select(func.count(LenderConditionCode.id)).where(LenderConditionCode.lender_id == lender.id)
    )
    assert rows == 0
    assert await _events(db_session, loan_file, ConditionEventKind.CONDITION_TYPED) == []
    assert (await file_lender_payload(db_session, loan_file=loan_file))["suggestion"] is None


async def test_her_companys_lender_is_reused_and_another_companys_is_refused(
    db_session: AsyncSession,
) -> None:
    loan_file, _ = await _file_without_lender(db_session)
    company = await db_session.get(Company, loan_file.company_id)
    assert company is not None
    mine = await make_lender(db_session, company=company, name="UWM")
    mine.canonical_lender_key = "uwm"
    other = await make_lender(db_session, company=await _company(db_session), name="Elsewhere")
    await db_session.flush()

    assert (await lender_suggestion(db_session, loan_file=loan_file)) is not None
    with pytest.raises(LenderRefused):
        await set_file_lender(
            db_session, loan_file=loan_file, lender_key=None, lender_id=other.id, actor_user_id=None
        )
    with pytest.raises(LenderRefused):
        await set_file_lender(
            db_session, loan_file=loan_file, lender_key="uwm", lender_id=mine.id, actor_user_id=None
        )
    await set_file_lender(
        db_session, loan_file=loan_file, lender_key="uwm", lender_id=None, actor_user_id=None
    )
    assert loan_file.lender_id == mine.id
    count = await db_session.scalar(
        select(func.count(Lender.id)).where(Lender.company_id == loan_file.company_id)
    )
    assert count == 1


async def test_a_same_named_lender_without_the_key_is_used_and_the_key_is_not_guessed(
    db_session: AsyncSession,
) -> None:
    loan_file, _ = await _file_without_lender(db_session)
    company = await db_session.get(Company, loan_file.company_id)
    assert company is not None
    named = await make_lender(db_session, company=company, name="United Wholesale Mortgage")
    assert named.canonical_lender_key is None

    suggestion = await lender_suggestion(db_session, loan_file=loan_file)
    assert suggestion is not None and suggestion.lender_id == named.id
    await set_file_lender(
        db_session, loan_file=loan_file, lender_key="uwm", lender_id=None, actor_user_id=None
    )
    assert loan_file.lender_id == named.id
    await db_session.refresh(named)
    assert named.canonical_lender_key is None
    payload = await file_lender_payload(db_session, loan_file=loan_file)
    assert payload["lender"] == {"id": named.id, "name": "United Wholesale Mortgage"}


async def test_declining_hides_the_suggestion_and_records_it(db_session: AsyncSession) -> None:
    loan_file, round_ = await _file_without_lender(db_session)
    with pytest.raises(LenderRefused):
        await decline_suggestion(
            db_session, loan_file=loan_file, round_id=uuid4(), actor_user_id=None
        )
    await decline_suggestion(
        db_session, loan_file=loan_file, round_id=round_.id, actor_user_id=None
    )
    assert (await lender_suggestion(db_session, loan_file=loan_file)) is None
    declined = await _events(db_session, loan_file, ConditionEventKind.ROUND_LENDER_DECLINED)
    assert [(e.round_id, e.condition_id, e.detail["key"]) for e in declined] == [
        (round_.id, None, "uwm")
    ]
    assert loan_file.lender_id is None


# --------------------------------------------------------------------------------------------- #
# LP-965 — the type comes from the reading, fresh every time
# --------------------------------------------------------------------------------------------- #


def _no_type_model(calls: list[str]):  # type: ignore[no-untyped-def]
    """The shared mock with every `library_type` taken out: a model that recognises nothing."""

    async def _complete(**kwargs: Any) -> AICompletion:
        content = kwargs["messages"][0]["content"]
        calls.append(content)
        answer = json.loads(canned_response(content))
        for entry in answer["conditions"]:
            entry.pop("library_type", None)
        return AICompletion(
            text=json.dumps(answer),
            input_tokens=1200,
            output_tokens=900,
            model=kwargs["model"],
            stop_reason="end_turn",
            cache_read_tokens=0,
            cache_write_tokens=0,
        )

    return _complete


async def test_the_reading_types_each_condition_with_no_lender_and_0007_waits_on_1228(
    db_session: AsyncSession, model: list[str]
) -> None:
    """A lender is no longer needed for a type: the reading chooses it."""
    loan_file, round_ = await _file_without_lender(db_session)
    assert await unread_round_to_read(db_session, loan_file_id=loan_file.id) == round_.id
    await read_round(db_session, round_id=round_.id)
    await build_plan(db_session, round_id=round_.id)

    conditions = await _by_code(db_session, loan_file)
    assert {code: conditions[code].canonical_type_id for code in UWM_TYPES} == UWM_TYPES
    reading = conditions["1228"].reading
    assert reading is not None and reading["type_id"] == "PA-03"
    items = list(
        await db_session.scalars(
            select(ConditionItem).where(ConditionItem.condition_id == conditions["0007"].id)
        )
    )
    assert items and all(i.waits_on_condition_id == conditions["1228"].id for i in items)
    assert await unread_round_to_read(db_session, loan_file_id=loan_file.id) is None


async def test_a_model_that_chooses_no_type_leaves_them_untyped_and_nothing_waits(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The positive control for the test above: the type and the wait come from the model's choice."""
    calls: list[str] = []
    monkeypatch.setattr(condition_reading, "complete", _no_type_model(calls))
    loan_file, round_ = await _file_without_lender(db_session)
    await read_round(db_session, round_id=round_.id)
    await build_plan(db_session, round_id=round_.id)

    conditions = await _by_code(db_session, loan_file)
    assert calls
    assert all(c.canonical_type_id is None for c in conditions.values())
    items = list(
        await db_session.scalars(
            select(ConditionItem).where(ConditionItem.condition_id == conditions["0007"].id)
        )
    )
    assert items and all(i.waits_on_condition_id is None for i in items)


def test_only_a_real_library_type_is_taken() -> None:
    chosen = chosen_type({"library_type": "IV-01"})
    assert chosen is not None and chosen.id == "IV-01"
    assert chosen_type({"library_type": "ZZ-99"}) is None
    assert chosen_type({"library_type": None}) is None
    assert chosen_type(None) is None


async def test_a_fresh_reading_replaces_an_earlier_type(
    db_session: AsyncSession, model: list[str]
) -> None:
    """Nothing typed before the reading survives it: the AI's choice is the type."""
    loan_file, round_ = await _file_without_lender(db_session)
    conditions = await _by_code(db_session, loan_file)
    conditions["1228"].canonical_type_id = "PA-04"
    await db_session.flush()

    await read_round(db_session, round_id=round_.id)
    assert conditions["1228"].canonical_type_id == "PA-03"


async def test_nothing_is_remembered_per_lender_code(
    db_session: AsyncSession, model: list[str]
) -> None:
    """Import, the lender, and the reading together write no `lender_condition_codes` row."""
    loan_file, round_ = await _file_without_lender(db_session)
    await set_file_lender(
        db_session, loan_file=loan_file, lender_key="uwm", lender_id=None, actor_user_id=None
    )
    await read_round(db_session, round_id=round_.id)
    rows = await db_session.scalar(select(func.count(LenderConditionCode.id)))
    assert rows == 0


def test_the_whole_library_with_its_items_goes_to_the_model() -> None:
    from app.conditions.library import load_library

    invoice = load_library().get("IV-01")
    assert invoice is not None
    sent = json.loads(
        _ai_input([(1, Condition(verbatim_text="x", lender_code="9", underwriter_notes=[]))], {})
    )
    by_id = {entry["id"]: entry for entry in sent["library"]}
    assert by_id["IV-01"]["name"] == invoice.name
    assert [item["key"] for item in by_id["IV-01"]["items"]] == [i.key for i in invoice.items]
    assert "type" not in sent["conditions"][0]


async def test_a_condition_already_read_is_not_read_again(
    db_session: AsyncSession, model: list[str]
) -> None:
    loan_file, round_ = await _file_without_lender(db_session)
    await read_round(db_session, round_id=round_.id)
    before = {code: c.reading for code, c in (await _by_code(db_session, loan_file)).items()}

    await set_file_lender(
        db_session, loan_file=loan_file, lender_key="uwm", lender_id=None, actor_user_id=None
    )
    assert await unread_round_to_read(db_session, loan_file_id=loan_file.id) is None
    after = await _by_code(db_session, loan_file)
    assert all(after[code].reading == before[code] for code in before)
    assert all(c.reading_status is not ConditionReadingStatus.UNREAD for c in after.values())


# --------------------------------------------------------------------------------------------- #
# The routes
# --------------------------------------------------------------------------------------------- #


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


async def test_the_routes_offer_set_and_queue_the_reading(
    db_session: AsyncSession, queued: list[str]
) -> None:
    from tests.conditions.test_lender_condition_settings import _clients

    loan_file, round_ = await _file_without_lender(db_session)
    client, _, processor = await _clients(db_session, loan_file)
    base = f"/api/v1/loan-files/{loan_file.id}/conditions/lender"
    async with client:
        got = await client.get(base, headers=processor)
        assert got.status_code == 200
        assert got.json()["suggestion"]["key"] == "uwm"
        assert got.json()["lender"] is None

        both = await client.put(
            base, json={"lender_key": "uwm", "lender_id": str(uuid4())}, headers=processor
        )
        assert both.status_code == 409

        put = await client.put(base, json={"lender_key": "uwm"}, headers=processor)
        assert put.status_code == 200, put.text
        assert put.json()["lender"]["name"] == "United Wholesale Mortgage"
        assert "has_code_map" not in put.json()["lender"]
        assert put.json()["suggestion"] is None
    assert queued == [str(round_.id)]


async def test_another_companys_file_is_404(db_session: AsyncSession, queued: list[str]) -> None:
    from tests.conditions.test_lender_condition_settings import _clients

    loan_file, round_ = await _file_without_lender(db_session)
    stranger_file = await make_loan_file(db_session, company=await _company(db_session))
    client, _, processor = await _clients(db_session, stranger_file)
    base = f"/api/v1/loan-files/{loan_file.id}/conditions/lender"
    async with client:
        assert (await client.get(base, headers=processor)).status_code == 404
        assert (
            await client.put(base, json={"lender_key": "uwm"}, headers=processor)
        ).status_code == 404
        declined = await client.post(
            f"{base}/decline", json={"round_id": str(round_.id)}, headers=processor
        )
        assert declined.status_code == 404
    await db_session.refresh(loan_file)
    assert loan_file.lender_id is None and queued == []


async def test_decline_route_and_a_lender_patch_both_work(
    db_session: AsyncSession, queued: list[str]
) -> None:
    from tests.conditions.test_lender_condition_settings import _clients

    loan_file, round_ = await _file_without_lender(db_session)
    company = await db_session.get(Company, loan_file.company_id)
    assert company is not None
    lender = await make_lender(db_session, company=company, name="UWM")
    lender.canonical_lender_key = "uwm"
    await db_session.flush()
    client, _, processor = await _clients(db_session, loan_file)
    base = f"/api/v1/loan-files/{loan_file.id}/conditions/lender"
    async with client:
        declined = await client.post(
            f"{base}/decline", json={"round_id": str(round_.id)}, headers=processor
        )
        assert declined.status_code == 200
        assert declined.json()["suggestion"] is None
        again = await client.post(
            f"{base}/decline", json={"round_id": str(round_.id)}, headers=processor
        )
        assert again.status_code == 409

        # THE OVERVIEW EDITOR'S DOOR: the conditions follow the lender, and the same reading is queued.
        patched = await client.patch(
            f"/api/v1/loan-files/{loan_file.id}",
            json={"lender_id": str(lender.id)},
            headers=processor,
        )
        assert patched.status_code == 200, patched.text
    conditions = await _by_code(db_session, loan_file)
    assert conditions["1228"].lender_id == lender.id
    assert conditions["1228"].canonical_type_id is None  # typed by its reading, not the lender
    assert queued == [str(round_.id)]


def test_typed_as_is_the_librarys_label_or_nothing() -> None:
    """The history's `typed_as` is drawn from the library, never from what `detail` holds."""
    from datetime import UTC, datetime

    from app.conditions.library import load_library
    from app.schemas.condition import ConditionEventPublic

    def project(kind: ConditionEventKind, type_id: object) -> str | None:
        event = ConditionEvent(
            kind=kind, detail={"type_id": type_id}, occurred_at=datetime.now(UTC)
        )
        return ConditionEventPublic.from_model(event).typed_as

    inspection = load_library().get("PA-03")
    assert inspection is not None
    assert project(ConditionEventKind.CONDITION_TYPED, "PA-03") == inspection.label
    assert project(ConditionEventKind.CONDITION_TYPED, "Alex Rivera") is None
    assert project(ConditionEventKind.CONDITION_READ, "PA-03") is None

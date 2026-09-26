"""Stage 1's acceptance scenario, through the API (spec §8, LP-909 §5).

Every step here already has a unit test somewhere — the readers, the import, the enrich, the split.
What those do not prove is that the DOORS compose: that a PDF uploaded over HTTP, parsed, imported,
followed by a paste over HTTP, imported, then enriched over HTTP, leaves the file in the state §8
names. That is the property this module exists for, so every step goes through a route, and the only
things called directly are the two Celery task bodies and the AI client:

- `parse_round` / `split_round` rather than the Celery wrappers, for the reason
  `tests/tasks/test_condition_parse.py` gives: `task_session()` opens its own engine, and this suite
  isolates each test in a transaction that is never committed, so a real worker would see nothing.
  `.delay` is replaced with a recorder, so the test also asserts the route ENQUEUED the round.
- `condition_split.complete` is mocked for step 6, as §8 says ("mocked in CI").

⚠️ STEP 8 IS NOT HERE, AND CANNOT BE. "The real-sheet smoke test passes on the product owner's
machine" is `tests/conditions/test_real_sheets_local.py`, which skips without the real sheets. A
green run of this module says nothing about step 8.

⚠️ ASSERTIONS ARE ON WHAT §8 NAMES, NOT A CENSUS. The events test in this directory failed once on a
correct implementation because it pinned an exact event list; here each step asserts §8's own
numbers and relations ("11 `CONDITION_CREATED` events", "one `ROUND_ENRICHED` event") and leaves the
rest of the history free to grow.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import date
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from app.ai.client import AICompletion
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.main import app
from app.models import Company, User, UserRole
from app.models.condition import Condition, ConditionLenderStatus, ConditionPrepStatus
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.lender_condition_code import LenderConditionCode
from app.models.loan_file import LoanFile
from app.services import condition_split as split_module
from app.services.loan_files import create_loan_file
from app.tasks import conditions as task_module
from app.tasks.conditions import parse_round, split_round
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.champions_fixture import build_champions_pdf
from tests.conditions.fixture_helpers import (
    UWM_PAGEBREAK,
    UWM_ROUND_1,
    UWM_ROUND_2,
    portal_excerpt,
)
from tests.conditions.test_condition_split import ROUND_2_TEXTS, UNSTRUCTURED
from tests.conditions.uwm_pdf_fixture import render_uwm_pdf
from tests.models.conftest_helpers import make_lender

API = "/api/v1"


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """Shadows the root fixture so the request shares this test's session (see LP-905 §1)."""

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    """What the routes handed to Celery, by task — recorded rather than sent."""
    seen: dict[str, list[str]] = {"parse": [], "split": []}
    monkeypatch.setattr(
        task_module.parse_condition_round, "delay", lambda round_id: seen["parse"].append(round_id)
    )
    monkeypatch.setattr(
        task_module.split_condition_round, "delay", lambda round_id: seen["split"].append(round_id)
    )
    return seen


async def _company_user(db: AsyncSession, *, slug: str) -> tuple[Company, dict[str, str]]:
    company = Company(name=slug.title(), slug=slug)
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id,
        email=f"processor@{slug}.com",
        hashed_password=hash_password("irrelevant"),
        first_name="Test",
        last_name="Processor",
        role=UserRole.PROCESSOR,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return company, {"Authorization": f"Bearer {create_access_token(user.id)}"}


async def _uwm_file(db: AsyncSession, company: Company) -> LoanFile:
    """A file whose lender is UWM, so import step 4 exercises the code map rather than skipping it."""
    loan_file = await create_loan_file(db, company_id=company.id)
    lender = await make_lender(db, company=company, name="UWM")
    loan_file.lender_id = lender.id
    await db.flush()
    return loan_file


async def _upload(
    client: AsyncClient,
    auth: dict[str, str],
    loan_file_id: UUID,
    pdf: bytes,
    *,
    enqueued: dict[str, list[str]],
    db: AsyncSession,
) -> dict[str, Any]:
    """POST the PDF, assert it was enqueued, run the parse body, and return the round as served."""
    response = await client.post(
        f"{API}/loan-files/{loan_file_id}/condition-rounds/uploads",
        files={"file": ("sheet.pdf", pdf, "application/pdf")},
        headers=auth,
    )
    assert response.status_code == 202, response.text
    round_id = response.json()["id"]
    assert response.json()["status"] == "parsing"
    assert enqueued["parse"][-1] == round_id, "the upload door must hand the round to the worker"

    await parse_round(db, UUID(round_id))
    return await _get_round(client, auth, round_id)


async def _get_round(client: AsyncClient, auth: dict[str, str], round_id: str) -> dict[str, Any]:
    response = await client.get(f"{API}/condition-rounds/{round_id}", headers=auth)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def _import(client: AsyncClient, auth: dict[str, str], round_id: str) -> dict[str, Any]:
    response = await client.post(f"{API}/condition-rounds/{round_id}/import", headers=auth)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def _conditions(
    client: AsyncClient, auth: dict[str, str], loan_file_id: UUID
) -> list[dict[str, Any]]:
    response = await client.get(f"{API}/loan-files/{loan_file_id}/conditions", headers=auth)
    assert response.status_code == 200, response.text
    body: list[dict[str, Any]] = response.json()
    return body


async def _event_count(db: AsyncSession, round_id: str, kind: ConditionEventKind) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(ConditionEvent)
        .where(ConditionEvent.round_id == UUID(round_id), ConditionEvent.kind == kind)
    )
    return int(result.scalar_one())


#: What every condition's two statuses must still be after each Stage 1 step: the defaults they were
#: created with. Stage 1 never clears, removes or changes a status (spec §9.3, ADR-404).
UNTOUCHED = {(ConditionPrepStatus.TO_DO, ConditionLenderStatus.OPEN)}


async def _statuses(
    db: AsyncSession, loan_file_id: UUID
) -> set[tuple[ConditionPrepStatus, ConditionLenderStatus]]:
    result = await db.execute(
        select(Condition.prep_status, Condition.lender_status).where(
            Condition.loan_file_id == loan_file_id
        )
    )
    return {(prep, lender) for prep, lender in result.all()}


# --------------------------------------------------------------------------- #
# Steps 1-3 and 7: one file, three arrivals, then a stranger at the door
# --------------------------------------------------------------------------- #


async def test_the_uwm_file_end_to_end(
    client: AsyncClient, db_session: AsyncSession, enqueued: dict[str, list[str]]
) -> None:
    """§8 steps 1, 2, 3 and 7, in order, on ONE file — the order is part of what is accepted.

    Round 2 is only "seen again" because round 1 was imported first, and the enrich only merges
    into an imported round because round 2 was imported first. Split into three tests with fixtures,
    each would be proving a state the test built by hand rather than one the doors produced.
    """
    company, auth = await _company_user(db_session, slug="accept-uwm")
    loan_file = await _uwm_file(db_session, company)

    # ── Step 1: round 1 by upload ─────────────────────────────────────────────────────────────────
    r1 = await _upload(
        client,
        auth,
        loan_file.id,
        render_uwm_pdf(UWM_ROUND_1),
        enqueued=enqueued,
        db=db_session,
    )
    assert r1["status"] == "draft"
    assert r1["draft_rows"] is not None and len(r1["draft_rows"]) == 11
    assert r1["header"], "step 1 names the header"
    assert r1["expiry_dates"], "step 1 names the expiry dates"

    imported_1 = await _import(client, auth, r1["id"])
    assert imported_1["round_number"] == 1
    assert imported_1["created"] == 11
    assert imported_1["seen_again"] == 0

    conditions = await _conditions(client, auth, loan_file.id)
    assert len(conditions) == 11
    # ⚠️ THREE BUCKETS MEANS THREE HEADINGS, NOT THREE KINDS. The glossary defines a bucket as "the
    # heading a condition is listed under", and round 1 has three — but two of them carry `(PTD)`, so
    # they share a kind. This line first asserted three `bucket_kind`s and failed on a correct read;
    # S1-05 draws the same thing: three headings under two kind labels.
    assert {c["bucket_heading"] for c in conditions} == {
        "UW - Prior To Final Approval (PTD)",
        "Compliance - Prior To Closing (PTD)",
        "Closing (PTF)",
    }, "step 1: three buckets"
    assert {c["bucket_kind"] for c in conditions} == {"prior_to_docs", "prior_to_funding"}
    noted = {c["lender_code"] for c in conditions if c["underwriter_notes"]}
    assert {"6132", "6637"} <= noted, "step 1: notes on 6132 and 6637"
    assert await _event_count(db_session, r1["id"], ConditionEventKind.CONDITION_CREATED) == 11

    # "Unknown codes (if any) recorded as unmapped." A test database carries no seeded code map, so
    # every code on the sheet is unknown here — and each must now have a row rather than be dropped.
    sheet_codes = {c["lender_code"] for c in conditions if c["lender_code"]}
    assert set(imported_1["unmapped_codes"]) == sheet_codes
    recorded = await db_session.execute(
        select(LenderConditionCode.code).where(LenderConditionCode.lender_id == loan_file.lender_id)
    )
    assert sheet_codes <= set(recorded.scalars().all())

    # ── Step 2: round 2 by paste, "just some" ─────────────────────────────────────────────────────
    pasted = await client.post(
        f"{API}/loan-files/{loan_file.id}/condition-rounds/paste",
        json={"text": portal_excerpt(), "completeness": "partial"},
        headers=auth,
    )
    assert pasted.status_code == 201, pasted.text
    r2 = pasted.json()
    assert r2["status"] == "draft", "rows with codes and headings are read by the rules, not the AI"
    assert r2["completeness"] == "partial"
    assert r2["draft_rows"] is not None and len(r2["draft_rows"]) == 6

    imported_2 = await _import(client, auth, r2["id"])
    assert imported_2["round_number"] == 2
    assert (imported_2["created"], imported_2["seen_again"]) == (0, 6)

    conditions = await _conditions(client, auth, loan_file.id)
    assert len(conditions) == 11, "step 2: still 11 conditions, nothing removed"
    assert sum(1 for c in conditions if c["round_numbers"] == [1, 2]) == 6
    assert sum(1 for c in conditions if c["round_numbers"] == [1]) == 5

    # "Every status unchanged" — not on the public schema, so read from the rows themselves.
    assert await _statuses(db_session, loan_file.id) == UNTOUCHED

    # ── Step 3: enrich round 2 with its PDF ───────────────────────────────────────────────────────
    attached = await client.post(
        f"{API}/condition-rounds/{r2['id']}/attach-pdf",
        files={"file": ("round2.pdf", render_uwm_pdf(UWM_ROUND_2), "application/pdf")},
        headers=auth,
    )
    assert attached.status_code == 200, attached.text
    enrich = attached.json()
    assert enrich["round_id"] == r2["id"], "the SAME round — no second one"
    assert enrich["added"] == 0

    r2_after = await _get_round(client, auth, r2["id"])
    assert r2_after["date_printed"] == date(2026, 9, 10).isoformat()
    assert r2_after["header"]
    assert r2_after["expiry_dates"]
    assert [s["kind"] for s in r2_after["sources"]] == ["paste", "pdf_upload"]
    assert len(await _conditions(client, auth, loan_file.id)) == 11, "step 3: still 11"
    assert await _event_count(db_session, r2["id"], ConditionEventKind.ROUND_ENRICHED) == 1
    assert await _statuses(db_session, loan_file.id) == UNTOUCHED, "the enrich moved nothing either"

    rounds = await client.get(f"{API}/loan-files/{loan_file.id}/condition-rounds", headers=auth)
    assert rounds.status_code == 200
    assert sorted(r["round_number"] for r in rounds.json()) == [1, 2], "no third round"

    # ── Step 7: another company cannot list, read, import or discard any of it ────────────────────
    _stranger, stranger = await _company_user(db_session, slug="accept-stranger")
    listed = await client.get(f"{API}/loan-files/{loan_file.id}/condition-rounds", headers=stranger)
    assert listed.status_code == 404
    for round_id in (r1["id"], r2["id"]):
        for method, path in (
            ("GET", ""),
            ("GET", "/events"),
            ("POST", "/import"),
            ("POST", "/discard"),
        ):
            response = await client.request(
                method, f"{API}/condition-rounds/{round_id}{path}", headers=stranger
            )
            assert response.status_code == 404, (method, path, response.status_code)

    # And the refusals changed nothing: a 404 that ran the write before refusing would pass above.
    assert len(await _conditions(client, auth, loan_file.id)) == 11
    for round_id in (r1["id"], r2["id"]):
        assert (await _get_round(client, auth, round_id))["status"] == "imported"


# --------------------------------------------------------------------------- #
# Steps 4-6: the three readers' hard cases, each through a door
# --------------------------------------------------------------------------- #


async def test_the_page_break_sheet(
    client: AsyncClient, db_session: AsyncSession, enqueued: dict[str, list[str]]
) -> None:
    """§8 step 4: 16 rows, 2 duplicates dropped, no unassigned lines."""
    company, auth = await _company_user(db_session, slug="accept-pagebreak")
    loan_file = await create_loan_file(db_session, company_id=company.id)

    round_ = await _upload(
        client,
        auth,
        loan_file.id,
        render_uwm_pdf(UWM_PAGEBREAK),
        enqueued=enqueued,
        db=db_session,
    )

    assert round_["status"] == "draft"
    assert len(round_["draft_rows"]) == 16
    assert round_["parse_report"]["duplicates_dropped"] == 2
    assert round_["parse_report"]["unassigned_lines"] == []


async def test_the_champions_certificate(
    client: AsyncClient, db_session: AsyncSession, enqueued: dict[str, list[str]]
) -> None:
    """§8 step 5: 28 rows, `206` reassembled across the page."""
    company, auth = await _company_user(db_session, slug="accept-champions")
    loan_file = await create_loan_file(db_session, company_id=company.id)

    round_ = await _upload(
        client, auth, loan_file.id, build_champions_pdf(), enqueued=enqueued, db=db_session
    )

    assert round_["status"] == "draft"
    assert round_["sheet_format"] == "champions_certificate"
    rows = round_["draft_rows"]
    assert len(rows) == 28
    row_206 = next(r for r in rows if r["lender_code"] == "206")
    # The seam, as the reader test states it: both halves present and the join not doubled.
    assert row_206["verbatim_text"].startswith(
        "Provide an updated homeowner's insurance declarations page"
    )
    assert row_206["verbatim_text"].endswith("premium paid in full at or before settlement.")
    assert row_206["verbatim_text"].count("The deductible may not") == 1


async def test_the_unstructured_paste_is_split_by_the_ai(
    client: AsyncClient,
    db_session: AsyncSession,
    enqueued: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§8 step 6: round-2 text with no codes or headings → the AI split (mocked) → 6 exact rows."""
    company, auth = await _company_user(db_session, slug="accept-split")
    loan_file = await create_loan_file(db_session, company_id=company.id)

    pasted = await client.post(
        f"{API}/loan-files/{loan_file.id}/condition-rounds/paste",
        json={"text": UNSTRUCTURED, "completeness": "partial"},
        headers=auth,
    )
    assert pasted.status_code == 201, pasted.text
    round_id = pasted.json()["id"]
    assert pasted.json()["status"] == "parsing", "no codes, no headings: the rules cannot read it"
    assert enqueued["split"] == [round_id]

    model = AsyncMock(
        return_value=AICompletion(
            text=json.dumps(
                {
                    "conditions": [
                        {"verbatim": t, "code": None, "bucket_heading": None} for t in ROUND_2_TEXTS
                    ],
                    "ignored": [],
                }
            ),
            input_tokens=1200,
            output_tokens=400,
            model="claude-haiku-4-5",
            stop_reason="end_turn",
            cache_read_tokens=0,
            cache_write_tokens=0,
        )
    )
    monkeypatch.setattr(split_module, "complete", model)

    await split_round(db_session, UUID(round_id))

    round_ = await _get_round(client, auth, round_id)
    assert round_["status"] == "draft"
    assert [r["verbatim_text"] for r in round_["draft_rows"]] == ROUND_2_TEXTS, "exact wording"
    assert round_["parse_report"]["ai_used"] is True
    model.assert_awaited_once()

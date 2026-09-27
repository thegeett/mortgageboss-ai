"""The Stage 2 acceptance scenario, §5 steps 1-9, driven through the API.

WHAT THIS IS FOR. Every other conditions test proves one rule. This one walks the whole file the way a
processor does — import, move, compare, confirm, record by hand, import again, answer a reworded pair,
reopen — and asserts the numbers §5 states at each step. A stage can pass every unit test and still be
wrong about what happens in sequence, which is the only thing this file is looking for.

STEP 10 IS NOT HERE AND CANNOT BE. It reads: "All 11 reference screens are checked against the built UI
at 1600 px." That needs a person with a browser. It is recorded as outstanding in
`docs/phases/phase4.5-progress.md` and in each ticket's Visual check, and no assertion here should be
mistaken for having done it.

THE NUMBERS ARE THE SPEC'S, TRANSCRIBED BEFORE THE RUN. §5 states the summary after most steps; those
are asserted as written rather than as whatever came out. Where a total is arithmetic over the spec's own
figures (13 conditions after round 3, for instance) the working is in the comment beside it.

EVERY SHEET GOES THROUGH THE UPLOAD DOOR and every decision through its endpoint. Nothing here calls a
service directly: the point is the doors.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.main import app
from app.models import Company, User, UserRole
from app.models.condition import Condition
from app.models.lender_condition_code import LenderConditionCode
from app.models.loan_file import LoanFile
from app.scripts.seed_lender_codes import seed_lender_codes
from app.services.loan_files import create_loan_file
from app.tasks import conditions as task_module
from app.tasks.conditions import parse_round
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.fixture_helpers import UWM_ROUND_1, UWM_ROUND_2, UWM_ROUND_3
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
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """What the upload door handed to Celery — recorded rather than sent."""
    seen: list[str] = []
    monkeypatch.setattr(
        task_module.parse_condition_round, "delay", lambda round_id: seen.append(round_id)
    )
    return seen


async def _company_file(db: AsyncSession, name: str) -> tuple[LoanFile, dict[str, str]]:
    """A UWM file with its code map seeded, and a token for its company."""
    company = Company(name=name, slug=f"{name.lower().replace(' ', '-')}-{uuid4().hex[:6]}")
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id,
        email=f"u-{uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("irrelevant"),
        first_name="Priya",
        last_name="Raman",
        role=UserRole.PROCESSOR,
        is_active=True,
    )
    db.add(user)
    loan_file = await create_loan_file(db, company_id=company.id)
    lender = await make_lender(db, company=company, name="UWM")
    lender.canonical_lender_key = "uwm"
    loan_file.lender_id = lender.id
    await db.flush()

    result = await seed_lender_codes(db)
    assert result.inserted > 0, "the UWM map must have seeded"
    seeded = (
        (
            await db.execute(
                select(LenderConditionCode).where(LenderConditionCode.lender_id == lender.id)
            )
        )
        .scalars()
        .all()
    )
    assert seeded, "this lender's codes must be seeded or owners come back unknown"
    return loan_file, {"Authorization": f"Bearer {create_access_token(user.id)}"}


async def _import(
    client: AsyncClient,
    auth: dict[str, str],
    loan_file: LoanFile,
    *,
    db: AsyncSession,
    enqueued: list[str],
    fixture: str,
    completeness: str = "full",
) -> UUID:
    """One sheet the way a processor sends it: upload -> parse -> import."""
    response = await client.post(
        f"{API}/loan-files/{loan_file.id}/condition-rounds/uploads",
        files={"file": (f"{fixture}.pdf", render_uwm_pdf(fixture), "application/pdf")},
        data={"completeness": completeness},
        headers=auth,
    )
    assert response.status_code == 202, response.text
    round_id = response.json()["id"]
    assert enqueued[-1] == round_id

    await parse_round(db, UUID(round_id))
    imported = await client.post(f"{API}/condition-rounds/{round_id}/import", headers=auth)
    assert imported.status_code == 200, imported.text
    return UUID(round_id)


async def _rows(client: AsyncClient, auth: dict[str, str], loan_file: LoanFile) -> list[Any]:
    response = await client.get(f"{API}/loan-files/{loan_file.id}/conditions", headers=auth)
    assert response.status_code == 200, response.text
    rows: list[Any] = response.json()
    return rows


async def _summary(client: AsyncClient, auth: dict[str, str], loan_file: LoanFile) -> Any:
    response = await client.get(f"{API}/loan-files/{loan_file.id}/conditions/summary", headers=auth)
    assert response.status_code == 200, response.text
    return response.json()


async def _ids_by_code(db: AsyncSession, loan_file: LoanFile) -> dict[str, list[str]]:
    """code -> its condition ids, oldest first.

    A LIST PER CODE, because a reworded pair SHARES one. §7.3's `6378` is two conditions with the same
    code and different wording, so a map to a single id would silently pick one of them.
    """
    rows = (
        (
            await db.execute(
                select(Condition)
                .where(Condition.loan_file_id == loan_file.id)
                .order_by(Condition.created_at.asc(), Condition.id.asc())
            )
        )
        .scalars()
        .all()
    )
    out: dict[str, list[str]] = {}
    for row in rows:
        out.setdefault(row.lender_code or "—", []).append(str(row.id))
    return out


async def _comparison(client: AsyncClient, auth: dict[str, str], round_id: UUID) -> Any:
    response = await client.get(f"{API}/condition-rounds/{round_id}", headers=auth)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["comparison"] is not None, "an imported round N>=2 carries a saved comparison"
    return body["comparison"]


def _codes_of(ids: list[str], by_code: dict[str, list[str]]) -> list[str]:
    """Condition ids -> the codes they belong to, sorted — so an assertion reads as the sheet does."""
    lookup = {value: code for code, values in by_code.items() for value in values}
    return sorted(lookup.get(value, "?") for value in ids)


async def _move(
    client: AsyncClient,
    auth: dict[str, str],
    condition_id: str,
    body: dict[str, Any],
) -> Any:
    return await client.post(
        f"{API}/conditions/{condition_id}/prep-status", headers=auth, json=body
    )


async def test_stage2_acceptance_steps_1_to_8(
    client: AsyncClient, db_session: AsyncSession, enqueued: list[str]
) -> None:
    """§5 steps 1-8, in order, on the §7 fixtures."""
    loan_file, auth = await _company_file(db_session, "Acceptance")

    # --- step 1: import round 1 (full). 11 conditions, all To do / Open. Summary: Open 11. ------ #
    round_1 = await _import(
        client, auth, loan_file, db=db_session, enqueued=enqueued, fixture=UWM_ROUND_1
    )
    rows = await _rows(client, auth, loan_file)
    assert len(rows) == 11
    assert {row["prep_status"] for row in rows} == {"to_do"}
    assert {row["lender_status"] for row in rows} == {"open"}
    assert (await _summary(client, auth, loan_file))["open"] == 11
    assert round_1 is not None

    by_code = await _ids_by_code(db_session, loan_file)

    # --- step 2: the moves, and a backward move refused then accepted ------------------------- #
    # `waiting_on` IS A REQUEST FIELD, NOT A RESPONSE ONE, which this test asserted wrongly at first.
    # The row says THAT a condition is waiting through `prep_status`; WHO it waits on is
    # `effective_owner`, which is what the list groups by and what the filter matches. "Waiting on
    # Title" on screen is those two fields together, so those two are what is checked here.
    for code in ("6637", "6132", "7086"):
        moved = await _move(
            client, auth, by_code[code][0], {"to": "waiting", "waiting_on": "borrower"}
        )
        assert moved.status_code == 200, (code, moved.text)
        assert moved.json()["prep_status"] == "waiting"
        assert moved.json()["effective_owner"] == "borrower"
    for code in ("1947", "6378"):
        moved = await _move(
            client, auth, by_code[code][0], {"to": "waiting", "waiting_on": "title"}
        )
        assert moved.status_code == 200, (code, moved.text)
        assert moved.json()["prep_status"] == "waiting"
        assert moved.json()["effective_owner"] == "title"

    ready = await _move(client, auth, by_code["0006"][0], {"to": "ready"})
    assert ready.status_code == 200, ready.text
    assert ready.json()["prep_status"] == "ready"

    # BACKWARD WITHOUT A REASON IS REFUSED, with the server's own sentence (spec §6 rule 5). The
    # sentence itself is pinned byte for byte against the tickets file in
    # `tests/conditions/test_refusal_sentences.py`; what matters here is that the door refuses and
    # names the target a processor is moving to.
    refused = await _move(client, auth, by_code["0006"][0], {"to": "to_do"})
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["data"]["code"] == "backward_move_needs_reason"
    assert "To do" in refused.json()["error"]["data"]["message"]

    # AND NOTHING MOVED. A refusal that had already written would be worse than no guard.
    still_ready = await _rows(client, auth, loan_file)
    assert next(row for row in still_ready if row["id"] == by_code["0006"][0])["prep_status"] == (
        "ready"
    )

    accepted = await _move(
        client,
        auth,
        by_code["0006"][0],
        {"to": "to_do", "reason": "Invoice was for the wrong report."},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["prep_status"] == "to_do"

    # --- step 3: import round 2 (full). 5 probably cleared, 6 still open, 0 new ---------------- #
    round_2 = await _import(
        client, auth, loan_file, db=db_session, enqueued=enqueued, fixture=UWM_ROUND_2
    )
    comparison = await _comparison(client, auth, round_2)
    assert _codes_of(comparison["probably_cleared"], by_code) == [
        "0132",
        "6132",
        "6178",
        "6637",
        "7086",
    ]
    # EXACT SETS, NOT COUNTS (Stage 2 review): §7.2 says "an exact assertion, not a count".
    assert _codes_of(comparison["still_open"], by_code) == sorted(
        ["1228", "1947", "1582", "0006", "0007", "6378"]
    )
    assert comparison["new"] == []
    assert comparison["came_back"] == []
    assert comparison["compared_with"] == 11
    # The letter changes are pinned value by value in `test_round_compare.py`; here the panel must
    # simply have them, because §5 step 3 names them as part of what the screen shows.
    # EXACTLY the eight LP-915's Done-when lists, and nothing that did not change.
    labels = {change["label"] for change in comparison["letter_changes"]}
    assert labels == {
        "note rate",
        "housing / debt ratios",
        "verified assets",
        "max funds to close",
        "rate lock expiry",
        "UW team",
        "close by expiry",
        "asset expiry",
    }

    # --- step 4: untick 0132, confirm 4. Open 7 · Cleared 4. 0132 keeps no suggestion ---------- #
    unticked = by_code["0132"][0]
    ticked = [value for value in comparison["probably_cleared"] if value != unticked]
    assert len(ticked) == 4
    confirmed = await client.post(
        f"{API}/condition-rounds/{round_2}/confirm-cleared",
        headers=auth,
        # THE PANEL'S REQUEST: `resolve_rest` defaults true, so the unticked one loses its suggestion.
        # That is what makes step 4's "0132 stays open with no suggestion" true.
        json={"condition_ids": ticked},
    )
    assert confirmed.status_code == 200, confirmed.text

    summary = await _summary(client, auth, loan_file)
    assert summary["open"] == 7
    assert summary["cleared"] == 4
    # NO QUESTION IS LEFT PENDING ANYWHERE, which is the half of step 4 that is easy to miss.
    assert summary["pending_suggestions"] == 0
    left = next(row for row in await _rows(client, auth, loan_file) if row["id"] == unticked)
    assert left["lender_status"] == "open"
    assert left["verdict"] is None

    # --- step 5: record 0132 cleared by hand (portal, 09/12/2026). Open 6 · Cleared 5 ---------- #
    by_hand = await client.post(
        f"{API}/conditions/{unticked}/verdict",
        headers=auth,
        json={"status": "cleared", "source_kind": "portal", "source_date": "2026-09-12"},
    )
    assert by_hand.status_code == 200, by_hand.text
    summary = await _summary(client, auth, loan_file)
    assert summary["open"] == 6
    assert summary["cleared"] == 5

    # --- step 6: 1228 to the lender, import round 3, answer the pair, confirm both ------------- #
    sent = await _move(client, auth, by_code["1228"][0], {"to": "with_underwriter"})
    assert sent.status_code == 200, sent.text

    round_3 = await _import(
        client, auth, loan_file, db=db_session, enqueued=enqueued, fixture=UWM_ROUND_3
    )
    after_3 = await _ids_by_code(db_session, loan_file)
    comparison = await _comparison(client, auth, round_3)

    assert _codes_of(comparison["came_back"], after_3) == ["1228"]
    assert _codes_of(comparison["new"], after_3) == ["7383"]
    assert _codes_of(comparison["probably_cleared"], after_3) == ["0006", "0007"]
    # §7.3's full expectation: still open `1947 1582` (Stage 2 review — it was not asserted).
    assert _codes_of(comparison["still_open"], after_3) == ["1582", "1947"]

    came_back_row = next(
        row for row in await _rows(client, auth, loan_file) if row["id"] == by_code["1228"][0]
    )
    assert came_back_row["lender_status"] == "not_cleared"
    assert came_back_row["came_back"] is True
    # OUR TRACK WENT BACK, which is what makes the condition findable again (ADR-408 as amended).
    assert came_back_row["prep_status"] == "to_do"

    # The reworded pair: two conditions, one code.
    assert len(after_3["6378"]) == 2, "round 3 reworded 6378 into a second condition"
    (pair,) = comparison["reworded"]
    # THE PAIR IS 6378 OLD → 6378 NEW (Stage 2 review): the old half is round 1's condition, and the
    # old half is never in probably cleared.
    assert pair["old_id"] == after_3["6378"][0]
    assert pair["new_id"] == after_3["6378"][1]
    assert pair["old_id"] not in comparison["probably_cleared"]
    same = await client.post(
        f"{API}/condition-rounds/{round_3}/reworded",
        headers=auth,
        json={"old_id": pair["old_id"], "new_id": pair["new_id"], "same": True},
    )
    assert same.status_code == 200, same.text
    replaced = next(
        row for row in await _rows(client, auth, loan_file) if row["id"] == pair["old_id"]
    )
    assert replaced["lender_status"] == "superseded"
    assert replaced["superseded_by_id"] == pair["new_id"]

    both = await client.post(
        f"{API}/condition-rounds/{round_3}/confirm-cleared",
        headers=auth,
        json={"condition_ids": comparison["probably_cleared"]},
    )
    assert both.status_code == 200, both.text

    # NOTHING ALREADY CLEARED IS TOUCHED — the sentence step 6 ends on, asserted from the side that
    # can actually go wrong. `0132` was cleared BY HAND from the portal; round 3's comparison must
    # neither suggest it again (it is no longer open) nor overwrite its verdict with a
    # `round_comparison` one. That overwrite is exactly what LP-915's review found (R2).
    assert unticked not in comparison["probably_cleared"]
    portal = next(row for row in await _rows(client, auth, loan_file) if row["id"] == unticked)
    assert portal["lender_status"] == "cleared"
    assert portal["verdict"]["source_kind"] == "portal"
    assert portal["verdict"]["source_date"] == "2026-09-12"

    # 13 conditions now: 11 from round 1, plus `7383` and the reworded half of `6378`.
    # Cleared 7 = the 4 confirmed + `0132` by hand + `0006` + `0007`. One superseded. Which leaves
    # five open: `1228` (came back counts as open), `1947`, `1582`, `7383` and the new `6378`.
    summary = await _summary(client, auth, loan_file)
    assert summary["total"] == 13
    assert summary["cleared"] == 7
    assert summary["superseded"] == 1
    assert summary["open"] == 5

    # --- step 7: reopen 0006 with a reason; its history reads in plain words -------------------- #
    reopened = await client.post(
        f"{API}/conditions/{by_code['0006'][0]}/reopen",
        headers=auth,
        json={"reason": "The lender re-issued it on the next sheet."},
    )
    assert reopened.status_code == 200, reopened.text
    body = reopened.json()
    assert body["lender_status"] == "open"
    assert body["prep_status"] == "to_do"
    assert body["verdict"] is None

    events = await client.get(f"{API}/conditions/{by_code['0006'][0]}/events", headers=auth)
    assert events.status_code == 200, events.text
    kinds = [event["kind"] for event in events.json()]
    # NEWEST FIRST, which S2-03 states ("History in plain words, newest first") and this test asserted
    # backwards at first. Pinned as an ORDER rather than by flipping two indices: the sheet renders
    # the list in the order it arrives, so a server that quietly reversed it would redraw every
    # history on the file with the oldest line at the top and nothing else would notice.
    assert kinds[0] == "condition_reopened", "the newest event leads"
    assert kinds[-1] == "condition_created", "and the oldest is last"
    # EVERY STEP THIS CONDITION TOOK IS IN ITS HISTORY: created, moved to ready, moved back with a
    # reason, seen again on later sheets, cleared by round 3's comparison, reopened.
    assert "condition_prep_moved" in kinds
    assert "condition_verdict_recorded" in kinds
    assert "condition_seen_again" in kinds

    # --- step 8: the lender dates come from round 3, which has its own letter ------------------ #
    round_3_body = (await client.get(f"{API}/condition-rounds/{round_3}", headers=auth)).json()
    facts = round_3_body["header"]["loan_facts"]
    # §7.3's sheet prints these, so the rail's "from round 3" branch is the live one rather than the
    # round-2 fallback. Which round the RAIL picks is `lib/conditions/lender-dates.test.ts`; that the
    # API serves round 3's own dates is this step.
    assert facts["Must Not Close Before"] == "09/30/2026"
    assert facts["Rate Lock Exp"] == "09/30/2026"
    assert any(value for value in (round_3_body["expiry_dates"] or {}).values())


async def test_step_9_another_company_can_do_none_of_it(
    client: AsyncClient, db_session: AsyncSession, enqueued: list[str]
) -> None:
    """§5 step 9: "A second company can't read, move, verdict, compare or switch completeness."

    404, NOT 403, AND THAT IS THE POINT. The scoping is inside the query, so another tenant's row is
    unfetchable rather than fetched and then refused — a 403 would confirm the id exists.
    """
    loan_file, auth = await _company_file(db_session, "Owner co")
    round_2 = await _import(
        client, auth, loan_file, db=db_session, enqueued=enqueued, fixture=UWM_ROUND_1
    )
    condition_id = (await _rows(client, auth, loan_file))[0]["id"]

    _stranger_file, stranger = await _company_file(db_session, "Stranger co")

    for method, path, body in (
        ("GET", f"/loan-files/{loan_file.id}/conditions", None),
        ("GET", f"/loan-files/{loan_file.id}/conditions/summary", None),
        ("GET", f"/conditions/{condition_id}", None),
        ("GET", f"/conditions/{condition_id}/events", None),
        ("GET", f"/condition-rounds/{round_2}", None),
        ("POST", f"/conditions/{condition_id}/prep-status", {"to": "ready"}),
        (
            "POST",
            f"/conditions/{condition_id}/verdict",
            {"status": "cleared", "source_kind": "portal", "source_date": "2026-09-12"},
        ),
        ("POST", f"/conditions/{condition_id}/reopen", {"reason": "x"}),
        ("PUT", f"/conditions/{condition_id}/owner", {"owner": "title"}),
        (
            "POST",
            f"/condition-rounds/{round_2}/confirm-cleared",
            {"condition_ids": [condition_id]},
        ),
        (
            "POST",
            f"/condition-rounds/{round_2}/reworded",
            {"old_id": condition_id, "new_id": condition_id, "same": True},
        ),
        ("PUT", f"/condition-rounds/{round_2}/completeness", {"completeness": "partial"}),
    ):
        response = await client.request(method, f"{API}{path}", headers=stranger, json=body)
        assert response.status_code == 404, (method, path, response.status_code)

    # AND THE FILE IS UNTOUCHED. Every id above is real; only the caller's company differs.
    rows = await _rows(client, auth, loan_file)
    assert len(rows) == 11
    assert {row["lender_status"] for row in rows} == {"open"}
    assert {row["prep_status"] for row in rows} == {"to_do"}

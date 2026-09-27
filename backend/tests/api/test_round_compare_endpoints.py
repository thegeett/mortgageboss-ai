"""The three comparison doors: confirm cleared, resolve a reworded pair, switch completeness (LP-915).

WHAT THESE ADD OVER `tests/conditions/test_round_compare.py` IS THE CLICK. That suite owns §7.2 and
§7.3 — which codes land in which outcome — by calling the engine directly. This one owns what happens
when a processor presses a button: the verdicts a confirm writes, the row a reworded pair replaces, the
suggestions a switch back to *Just some* withdraws, and every refusal each door makes.

THE HELPERS ARE STATED AGAIN RATHER THAN IMPORTED FROM THAT MODULE. Reaching into a sibling test file
for its private helpers couples two suites through names neither declares, and the shared part is one
upload-parse-import sequence. The FIXTURE CONSTANTS and the PDF renderer are imported, because those
are real shared fixtures with a home of their own — duplicating a sheet's bytes is what would matter.

EVERY SHEET GOES IN THROUGH THE UPLOAD DOOR, for the reason the sibling gives: the outcomes are derived
from the events the importer writes, so a test that built those events itself would assert against a
shape of its own invention.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.main import app
from app.models import Company, User, UserRole
from app.models.condition import Condition, ConditionLenderStatus
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_round import (
    ConditionRound,
    ConditionRoundCompleteness,
    ConditionRoundStatus,
)
from app.models.lender_condition_code import LenderCodeStatus, LenderConditionCode
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


async def _file_with_codes(db: AsyncSession) -> tuple[LoanFile, dict[str, str]]:
    """A UWM file whose code map is seeded the way the application seeds it."""
    company = Company(name="Compare doors", slug=f"doors-{uuid4().hex[:6]}")
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
    rows = (
        (
            await db.execute(
                select(LenderConditionCode).where(LenderConditionCode.lender_id == lender.id)
            )
        )
        .scalars()
        .all()
    )
    assert rows and all(row.status is LenderCodeStatus.SEEDED for row in rows)
    return loan_file, {"Authorization": f"Bearer {create_access_token(user.id)}"}


async def _upload_and_import(
    client: AsyncClient,
    auth: dict[str, str],
    loan_file: LoanFile,
    *,
    db: AsyncSession,
    enqueued: list[str],
    fixture: str,
    completeness: str = "full",
) -> UUID:
    """One sheet through the real door: upload → parse → import. Returns the round id."""
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


async def _round(db: AsyncSession, round_id: UUID) -> ConditionRound:
    return (
        await db.execute(select(ConditionRound).where(ConditionRound.id == round_id))
    ).scalar_one()


async def _codes(db: AsyncSession, ids: list[str]) -> list[str]:
    """Condition ids → their lender codes, sorted — so an assertion reads as the sheet does."""
    if not ids:
        return []
    rows = (
        (await db.execute(select(Condition).where(Condition.id.in_([UUID(i) for i in ids]))))
        .scalars()
        .all()
    )
    return sorted(row.lender_code or "—" for row in rows)


async def _by_code(db: AsyncSession, loan_file: LoanFile, code: str) -> list[Condition]:
    """Every condition on the file carrying this lender code, oldest first.

    A LIST, BECAUSE A REWORDED PAIR SHARES ITS CODE. That is the whole shape of §7.3's `6378`: two
    conditions, same code, different wording — so a helper returning "the" condition for a code would
    silently pick one of them.
    """
    rows = (
        (
            await db.execute(
                select(Condition)
                .where(Condition.loan_file_id == loan_file.id, Condition.lender_code == code)
                .order_by(Condition.created_at.asc(), Condition.id.asc())
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def _events_for(db: AsyncSession, condition_id: UUID) -> list[ConditionEvent]:
    rows = await db.execute(
        select(ConditionEvent)
        .where(ConditionEvent.condition_id == condition_id)
        .order_by(ConditionEvent.occurred_at)
    )
    return list(rows.scalars().all())


async def _rounds_one_and_two(
    client: AsyncClient, db: AsyncSession, enqueued: list[str], *, completeness: str = "full"
) -> tuple[LoanFile, dict[str, str], UUID]:
    """The acceptance pair: round 1 full, then round 2. Returns the file, auth and round 2's id."""
    loan_file, auth = await _file_with_codes(db)
    await _upload_and_import(client, auth, loan_file, db=db, enqueued=enqueued, fixture=UWM_ROUND_1)
    round_2 = await _upload_and_import(
        client,
        auth,
        loan_file,
        db=db,
        enqueued=enqueued,
        fixture=UWM_ROUND_2,
        completeness=completeness,
    )
    return loan_file, auth, round_2


# --------------------------------------------------------------------------- #
# Confirming "probably cleared"
# --------------------------------------------------------------------------- #


async def test_confirming_all_five_writes_five_verdicts_sourced_to_round_two(
    client: AsyncClient, db_session: AsyncSession, enqueued: list[str]
) -> None:
    """§7.2's Done-when, through the door: "Confirming all 5 writes 5 verdicts sourced to round 2,
    and the summary becomes Open 6 · Cleared 5".

    THE VERDICT'S SOURCE IS THE ASSERTION THAT MATTERS. Only the lender clears (ADR-404), and what
    makes this legitimate is that the sheet is the evidence — so each verdict must say
    `round_comparison` and name round 2, with the sheet's own printed date rather than today's.
    """
    loan_file, auth, round_2 = await _rounds_one_and_two(client, db_session, enqueued)
    suggested = (await _round(db_session, round_2)).comparison["probably_cleared"]
    assert len(suggested) == 5

    response = await client.post(
        f"{API}/condition-rounds/{round_2}/confirm-cleared",
        headers=auth,
        json={"condition_ids": suggested},
    )

    assert response.status_code == 200, response.text
    # THE ROUND COMES BACK WITH NOTHING PENDING, which is the state the panel has to redraw from.
    assert response.json()["comparison"]["probably_cleared"] == []

    cleared = [
        row
        for row in (
            await db_session.execute(
                select(Condition).where(Condition.loan_file_id == loan_file.id)
            )
        )
        .scalars()
        .all()
        if row.lender_status is ConditionLenderStatus.CLEARED
    ]
    assert sorted(row.lender_code or "—" for row in cleared) == [
        "0132",
        "6132",
        "6178",
        "6637",
        "7086",
    ]
    for row in cleared:
        assert row.verdict is not None
        assert row.verdict["source_kind"] == "round_comparison"
        assert row.verdict["round_id"] == str(round_2)
        # The sheet's date, not the clock's — round 2 is printed 09/10/2026.
        assert row.verdict["source_date"] == "2026-09-10"


async def test_an_unticked_suggestion_stays_open_and_loses_the_suggestion(
    client: AsyncClient, db_session: AsyncSession, enqueued: list[str]
) -> None:
    """S2-07: `0132` unticked, the button reads *Confirm 4 as cleared*.

    "0132 stays Open and loses the suggestion. You can still record the lender's answer on it by
    hand." — so afterwards it must be neither cleared nor still being asked about.
    """
    _loan_file, auth, round_2 = await _rounds_one_and_two(client, db_session, enqueued)
    suggested = (await _round(db_session, round_2)).comparison["probably_cleared"]
    (unticked,) = [value for value in suggested if (await _codes(db_session, [value])) == ["0132"]]
    ticked = [value for value in suggested if value != unticked]
    assert len(ticked) == 4

    response = await client.post(
        f"{API}/condition-rounds/{round_2}/confirm-cleared",
        headers=auth,
        json={"condition_ids": ticked},
    )

    assert response.status_code == 200, response.text
    assert response.json()["comparison"]["probably_cleared"] == []

    left = (
        await db_session.execute(select(Condition).where(Condition.id == UUID(unticked)))
    ).scalar_one()
    await db_session.refresh(left)
    assert left.lender_status is ConditionLenderStatus.OPEN
    assert left.verdict is None


async def test_a_confirm_naming_nothing_pending_is_refused_and_withdraws_nothing(
    client: AsyncClient, db_session: AsyncSession, enqueued: list[str]
) -> None:
    """A SECOND PRESS MUST NOT EMPTY THE PANEL SILENTLY.

    The suggestions are resolved either way once a confirm runs, so a request whose ids are all
    already resolved would withdraw every pending question and record no verdict. That is reachable
    by a double press, a second tab, or a reload after someone else confirmed — so it is refused, and
    the pending list is asserted still to be there afterwards.
    """
    loan_file, auth, round_2 = await _rounds_one_and_two(client, db_session, enqueued)
    suggested = (await _round(db_session, round_2)).comparison["probably_cleared"]
    # A condition on the file that this round did NOT suggest: `1228` is still open, not cleared.
    (not_suggested,) = await _by_code(db_session, loan_file, "1228")

    response = await client.post(
        f"{API}/condition-rounds/{round_2}/confirm-cleared",
        headers=auth,
        json={"condition_ids": [str(not_suggested.id)]},
    )

    assert response.status_code == 409, response.text
    assert "no pending suggestion" in response.json()["error"]["message"]

    await db_session.refresh(not_suggested)
    assert not_suggested.lender_status is ConditionLenderStatus.OPEN
    assert (await _round(db_session, round_2)).comparison["probably_cleared"] == suggested


async def test_the_summary_counts_pending_suggestions_until_they_are_answered(
    client: AsyncClient, db_session: AsyncSession, enqueued: list[str]
) -> None:
    """The number behind "5 probably cleared — review" on the round card and the summary bar.

    ASSERTED HERE RATHER THAN IN THE SUMMARY'S OWN SUITE, because it is a ROUND-level fact reaching a
    condition-level response: nothing on a condition row says "round 2 thinks this cleared" — all five
    rows are plainly `open`, which is the whole distinction between a suggestion and a verdict
    (ADR-404). `summarise_conditions` therefore cannot compute it and is passed it.

    IT SHIPPED AS A HARDCODED `0` FOR THREE TICKETS, honestly labelled "0 until LP-915 writes one". A
    producer added without a test asserting a NON-zero value would have looked identical from every
    existing test, since 0 is a valid count — the same trap `condition_count` fell into.

    AND IT ALSO PINS §7.2'S OTHER DONE-WHEN: "the summary becomes Open 6 · Cleared 5".
    """
    loan_file, auth, round_2 = await _rounds_one_and_two(client, db_session, enqueued)
    summary_path = f"{API}/loan-files/{loan_file.id}/conditions/summary"

    before = await client.get(summary_path, headers=auth)
    assert before.status_code == 200, before.text
    assert before.json()["pending_suggestions"] == 5
    # NOTHING ELSE MOVED. A question was asked; no condition was answered.
    assert before.json()["open"] == 11
    assert before.json()["cleared"] == 0

    suggested = (await _round(db_session, round_2)).comparison["probably_cleared"]
    confirmed = await client.post(
        f"{API}/condition-rounds/{round_2}/confirm-cleared",
        headers=auth,
        json={"condition_ids": suggested},
    )
    assert confirmed.status_code == 200, confirmed.text

    after = await client.get(summary_path, headers=auth)
    assert after.status_code == 200, after.text
    # THE COUNT FALLS BECAUSE THE QUESTIONS WERE ANSWERED, not because anything swept them away.
    assert after.json()["pending_suggestions"] == 0
    assert after.json()["open"] == 6
    assert after.json()["cleared"] == 5


# --------------------------------------------------------------------------- #
# The reworded pair (S2-08)
# --------------------------------------------------------------------------- #


async def _through_round_three(
    client: AsyncClient, db: AsyncSession, enqueued: list[str]
) -> tuple[LoanFile, dict[str, str], UUID, list[str]]:
    """§7.3's state: rounds 1 and 2 imported, round 2's five confirmed, then round 3 imported.

    ROUND 2 IS CONFIRMED THROUGH THE ENDPOINT, which is the scenario §7.3 describes. Unconfirmed,
    those five are still open and round 3 correctly suggests them again — the sibling suite records
    that as a test that was wrong while the engine was right.
    """
    loan_file, auth, round_2 = await _rounds_one_and_two(client, db, enqueued)
    suggested = (await _round(db, round_2)).comparison["probably_cleared"]
    confirmed = await client.post(
        f"{API}/condition-rounds/{round_2}/confirm-cleared",
        headers=auth,
        json={"condition_ids": suggested},
    )
    assert confirmed.status_code == 200, confirmed.text

    round_3 = await _upload_and_import(
        client, auth, loan_file, db=db, enqueued=enqueued, fixture=UWM_ROUND_3
    )
    pair = (await _round(db, round_3)).comparison["reworded"]
    (one,) = pair
    return loan_file, auth, round_3, [str(one[0]), str(one[1])]


async def test_same_condition_replaces_the_old_one_and_writes_one_event(
    client: AsyncClient, db_session: AsyncSession, enqueued: list[str]
) -> None:
    """*Same condition — replace the old one*: the old row becomes **Replaced** and points at its
    successor.

    NOTHING DISAPPEARS (spec §6 rule 3). The old condition is still there with its whole history; what
    changes is that it now names the row carrying the work, which is what the list collapses under
    "Replaced" and what the detail sheet links to.
    """
    _file, auth, round_3, (old_id, new_id) = await _through_round_three(
        client, db_session, enqueued
    )

    response = await client.post(
        f"{API}/condition-rounds/{round_3}/reworded",
        headers=auth,
        json={"old_id": old_id, "new_id": new_id, "same": True},
    )

    assert response.status_code == 200, response.text
    # The pair is answered, so the panel stops asking.
    assert response.json()["comparison"]["reworded"] == []

    old = (
        await db_session.execute(select(Condition).where(Condition.id == UUID(old_id)))
    ).scalar_one()
    await db_session.refresh(old)
    assert old.superseded_by_id == UUID(new_id)
    assert old.lender_status is ConditionLenderStatus.SUPERSEDED

    superseded = [
        event
        for event in await _events_for(db_session, old.id)
        if event.kind is ConditionEventKind.CONDITION_SUPERSEDED
    ]
    assert len(superseded) == 1, "exactly one event per change (spec §6 rule 4)"
    assert superseded[0].detail["superseded_by_id"] == new_id


async def test_a_replaced_condition_then_refuses_every_write(
    client: AsyncClient, db_session: AsyncSession, enqueued: list[str]
) -> None:
    """THE GUARD AND ITS PRODUCER, MEETING.

    LP-916's review handed forward "refuse verdicts and moves on a Replaced condition, adding the
    guard with the producer". This is the whole path in one test: a real reworded pair, confirmed
    *Same*, and then the old row refusing a verdict with the typed code — which was unreachable until
    something wrote `superseded_by_id`.
    """
    _file, auth, round_3, (old_id, new_id) = await _through_round_three(
        client, db_session, enqueued
    )
    same = await client.post(
        f"{API}/condition-rounds/{round_3}/reworded",
        headers=auth,
        json={"old_id": old_id, "new_id": new_id, "same": True},
    )
    assert same.status_code == 200, same.text

    refused = await client.post(
        f"{API}/conditions/{old_id}/verdict",
        headers=auth,
        json={"status": "cleared", "source_kind": "portal", "source_date": "2026-09-20"},
    )

    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["data"]["code"] == "condition_was_replaced"
    assert refused.json()["error"]["data"]["message"] == (
        "This condition was replaced by a later one. Open the condition that replaced it instead."
    )


async def test_different_conditions_answers_the_question_and_changes_neither_row(
    client: AsyncClient, db_session: AsyncSession, enqueued: list[str]
) -> None:
    """*Different conditions — keep both*: no condition changes, and the pair stops being offered.

    RESOLVING THE QUESTION WITHOUT TOUCHING A ROW IS A DECISION TAKEN WITHOUT THE PRODUCT OWNER. The
    spec says "Different leaves both", which is true of the two conditions; left pending as well, the
    panel would ask again forever and "these are different" would be unanswerable.
    """
    _file, auth, round_3, (old_id, new_id) = await _through_round_three(
        client, db_session, enqueued
    )
    old_before = (
        await db_session.execute(select(Condition).where(Condition.id == UUID(old_id)))
    ).scalar_one()
    status_before = old_before.lender_status

    response = await client.post(
        f"{API}/condition-rounds/{round_3}/reworded",
        headers=auth,
        json={"old_id": old_id, "new_id": new_id, "same": False},
    )

    assert response.status_code == 200, response.text
    assert response.json()["comparison"]["reworded"] == []

    await db_session.refresh(old_before)
    assert old_before.superseded_by_id is None
    assert old_before.lender_status is status_before
    assert not [
        event
        for event in await _events_for(db_session, UUID(old_id))
        if event.kind is ConditionEventKind.CONDITION_SUPERSEDED
    ]


async def test_a_pair_the_round_never_offered_is_refused(
    client: AsyncClient, db_session: AsyncSession, enqueued: list[str]
) -> None:
    """The saved comparison is the authority.

    Being replaced hides a row from the working list, so it may happen only on the sheet's own
    evidence — never because a caller named two ids it liked the look of.
    """
    loan_file, auth, round_2 = await _rounds_one_and_two(client, db_session, enqueued)
    (one,) = await _by_code(db_session, loan_file, "1228")
    (two,) = await _by_code(db_session, loan_file, "1947")

    response = await client.post(
        f"{API}/condition-rounds/{round_2}/reworded",
        headers=auth,
        json={"old_id": str(one.id), "new_id": str(two.id), "same": True},
    )

    assert response.status_code == 409, response.text
    assert "reworded pair" in response.json()["error"]["message"]
    await db_session.refresh(one)
    assert one.superseded_by_id is None


# --------------------------------------------------------------------------- #
# Switching completeness (A7)
# --------------------------------------------------------------------------- #


async def test_switching_a_partial_round_to_full_produces_the_same_five(
    client: AsyncClient, db_session: AsyncSession, enqueued: list[str]
) -> None:
    """§7.2's Done-when: "switching to Full list then gives the same 5".

    THIS IS THE ONE EDIT THAT CHANGES WHAT ABSENCE MEANS. Imported as *Just some*, the sheet claimed
    to list nothing in particular and nothing was suggested; marked *Full list*, the same sheet claims
    to list everything, and the five conditions missing from it become the question.
    """
    _loan_file, auth, round_2 = await _rounds_one_and_two(
        client, db_session, enqueued, completeness=ConditionRoundCompleteness.PARTIAL.value
    )
    before = await _round(db_session, round_2)
    assert before.comparison["probably_cleared"] == []

    response = await client.put(
        f"{API}/condition-rounds/{round_2}/completeness",
        headers=auth,
        json={
            "completeness": ConditionRoundCompleteness.FULL.value,
            "expected_updated_at": before.updated_at.isoformat(),
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["completeness"] == "full"
    assert await _codes(db_session, body["comparison"]["probably_cleared"]) == [
        "0132",
        "6132",
        "6178",
        "6637",
        "7086",
    ]
    assert body["comparison"]["no_suggestions_reason"] is None

    kinds = [
        event.kind
        for event in (
            await db_session.execute(
                select(ConditionEvent).where(
                    ConditionEvent.round_id == round_2, ConditionEvent.condition_id.is_(None)
                )
            )
        )
        .scalars()
        .all()
    ]
    assert ConditionEventKind.ROUND_COMPLETENESS_CHANGED in kinds


async def test_switching_back_to_just_some_withdraws_the_pending_suggestions(
    client: AsyncClient, db_session: AsyncSession, enqueued: list[str]
) -> None:
    """A7's first half: the unconfirmed suggestions go, because the sheet no longer claims that the
    conditions missing from it were finished.

    NOTHING IS CONFIRMED FIRST, AND AN EARLIER VERSION OF THIS TEST GOT THAT WRONG. It confirmed one
    suggestion and then asserted the pending list was empty — but confirming resolves ALL of the
    round's suggestions, so the list was already empty and the assertion passed without the switch
    doing anything. The withdraw path only exists for the processor who pressed *Not now*, so that is
    the state to put the round in: five questions still pending, then withdrawn.

    AND WITHDRAWING CLEARS NOTHING. Five suggestions disappear and five conditions stay exactly as
    they were — a suggestion was never a status (spec §6 rule 1).
    """
    _loan_file, auth, round_2 = await _rounds_one_and_two(client, db_session, enqueued)
    before = await _round(db_session, round_2)
    pending = before.comparison["probably_cleared"]
    assert len(pending) == 5, "five questions must be pending for a withdrawal to mean anything"

    response = await client.put(
        f"{API}/condition-rounds/{round_2}/completeness",
        headers=auth,
        json={
            "completeness": ConditionRoundCompleteness.PARTIAL.value,
            "expected_updated_at": before.updated_at.isoformat(),
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["completeness"] == "partial"
    assert body["comparison"]["probably_cleared"] == []
    assert body["comparison"]["no_suggestions_reason"] == (
        "This round was just some conditions, so nothing is suggested as cleared."
    )

    rows = (
        (
            await db_session.execute(
                select(Condition).where(Condition.id.in_([UUID(value) for value in pending]))
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 5
    for row in rows:
        await db_session.refresh(row)
        assert row.lender_status is ConditionLenderStatus.OPEN
        assert row.verdict is None


async def test_a_recorded_verdict_survives_a_switch_back_to_just_some(
    client: AsyncClient, db_session: AsyncSession, enqueued: list[str]
) -> None:
    """A7's second half: confirmed verdicts STAY.

    They are the processor's recorded decision, and only the lender clears (ADR-404) — so nothing
    about switching a round's completeness may unpick one. The switch and the confirm are tested apart
    because a confirm leaves no pending suggestion to withdraw: these are two different halves of A7,
    not two assertions about one call.
    """
    _loan_file, auth, round_2 = await _rounds_one_and_two(client, db_session, enqueued)
    suggested = (await _round(db_session, round_2)).comparison["probably_cleared"]
    confirmed = await client.post(
        f"{API}/condition-rounds/{round_2}/confirm-cleared",
        headers=auth,
        json={"condition_ids": suggested},
    )
    assert confirmed.status_code == 200, confirmed.text

    # Re-read: the confirm wrote verdicts and resolved the panel, so `updated_at` has moved on.
    round_row = await _round(db_session, round_2)
    response = await client.put(
        f"{API}/condition-rounds/{round_2}/completeness",
        headers=auth,
        json={
            "completeness": ConditionRoundCompleteness.PARTIAL.value,
            "expected_updated_at": round_row.updated_at.isoformat(),
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["completeness"] == "partial"

    rows = (
        (
            await db_session.execute(
                select(Condition).where(Condition.id.in_([UUID(value) for value in suggested]))
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 5
    for row in rows:
        await db_session.refresh(row)
        assert row.lender_status is ConditionLenderStatus.CLEARED, "a verdict is not undone"
        assert row.verdict is not None
        assert row.verdict["source_kind"] == "round_comparison"


async def test_a_stale_expected_updated_at_is_refused_and_changes_nothing(
    client: AsyncClient, db_session: AsyncSession, enqueued: list[str]
) -> None:
    """Two tabs on one round, refused rather than silently last-write-wins."""
    _loan_file, auth, round_2 = await _rounds_one_and_two(
        client, db_session, enqueued, completeness=ConditionRoundCompleteness.PARTIAL.value
    )
    round_row = await _round(db_session, round_2)
    stale = round_row.created_at.isoformat()

    response = await client.put(
        f"{API}/condition-rounds/{round_2}/completeness",
        headers=auth,
        json={
            "completeness": ConditionRoundCompleteness.FULL.value,
            "expected_updated_at": stale,
        },
    )

    assert response.status_code == 409, response.text
    assert "Someone else changed this round" in response.json()["error"]["message"]

    await db_session.refresh(round_row)
    assert round_row.completeness is ConditionRoundCompleteness.PARTIAL
    assert round_row.comparison["probably_cleared"] == []


async def test_a_draft_round_cannot_have_its_completeness_switched(
    client: AsyncClient, db_session: AsyncSession, enqueued: list[str]
) -> None:
    """Imported rounds only. A draft's completeness belongs to the review screen, which edits it
    through `PUT /draft` — a second door onto the same field would let a round be switched out from
    under that screen."""
    loan_file, auth = await _file_with_codes(db_session)
    response = await client.post(
        f"{API}/loan-files/{loan_file.id}/condition-rounds/uploads",
        files={"file": (f"{UWM_ROUND_1}.pdf", render_uwm_pdf(UWM_ROUND_1), "application/pdf")},
        data={"completeness": "full"},
        headers=auth,
    )
    assert response.status_code == 202, response.text
    round_id = response.json()["id"]
    await parse_round(db_session, UUID(round_id))
    draft = await _round(db_session, UUID(round_id))
    assert draft.status is ConditionRoundStatus.DRAFT

    refused = await client.put(
        f"{API}/condition-rounds/{round_id}/completeness",
        headers=auth,
        json={"completeness": ConditionRoundCompleteness.PARTIAL.value},
    )

    assert refused.status_code == 409, refused.text
    assert "Only an imported round" in refused.json()["error"]["message"]
    await db_session.refresh(draft)
    assert draft.completeness is ConditionRoundCompleteness.FULL

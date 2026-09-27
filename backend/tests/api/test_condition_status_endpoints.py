"""The five writes: moving our track, recording the lender's answer, reopening, the owner, and bulk.

WHAT THESE TESTS ARE ABOUT IS WHAT THE ENDPOINTS REFUSE. The happy paths are one assertion each; the
refusals are the product decision (ADR-404, ADR-408), so each one is checked for its STATUS, its typed
CODE and its SENTENCE — the UI shows the server's words as-is (spec §6 rule 5), so a sentence that
drifts is a user-visible defect that no other test would catch.

AND FOR EVERY REFUSAL, THAT NOTHING CHANGED. A 409 that has already written is worse than no guard at
all: the processor is told the write was refused and the row moved anyway. That is asserted rather than
assumed, because it is invisible from the response alone.

THE FIXTURES ARE THE LIGHT ONES ON PURPOSE. Status rules do not depend on a lender's sheet, so these
build conditions with `make_condition` rather than importing a PDF — a status refusal that failed
because a code map was unseeded would be a test failing for a reason it is not about. The came-back
hook, which DOES depend on real notes on a real round, is tested in
`tests/conditions/test_came_back.py` against the fixtures.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.main import app
from app.models import Company, User, UserRole
from app.models.condition import (
    Condition,
    ConditionLenderStatus,
    ConditionPrepStatus,
    OwnerHint,
)
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.schemas.condition import VerdictRequest, VerdictSourceKind
from app.services import condition_status
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.models.conftest_helpers import make_company, make_condition, make_loan_file, make_round

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


async def _auth_for(db: AsyncSession, company: Company) -> dict[str, str]:
    user = User(
        company_id=company.id,
        email=f"u-{uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("irrelevant"),
        first_name="Test",
        last_name="Processor",
        role=UserRole.PROCESSOR,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


async def _one(
    db: AsyncSession, *, info_only: bool = False
) -> tuple[Condition, dict[str, str], Any]:
    """One condition on one file, with a token for its company. Returns `(condition, auth, file)`."""
    company = await make_company(db)
    loan_file = await make_loan_file(db, company=company)
    round_ = await make_round(db, company=company, loan_file=loan_file, round_number=1)
    condition = await make_condition(db, company=company, loan_file=loan_file, round_=round_)
    if info_only:
        condition.info_only = True
        await db.flush()
    return condition, await _auth_for(db, company), loan_file


async def _events(db: AsyncSession, condition_id: UUID) -> list[ConditionEvent]:
    result = await db.execute(
        select(ConditionEvent)
        .where(ConditionEvent.condition_id == condition_id)
        .order_by(ConditionEvent.occurred_at)
    )
    return list(result.scalars().all())


def _error(response: Any) -> dict[str, Any]:
    """The refusal envelope: `{"error": {"type", "message", "data": {"message", "code"}}}`.

    READ FROM THE RESPONSE, NEVER FROM THE EXCEPTION. LP-850's review found every assertion about a
    structured refusal written against the exception object at the service layer, while the client was
    receiving "Request failed" and none of the contents. These assert what a browser would see.
    """
    body: dict[str, Any] = response.json()["error"]
    return body


# --------------------------------------------------------------------------- #
# Our track
# --------------------------------------------------------------------------- #


async def test_a_forward_move_needs_no_reason(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Forward is the work progressing, and the move itself is the record (ADR-408)."""
    condition, auth, _file = await _one(db_session)

    response = await client.post(
        f"{API}/conditions/{condition.id}/prep-status",
        headers=auth,
        json={"to": "ready"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["prep_status"] == "ready"
    (event,) = await _events(db_session, condition.id)
    assert event.kind is ConditionEventKind.CONDITION_PREP_MOVED
    assert event.detail["prep_status_from"] == "to_do"
    assert event.detail["prep_status_to"] == "ready"
    assert "reason" not in event.detail


async def test_a_backward_move_without_a_reason_is_refused_in_the_specs_words(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The refusal S2-05 exists to prevent, with its code AND its sentence.

    The sentence names the TARGET, which the spec's example does not: a move back to *Waiting on
    someone* is also backward, and "Moving back to To do" would be wrong there.
    """
    condition, auth, _file = await _one(db_session)
    condition.prep_status = ConditionPrepStatus.READY
    await db_session.flush()

    response = await client.post(
        f"{API}/conditions/{condition.id}/prep-status", headers=auth, json={"to": "to_do"}
    )

    assert response.status_code == 409, response.text
    error = _error(response)
    assert error["data"]["code"] == "backward_move_needs_reason"
    assert error["message"] == "Moving back to To do needs a short reason."

    # AND NOTHING MOVED. A 409 that has already written is worse than no guard.
    await db_session.refresh(condition)
    assert condition.prep_status is ConditionPrepStatus.READY
    assert await _events(db_session, condition.id) == []


async def test_a_backward_move_with_a_reason_keeps_it_in_the_history(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The reason is the only record of what went wrong, so it lives in the event, not just the row."""
    condition, auth, _file = await _one(db_session)
    condition.prep_status = ConditionPrepStatus.WITH_UNDERWRITER
    await db_session.flush()

    response = await client.post(
        f"{API}/conditions/{condition.id}/prep-status",
        headers=auth,
        json={"to": "to_do", "reason": "Invoice amount does not match the credit report fee."},
    )

    assert response.status_code == 200, response.text
    (event,) = await _events(db_session, condition.id)
    assert event.detail["reason"] == "Invoice amount does not match the credit report fee."
    assert event.detail["prep_status_from"] == "with_underwriter"


async def test_waiting_without_an_owner_is_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """ "Waiting" with nobody named is a status nobody can act on, and the list groups by owner."""
    condition, auth, _file = await _one(db_session)

    response = await client.post(
        f"{API}/conditions/{condition.id}/prep-status", headers=auth, json={"to": "waiting"}
    )

    assert response.status_code == 409, response.text
    assert _error(response)["data"]["code"] == "waiting_needs_owner"
    await db_session.refresh(condition)
    assert condition.prep_status is ConditionPrepStatus.TO_DO


async def test_leaving_waiting_clears_the_owner(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """ "Waiting on Title" is meaningless once we are no longer waiting, and a stale value would keep
    the row in Title's group after the work moved on."""
    condition, auth, _file = await _one(db_session)
    await client.post(
        f"{API}/conditions/{condition.id}/prep-status",
        headers=auth,
        json={"to": "waiting", "waiting_on": "title"},
    )
    await db_session.refresh(condition)
    assert condition.waiting_on is OwnerHint.TITLE

    response = await client.post(
        f"{API}/conditions/{condition.id}/prep-status", headers=auth, json={"to": "ready"}
    )

    assert response.status_code == 200, response.text
    await db_session.refresh(condition)
    assert condition.waiting_on is None


async def test_an_information_only_line_has_no_status_to_move(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """It asks for nothing, so there is nothing to prepare — the spec's sentence, verbatim."""
    condition, auth, _file = await _one(db_session, info_only=True)

    response = await client.post(
        f"{API}/conditions/{condition.id}/prep-status", headers=auth, json={"to": "ready"}
    )

    assert response.status_code == 409, response.text
    error = _error(response)
    assert error["data"]["code"] == "info_only_has_no_status"
    assert error["message"] == (
        "This line is information from the lender — there is nothing to track."
    )


# --------------------------------------------------------------------------- #
# The lender's track
# --------------------------------------------------------------------------- #


async def test_a_verdict_is_the_only_route_to_cleared(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """ADR-404's rule, as the API enforces it: `cleared` arrives with who said so and when."""
    condition, auth, _file = await _one(db_session)

    response = await client.post(
        f"{API}/conditions/{condition.id}/verdict",
        headers=auth,
        json={
            "status": "cleared",
            "source_kind": "portal",
            "source_date": "2026-09-12",
            "note": "Cleared in EASE, condition status screen",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["lender_status"] == "cleared"
    assert body["verdict"]["source_kind"] == "portal"
    assert body["verdict"]["source_date"] == "2026-09-12"
    assert body["verdict"]["recorded_by"] is not None
    # NOT a came-back: the lender cleared it, and `came_back` is the note-sourced case only.
    assert body["came_back"] is False
    assert body["is_open"] is False

    (event,) = await _events(db_session, condition.id)
    assert event.kind is ConditionEventKind.CONDITION_VERDICT_RECORDED
    assert event.detail["source_kind"] == "portal"
    # THE NOTE IS NOT IN THE EVENT. `detail` is dropped whole from `readonly.condition_events`, and the
    # sibling writers keep it to counts, codes and names (LP-909's decision 4).
    assert "note" not in event.detail


async def test_a_refusal_recorded_from_a_phone_call_is_not_a_came_back(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """THE NARROWING LP-911'S REVIEW CARRIED FORWARD (R1/R8), AND THE HALF THAT PROVES IT.

    `came_back` does not mean "the lender said not satisfied". It means "the lender said it IN A DATED
    NOTE". A processor recording a refusal from a phone call sets `not_cleared` and must NOT set
    `came_back`, because S2-08's amber rail and its "set by the lender's note" line would then have no
    note to name.

    WITHOUT THIS ASSERTION THE NARROWING IS UNTESTED. Every test in `test_came_back.py` drives the
    note-sourced path, so the pre-narrowing rule — `came_back = (lender_status == not_cleared)` —
    satisfies all of them. This is the only case that separates the two.
    """
    condition, auth, _file = await _one(db_session)

    response = await client.post(
        f"{API}/conditions/{condition.id}/verdict",
        headers=auth,
        json={
            "status": "not_cleared",
            "source_kind": "phone",
            "source_date": "2026-09-18",
            "note": "Underwriter called, wants the invoice reissued on letterhead.",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["lender_status"] == "not_cleared"
    assert body["verdict"]["source_kind"] == "phone"
    assert body["came_back"] is False, (
        "a phone call names no note, so there is no came-back to draw"
    )


async def test_a_refusal_puts_the_work_back_the_way_the_lenders_note_does(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """TWO ROUTES TO ONE STATUS MUST NOT HAVE OPPOSITE EFFECTS (LP-912 part 2 review, settled here).

    The lender's dated note reset our track; a processor recording that same refusal from a phone call
    left the condition sitting at *Sent to lender*. Same status, same meaning, opposite consequence —
    and the second is the wrong one by this feature's own reopen argument: leaving it there hides the
    condition from the list that would make somebody pick it up again.

    A DECISION TAKEN WITHOUT THE PRODUCT OWNER, recorded in `docs/tickets/LP-912.md` and ADR-408.
    """
    condition, auth, _file = await _one(db_session)
    condition.prep_status = ConditionPrepStatus.WITH_UNDERWRITER
    await db_session.flush()

    response = await client.post(
        f"{API}/conditions/{condition.id}/verdict",
        headers=auth,
        json={"status": "not_cleared", "source_kind": "phone", "source_date": "2026-09-18"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["prep_status"] == "to_do"

    (event,) = await _events(db_session, condition.id)
    # BOTH FROM→TO PAIRS, NAMED AS `condition_came_back` NAMES THEM, so a history line does not need a
    # different vocabulary depending on which route produced the refusal.
    assert event.detail["lender_status_from"] == "open"
    assert event.detail["lender_status_to"] == "not_cleared"
    assert event.detail["prep_status_from"] == "with_underwriter"
    assert event.detail["prep_status_to"] == "to_do"


async def test_a_refusal_leaves_work_already_in_hand_alone(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """THE OTHER HALF, AND IT IS WHAT KEEPS THE RESET FROM BEING DESTRUCTIVE.

    A condition still `waiting` on the borrower was already being worked. Resetting it to `to_do` would
    wipe the owner a processor chose and claim a correction that was not needed — so the scope is
    `ready` / `with_underwriter` only, exactly as the import's came-back branch has it.
    """
    condition, auth, _file = await _one(db_session)
    condition.prep_status = ConditionPrepStatus.WAITING
    condition.waiting_on = OwnerHint.BORROWER
    await db_session.flush()

    response = await client.post(
        f"{API}/conditions/{condition.id}/verdict",
        headers=auth,
        json={"status": "not_cleared", "source_kind": "email", "source_date": "2026-09-18"},
    )

    assert response.status_code == 200, response.text
    await db_session.refresh(condition)
    assert condition.prep_status is ConditionPrepStatus.WAITING
    assert condition.waiting_on is OwnerHint.BORROWER, "the owner somebody chose survives"
    # The lender's track still moved — only ours was left alone.
    assert condition.lender_status is ConditionLenderStatus.NOT_CLEARED


async def test_a_cleared_verdict_still_leaves_our_track_where_it_was(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """THE SCOPE OF THE RESET, PINNED FROM THE OTHER SIDE. Only `not_cleared` puts work back.

    A condition that was *Sent to lender* and is now cleared **was still sent**. Moving our track there
    would erase what we did, which is ADR-408's original rule and still correct — so this test exists to
    stop the new reset quietly widening to every verdict.
    """
    condition, auth, _file = await _one(db_session)
    condition.prep_status = ConditionPrepStatus.WITH_UNDERWRITER
    await db_session.flush()

    response = await client.post(
        f"{API}/conditions/{condition.id}/verdict",
        headers=auth,
        json={"status": "cleared", "source_kind": "portal", "source_date": "2026-09-12"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["prep_status"] == "with_underwriter"


async def test_a_verdict_without_a_date_is_refused_by_the_schema(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """`source_date` HAS NO DEFAULT, which is the single most important line in the schema.

    A verdict dated by our clock is a verdict about us, so the field is required — and a missing one is
    a 422 from the request model rather than a silent `today()`.
    """
    condition, auth, _file = await _one(db_session)

    response = await client.post(
        f"{API}/conditions/{condition.id}/verdict",
        headers=auth,
        json={"status": "cleared", "source_kind": "portal"},
    )

    assert response.status_code == 422, response.text
    await db_session.refresh(condition)
    assert condition.lender_status is ConditionLenderStatus.OPEN
    assert condition.verdict is None


async def test_a_derived_verdict_must_name_its_round(db_session: AsyncSession) -> None:
    """`round_comparison` and `underwriter_note` are produced by the app from a SHEET, so they carry
    the round that showed it. Without it the provenance is a claim with nothing behind it.

    THROUGH THE SERVICE, AS LP-915 WILL CALL IT (LP-912 review). The public endpoint no longer accepts
    these sources at all — see `test_a_client_cannot_claim_the_apps_own_sources`."""
    condition, _auth, _file = await _one(db_session)

    with pytest.raises(condition_status.ConditionRefused) as refused:
        await condition_status.record_verdict(
            db_session,
            condition=condition,
            payload=VerdictRequest(
                status=ConditionLenderStatus.CLEARED,
                source_kind=VerdictSourceKind.ROUND_COMPARISON,
                source_date=date(2026, 9, 10),
            ),
            derived_allowed=True,
        )

    assert refused.value.code is condition_status.RefusalCode.VERDICT_NEEDS_ROUND
    await db_session.refresh(condition)
    assert condition.verdict is None


async def test_a_derived_verdict_must_name_a_round_on_this_file(db_session: AsyncSession) -> None:
    """LP-912 REVIEW. The first version stored whatever `round_id` it was given. A round from another
    file (here another company's) is not "the sheet that showed it", so it is refused."""
    condition, _auth, _file = await _one(db_session)
    elsewhere, _other_auth, _other_file = await _one(db_session)

    with pytest.raises(condition_status.ConditionRefused) as refused:
        await condition_status.record_verdict(
            db_session,
            condition=condition,
            payload=VerdictRequest(
                status=ConditionLenderStatus.CLEARED,
                source_kind=VerdictSourceKind.ROUND_COMPARISON,
                source_date=date(2026, 9, 10),
                round_id=elsewhere.first_round_id,
            ),
            derived_allowed=True,
        )

    assert refused.value.code is condition_status.RefusalCode.VERDICT_NEEDS_ROUND
    await db_session.refresh(condition)
    assert condition.verdict is None


@pytest.mark.parametrize("source_kind", ["underwriter_note", "round_comparison"])
async def test_a_client_cannot_claim_the_apps_own_sources(
    client: AsyncClient, db_session: AsyncSession, source_kind: str
) -> None:
    """LP-912 REVIEW. Measured against c1fbfedc: `{not_cleared, underwriter_note, <random uuid>}`
    answered 200 with `came_back: true`, painting S2-08's amber rail for a note that never existed.
    A person records what the lender said through portal, email or phone (S2-04)."""
    condition, auth, _file = await _one(db_session)

    response = await client.post(
        f"{API}/conditions/{condition.id}/verdict",
        headers=auth,
        json={
            "status": "not_cleared",
            "source_kind": source_kind,
            "source_date": "2026-09-10",
            "round_id": str(condition.first_round_id),
        },
    )

    assert response.status_code == 409, response.text
    error = _error(response)
    assert error["data"]["code"] == "verdict_needs_source"
    assert error["message"] == (
        "Say where the lender cleared it (portal, email, phone) and on what date."
    )
    await db_session.refresh(condition)
    assert condition.lender_status is ConditionLenderStatus.OPEN
    assert condition.verdict is None


async def test_a_verdict_leaves_our_track_alone(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A condition that was *Sent to lender* and is now cleared was still sent (ADR-408).

    Rewriting our status to something tidier would erase what we did; the history says it instead.
    """
    condition, auth, _file = await _one(db_session)
    condition.prep_status = ConditionPrepStatus.WITH_UNDERWRITER
    await db_session.flush()

    await client.post(
        f"{API}/conditions/{condition.id}/verdict",
        headers=auth,
        json={"status": "cleared", "source_kind": "email", "source_date": "2026-09-12"},
    )

    await db_session.refresh(condition)
    assert condition.prep_status is ConditionPrepStatus.WITH_UNDERWRITER


async def test_reopening_keeps_the_old_verdict_in_history_and_resets_our_track(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Both cases this serves — a misclick and a lender re-issuing — need the old verdict remembered.

    The row's `verdict` is "the current one", so a reopened condition has none; the event is where
    "it was cleared on the 12th and reopened after" lives.
    """
    condition, auth, _file = await _one(db_session)
    condition.prep_status = ConditionPrepStatus.WITH_UNDERWRITER
    await db_session.flush()
    await client.post(
        f"{API}/conditions/{condition.id}/verdict",
        headers=auth,
        json={"status": "cleared", "source_kind": "portal", "source_date": "2026-09-12"},
    )

    response = await client.post(
        f"{API}/conditions/{condition.id}/reopen",
        headers=auth,
        json={"reason": "The lender re-issued it on the next sheet."},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["lender_status"] == "open"
    assert body["verdict"] is None
    # OUR TRACK GOES BACK, unlike after a verdict: the condition needs working again, and leaving it at
    # *Sent to lender* would hide it from the list that would make somebody pick it up.
    assert body["prep_status"] == "to_do"

    kinds = [event.kind for event in await _events(db_session, condition.id)]
    assert kinds == [
        ConditionEventKind.CONDITION_VERDICT_RECORDED,
        ConditionEventKind.CONDITION_REOPENED,
    ]
    reopened = (await _events(db_session, condition.id))[-1]
    assert reopened.detail["overruled_source_kind"] == "portal"
    assert reopened.detail["overruled_source_date"] == "2026-09-12"


async def test_there_is_nothing_to_reopen_on_an_open_condition(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Reopen undoes a verdict. With none recorded there is nothing to undo, and saying so is clearer
    than silently succeeding."""
    condition, auth, _file = await _one(db_session)

    response = await client.post(
        f"{API}/conditions/{condition.id}/reopen", headers=auth, json={"reason": "Mistake."}
    )

    assert response.status_code == 409, response.text
    assert _error(response)["data"]["code"] == "nothing_to_reopen"


# --------------------------------------------------------------------------- #
# Who it is waiting on
# --------------------------------------------------------------------------- #


async def test_a_manual_owner_outranks_the_hint_and_says_so(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A2: the code map and the prefixes are a good first guess, not the truth.

    `owner_hint` IS UNTOUCHED, because it is a true fact about what the sheet said. The override is a
    separate fact about what we decided, and overwriting the hint would destroy the better record of
    where the guess came from.
    """
    condition, auth, _file = await _one(db_session)
    assert condition.owner_hint is OwnerHint.PROCESSOR

    response = await client.put(
        f"{API}/conditions/{condition.id}/owner", headers=auth, json={"owner": "title"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["effective_owner"] == "title"
    assert body["effective_owner_source"] == "manual"
    assert body["owner_hint"] == "processor", "the sheet's guess is still on the row"

    (event,) = await _events(db_session, condition.id)
    assert event.kind is ConditionEventKind.CONDITION_OWNER_CHANGED
    assert event.detail["to"] == "title"


async def test_clearing_the_override_goes_back_to_the_hint(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """`owner: null` means "back to the hint", not "nobody" — which is why the field is nullable rather
    than the endpoint having a second verb."""
    condition, auth, _file = await _one(db_session)
    await client.put(
        f"{API}/conditions/{condition.id}/owner", headers=auth, json={"owner": "title"}
    )

    response = await client.put(
        f"{API}/conditions/{condition.id}/owner", headers=auth, json={"owner": None}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["effective_owner"] == "processor", "the hint is what is left"
    assert body["effective_owner_source"] != "manual", "it no longer claims a person chose it"


async def test_the_owner_filter_returns_what_the_row_displays(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """THE HALF OF THE OVERRIDE BUG THAT NO RESPONSE BODY SHOWS.

    `effective_owner` runs in Python for the rendered field and `_effective_owner_column` runs in SQL
    for the filter, and the two are one rule written twice. When only the Python side honoured the
    override, a condition reassigned to Title DISPLAYED as Title and did not come back under
    `owner=title` — and nothing failed, because each answer is individually valid. The processor's
    symptom is a row they just reassigned vanishing from the group they reassigned it to.

    SO THIS ASSERTS BOTH DIRECTIONS: it appears under the new owner and is gone from the hint's group.
    One without the other would pass on a filter that ignored the override entirely.
    """
    company = await make_company(db_session)
    loan_file = await make_loan_file(db_session, company=company)
    round_ = await make_round(db_session, company=company, loan_file=loan_file, round_number=1)
    condition = await make_condition(
        db_session, company=company, loan_file=loan_file, round_=round_
    )
    auth = await _auth_for(db_session, company)

    moved = await client.put(
        f"{API}/conditions/{condition.id}/owner", headers=auth, json={"owner": "title"}
    )
    assert moved.status_code == 200, moved.text

    async def _owned_by(owner: str) -> list[str]:
        response = await client.get(
            f"{API}/loan-files/{loan_file.id}/conditions", headers=auth, params={"owner": owner}
        )
        assert response.status_code == 200, response.text
        rows: list[dict[str, Any]] = response.json()
        return [row["id"] for row in rows]

    assert await _owned_by("title") == [str(condition.id)]
    assert await _owned_by("processor") == [], "it left the group the code map had guessed"


# --------------------------------------------------------------------------- #
# Concurrency
# --------------------------------------------------------------------------- #


async def test_a_stale_write_is_refused_and_changes_nothing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The guard LP-911 put `updated_at` on the wire to make reachable at all.

    Two processors on one condition is the case; the same check also refuses a tab whose row was moved
    by an import underneath it, which is the same hazard.
    """
    condition, auth, _file = await _one(db_session)
    stale = condition.updated_at

    first = await client.post(
        f"{API}/conditions/{condition.id}/prep-status",
        headers=auth,
        json={"to": "ready", "expected_updated_at": stale.isoformat()},
    )
    assert first.status_code == 200, first.text

    second = await client.post(
        f"{API}/conditions/{condition.id}/prep-status",
        headers=auth,
        json={"to": "with_underwriter", "expected_updated_at": stale.isoformat()},
    )

    assert second.status_code == 409, second.text
    error = _error(second)
    assert error["data"]["code"] == "stale"
    assert error["message"] == "Someone else changed this condition — reload to see their change."

    await db_session.refresh(condition)
    assert condition.prep_status is ConditionPrepStatus.READY, "the second write changed nothing"


# --------------------------------------------------------------------------- #
# Bulk
# --------------------------------------------------------------------------- #


async def test_bulk_applies_what_it_can_and_reports_the_rest(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The shape the UI's "4 marked cleared · 1 skipped: information only" needs (spec §LP-912).

    200 AND NOT 409: partial success is the expected outcome, so the refusals are DATA. A 409 would
    throw away the rows that worked, and a 200 listing only successes would leave a processor to work
    out which row did not move.
    """
    company = await make_company(db_session)
    loan_file = await make_loan_file(db_session, company=company)
    round_ = await make_round(db_session, company=company, loan_file=loan_file, round_number=1)
    good = [
        await make_condition(db_session, company=company, loan_file=loan_file, round_=round_)
        for _ in range(2)
    ]
    skipped = await make_condition(db_session, company=company, loan_file=loan_file, round_=round_)
    skipped.info_only = True
    await db_session.flush()
    auth = await _auth_for(db_session, company)

    response = await client.post(
        f"{API}/loan-files/{loan_file.id}/conditions/bulk",
        headers=auth,
        json={
            "condition_ids": [str(c.id) for c in [*good, skipped]],
            "action": "verdict",
            "status": "cleared",
            "source_kind": "portal",
            "source_date": "2026-09-12",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert sorted(body["applied"]) == sorted(str(c.id) for c in good)
    (refusal,) = body["refused"]
    assert refusal["condition_id"] == str(skipped.id)
    assert refusal["code"] == "info_only_has_no_status"
    assert refusal["message"] == (
        "This line is information from the lender — there is nothing to track."
    )

    # The two that applied each wrote exactly one event; the refused one wrote none.
    for condition in good:
        assert len(await _events(db_session, condition.id)) == 1
    assert await _events(db_session, skipped.id) == []


async def test_a_bulk_verdict_on_five_rows_writes_five_verdicts_and_five_events(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """LP-913's DONE-WHEN, AT THE SCALE IT NAMES: "Bulk verdict on 5 rows writes 5 verdicts and 5
    events."

    THE SIBLING TEST ABOVE DOES NOT COVER THIS, AND THE GAP IS NOT THE NUMBER. It applies TWO rows and
    counts events per row — it never asserts that each row ends up carrying its OWN recorded verdict.
    A bulk write that moved five `lender_status` values while recording a single verdict for the
    batch, or one shared event, would satisfy every assertion in this file.

    THAT FAILURE WOULD PUT "CLEARED" ON FOUR CONDITIONS WITH NOTHING BEHIND IT. Only a recorded
    verdict may say the lender cleared anything (ADR-404), and the verdict is what names who said so
    and where — so a shared one is four rows a processor cannot trace to an answer, on the word this
    whole stage exists to protect.
    """
    company = await make_company(db_session)
    loan_file = await make_loan_file(db_session, company=company)
    round_ = await make_round(db_session, company=company, loan_file=loan_file, round_number=1)
    conditions = [
        await make_condition(db_session, company=company, loan_file=loan_file, round_=round_)
        for _ in range(5)
    ]
    auth = await _auth_for(db_session, company)

    response = await client.post(
        f"{API}/loan-files/{loan_file.id}/conditions/bulk",
        headers=auth,
        json={
            "condition_ids": [str(condition.id) for condition in conditions],
            "action": "verdict",
            "status": "cleared",
            "source_kind": "portal",
            "source_date": "2026-09-12",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    # THE FIVE IDS, NOT FIVE ENTRIES (LP-913 review): a response listing one id five times passed
    # a length check.
    assert sorted(body["applied"]) == sorted(str(condition.id) for condition in conditions)
    assert body["refused"] == [], "nothing here is information-only or stale"

    for condition in conditions:
        await db_session.refresh(condition)
        assert condition.lender_status is ConditionLenderStatus.CLEARED
        # ITS OWN VERDICT, not the batch's. This is the assertion the two-row test never makes.
        assert condition.verdict is not None
        assert condition.verdict["source_kind"] == "portal"
        assert condition.verdict["source_date"] == "2026-09-12"

        events = await _events(db_session, condition.id)
        assert len(events) == 1, "exactly one event per change (spec §6 rule 4)"
        assert events[0].kind is ConditionEventKind.CONDITION_VERDICT_RECORDED


async def test_bulk_goes_through_the_same_service_as_one_row(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """THE HOLE THIS CLOSES: if bulk had its own copy of the backward-move rule, "needs a reason" would
    be enforceable one row at a time and not eleven — making a bulk action the way round a guard."""
    company = await make_company(db_session)
    loan_file = await make_loan_file(db_session, company=company)
    round_ = await make_round(db_session, company=company, loan_file=loan_file, round_number=1)
    condition = await make_condition(
        db_session, company=company, loan_file=loan_file, round_=round_
    )
    condition.prep_status = ConditionPrepStatus.READY
    await db_session.flush()
    auth = await _auth_for(db_session, company)

    response = await client.post(
        f"{API}/loan-files/{loan_file.id}/conditions/bulk",
        headers=auth,
        json={"condition_ids": [str(condition.id)], "action": "prep_status", "to": "to_do"},
    )

    assert response.status_code == 200, response.text
    (refusal,) = response.json()["refused"]
    assert refusal["code"] == "backward_move_needs_reason"
    await db_session.refresh(condition)
    assert condition.prep_status is ConditionPrepStatus.READY


# --------------------------------------------------------------------------- #
# Tenancy
# --------------------------------------------------------------------------- #


async def test_another_company_gets_404_on_every_write(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """404 AND NEVER 403 — confirming the id exists would be an oracle over another tenant's rows.

    The gating walk proves the dependency is DECLARED; this proves it refuses, and that the refusal
    happens BEFORE the write.
    """
    condition, _auth, loan_file = await _one(db_session)
    stranger_company = await make_company(db_session, name="Stranger")
    stranger = await _auth_for(db_session, stranger_company)

    for method, path, body in (
        ("POST", f"/conditions/{condition.id}/prep-status", {"to": "ready"}),
        (
            "POST",
            f"/conditions/{condition.id}/verdict",
            {"status": "cleared", "source_kind": "portal", "source_date": "2026-09-12"},
        ),
        ("POST", f"/conditions/{condition.id}/reopen", {"reason": "x"}),
        ("PUT", f"/conditions/{condition.id}/owner", {"owner": "title"}),
        (
            "POST",
            f"/loan-files/{loan_file.id}/conditions/bulk",
            {"condition_ids": [str(condition.id)], "action": "owner", "owner": "title"},
        ),
    ):
        response = await client.request(method, f"{API}{path}", headers=stranger, json=body)
        assert response.status_code == 404, (method, path, response.status_code)

    await db_session.refresh(condition)
    assert condition.prep_status is ConditionPrepStatus.TO_DO
    assert condition.lender_status is ConditionLenderStatus.OPEN
    assert condition.owner_override is None
    assert await _events(db_session, condition.id) == []


# --------------------------------------------------------------------------- #
# A replaced condition (LP-915)
# --------------------------------------------------------------------------- #

#: The sentence as a processor reads it. Written out rather than imported from the service, because the
#: point of asserting it is that the words cannot change unnoticed — comparing the constant to itself
#: would pass for any wording at all. It is one of the authored five, so `test_refusal_sentences.py`
#: does not pin it against the spec; this is what pins it.
_REPLACED_SENTENCE = (
    "This condition was replaced by a later one. Open the condition that replaced it instead."
)


async def _replaced_pair(db: AsyncSession) -> tuple[Condition, Condition, dict[str, str], Any]:
    """An old condition pointing at the one that replaced it, both on the same file.

    A REAL SUCCESSOR ROW, NOT AN INVENTED UUID. `superseded_by_id` is a foreign key to
    `conditions.id` with `ondelete="RESTRICT"`, so a made-up id fails at flush and the test dies in
    setup rather than asserting anything — the shape of failure `make_loan_file`'s docstring records
    from LP-904.
    """
    company = await make_company(db)
    loan_file = await make_loan_file(db, company=company)
    round_one = await make_round(db, company=company, loan_file=loan_file, round_number=1)
    round_two = await make_round(db, company=company, loan_file=loan_file, round_number=2)
    old = await make_condition(db, company=company, loan_file=loan_file, round_=round_one)
    new = await make_condition(
        db,
        company=company,
        loan_file=loan_file,
        round_=round_two,
        verbatim_text="Provide the paid invoice for the credit report.",
    )
    old.superseded_by_id = new.id
    old.lender_status = ConditionLenderStatus.SUPERSEDED
    await db.flush()
    return old, new, await _auth_for(db, company), loan_file


async def test_every_write_is_refused_on_a_condition_that_was_replaced(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The successor carries the work, so none of the four writes belongs on the old row (ADR-404).

    ALL FOUR, NOT JUST THE VERDICT. The verdict is the dangerous one — it would file what the lender
    said against the condition they stopped asking about — but a prep move on a row the list shows
    collapsed under "Replaced" is invisible work, and an owner there keeps the old row in the Owner
    filter's Title group after everyone moved on. A guard on one write and not the others is the shape
    of hole that makes the unguarded route the way in.
    """
    old, new, auth, _file = await _replaced_pair(db_session)

    for method, path, body in (
        ("POST", f"/conditions/{old.id}/prep-status", {"to": "ready"}),
        (
            "POST",
            f"/conditions/{old.id}/verdict",
            {"status": "cleared", "source_kind": "portal", "source_date": "2026-09-12"},
        ),
        ("POST", f"/conditions/{old.id}/reopen", {"reason": "Cleared by mistake."}),
        ("PUT", f"/conditions/{old.id}/owner", {"owner": "title"}),
    ):
        response = await client.request(method, f"{API}{path}", headers=auth, json=body)

        assert response.status_code == 409, (method, path, response.text)
        assert _error(response)["data"]["code"] == "condition_was_replaced", (method, path)
        assert _error(response)["data"]["message"] == _REPLACED_SENTENCE, (method, path)

    # AND NOTHING MOVED ON EITHER ROW. A 409 that has already written is worse than no guard at all;
    # the successor is checked too, because a guard that refused by acting on the wrong row would look
    # identical from the response.
    await db_session.refresh(old)
    await db_session.refresh(new)
    assert old.lender_status is ConditionLenderStatus.SUPERSEDED
    assert old.prep_status is ConditionPrepStatus.TO_DO
    assert old.verdict is None
    assert old.owner_override is None
    assert new.lender_status is ConditionLenderStatus.OPEN
    assert new.prep_status is ConditionPrepStatus.TO_DO
    assert await _events(db_session, old.id) == []
    assert await _events(db_session, new.id) == []


async def test_a_replaced_row_in_a_bulk_write_is_one_refused_row(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Bulk refuses the replaced row and applies the rest — the same partial-success shape as the
    others, so selecting a collapsed row does not lose the ten that were fine."""
    old, new, auth, loan_file = await _replaced_pair(db_session)

    response = await client.post(
        f"{API}/loan-files/{loan_file.id}/conditions/bulk",
        headers=auth,
        json={"condition_ids": [str(old.id), str(new.id)], "action": "owner", "owner": "title"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["applied"] == [str(new.id)]
    (refusal,) = body["refused"]
    assert refusal["condition_id"] == str(old.id)
    assert refusal["code"] == "condition_was_replaced"
    assert refusal["message"] == _REPLACED_SENTENCE


async def test_the_replaced_guard_reads_the_pointer_and_outranks_nothing_to_reopen(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Two claims the service's own comments make, neither visible from the other tests.

    THE POINTER IS THE FACT, NOT THE STATUS. `superseded_by_id` names the successor, where
    `lender_status == superseded` is a rendering of it — so this row carries the pointer with the
    status left `open`, and the write is still refused. A guard written against the status would pass
    every other test in this file and let this one through.

    AND IT IS ORDERED ABOVE `_REOPENABLE`. A properly replaced row's status is already outside the
    reopenable set, so a guard placed after that check would answer "there is nothing to reopen" —
    true, but it does not tell the processor where the work went.
    """
    company = await make_company(db_session)
    loan_file = await make_loan_file(db_session, company=company)
    round_ = await make_round(db_session, company=company, loan_file=loan_file, round_number=1)
    old = await make_condition(db_session, company=company, loan_file=loan_file, round_=round_)
    new = await make_condition(
        db_session, company=company, loan_file=loan_file, round_=round_, verbatim_text="Reworded."
    )
    old.superseded_by_id = new.id
    await db_session.flush()
    auth = await _auth_for(db_session, company)
    assert old.lender_status is ConditionLenderStatus.OPEN, "the pointer alone must be enough"

    response = await client.post(
        f"{API}/conditions/{old.id}/reopen", headers=auth, json={"reason": "Mistake."}
    )

    assert response.status_code == 409, response.text
    assert _error(response)["data"]["code"] == "condition_was_replaced"


async def test_every_refusal_code_the_service_can_raise_has_been_exercised() -> None:
    """A CENSUS, SO A NEW CODE IS NOT SHIPPED UNTESTED.

    All nine are triggered by a test in this file that sends the request — `known_elsewhere` is empty
    and should stay that way. This lists them, so adding a code forces a decision rather than sliding
    in with no test at all.
    """
    covered_here = {
        "backward_move_needs_reason",
        "info_only_has_no_status",
        "verdict_needs_round",
        "stale",
        "waiting_needs_owner",
        "nothing_to_reopen",
        # BOTH WERE LISTED AS "COVERED ELSEWHERE OR UNREACHABLE" AND NEITHER WAS TRIGGERED ANYWHERE
        # (LP-912 review): only their sentences were compared. Each now has a test that sends the
        # request. `status_not_offered` was never unreachable — any client can post `review`.
        "verdict_needs_source",
        "status_not_offered",
        # LP-915, and it arrived WITH its producer rather than before it: nothing set
        # `superseded_by_id` until the reworded pair could be confirmed, which is why LP-916's review
        # handed the guard forward to this ticket instead of asking for it then.
        "condition_was_replaced",
    }
    known_elsewhere: set[str] = set()

    all_codes = {code.value for code in condition_status.RefusalCode}
    assert covered_here | known_elsewhere == all_codes, (
        "the refusal codes and this census disagree: "
        f"{sorted(all_codes - (covered_here | known_elsewhere))} are new and untested"
    )


# --------------------------------------------------------------------------- #
# Found in LP-912's review
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("prep-status", {"to": "review"}),
        (
            "verdict",
            {"status": "pending_review", "source_kind": "portal", "source_date": "2026-09-10"},
        ),
    ],
)
async def test_the_a4_statuses_are_refused_with_their_sentence(
    client: AsyncClient, db_session: AsyncSession, path: str, body: dict[str, Any]
) -> None:
    """`status_not_offered` was listed in the census as "unreachable", and nothing triggered it. Any
    client can post `review` or `pending_review`; this is the refusal they get."""
    condition, auth, _file = await _one(db_session)

    response = await client.post(f"{API}/conditions/{condition.id}/{path}", headers=auth, json=body)

    assert response.status_code == 409, response.text
    error = _error(response)
    assert error["data"]["code"] == "status_not_offered"
    assert error["message"] == "That status is not one this screen offers."
    assert await _events(db_session, condition.id) == []


async def test_a_bulk_verdict_with_no_source_is_refused_per_row(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """`verdict_needs_source` was listed as covered "through bulk", and no test sent that bulk."""
    condition, auth, loan_file = await _one(db_session)

    response = await client.post(
        f"{API}/loan-files/{loan_file.id}/conditions/bulk",
        headers=auth,
        json={"condition_ids": [str(condition.id)], "action": "verdict", "status": "cleared"},
    )

    assert response.status_code == 200, response.text
    (refusal,) = response.json()["refused"]
    assert refusal["code"] == "verdict_needs_source"
    await db_session.refresh(condition)
    assert condition.lender_status is ConditionLenderStatus.OPEN


async def test_a_move_to_where_it_already_is_writes_nothing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """LP-912 REVIEW. The first version wrote an event and reset `prep_status_changed_at` on a move to
    the current status, so a bulk "Waiting on Borrower" over rows already waiting restarted every
    clock and put a line in each history for nothing that happened."""
    condition, auth, _file = await _one(db_session)
    body = {"to": "waiting", "waiting_on": "borrower"}
    first = await client.post(
        f"{API}/conditions/{condition.id}/prep-status", headers=auth, json=body
    )
    assert first.status_code == 200, first.text
    await db_session.refresh(condition)
    clock = condition.prep_status_changed_at

    again = await client.post(
        f"{API}/conditions/{condition.id}/prep-status", headers=auth, json=body
    )

    assert again.status_code == 200, again.text
    await db_session.refresh(condition)
    assert condition.prep_status_changed_at == clock
    kinds = [event.kind for event in await _events(db_session, condition.id)]
    assert kinds == [ConditionEventKind.CONDITION_PREP_MOVED]

    # A DIFFERENT OWNER WHILE STILL WAITING IS A CHANGE, and is recorded — but the status clock,
    # which is about how long it has sat in this STATUS, keeps running.
    other = await client.post(
        f"{API}/conditions/{condition.id}/prep-status",
        headers=auth,
        json={"to": "waiting", "waiting_on": "title"},
    )
    assert other.status_code == 200, other.text
    await db_session.refresh(condition)
    assert condition.waiting_on is OwnerHint.TITLE
    assert condition.prep_status_changed_at == clock
    assert len(await _events(db_session, condition.id)) == 2


async def test_setting_the_owner_it_already_has_writes_nothing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    condition, auth, _file = await _one(db_session)
    for _ in range(2):
        response = await client.put(
            f"{API}/conditions/{condition.id}/owner", headers=auth, json={"owner": "title"}
        )
        assert response.status_code == 200, response.text

    kinds = [event.kind for event in await _events(db_session, condition.id)]
    assert kinds == [ConditionEventKind.CONDITION_OWNER_CHANGED]


async def test_every_write_locks_the_row_before_the_stale_check(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """LP-912 REVIEW. Comparing `updated_at` read without a lock lets two concurrent writers both pass
    and the second overwrite the first — the lost update the check exists for. The race itself needs
    two connections, which this harness does not have; what it CAN pin is that the row is read FOR
    UPDATE before anything is written."""
    condition, auth, _file = await _one(db_session)
    statements: list[str] = []
    connection = (await db_session.connection()).sync_connection
    assert connection is not None

    def _record(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        statements.append(statement)

    event.listen(connection, "before_cursor_execute", _record)
    try:
        response = await client.post(
            f"{API}/conditions/{condition.id}/prep-status", headers=auth, json={"to": "ready"}
        )
    finally:
        event.remove(connection, "before_cursor_execute", _record)

    assert response.status_code == 200, response.text
    locked = next(i for i, sql in enumerate(statements) if "FOR UPDATE" in sql)
    updated = next(
        i for i, sql in enumerate(statements) if sql.lstrip().startswith("UPDATE conditions")
    )
    assert locked < updated


async def test_a_backward_move_to_waiting_names_the_owner(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """LP-912 REVIEW. The screens say "Waiting on Title"; the sentence said "Waiting on someone"."""
    condition, auth, _file = await _one(db_session)
    sent = await client.post(
        f"{API}/conditions/{condition.id}/prep-status",
        headers=auth,
        json={"to": "with_underwriter"},
    )
    assert sent.status_code == 200, sent.text

    response = await client.post(
        f"{API}/conditions/{condition.id}/prep-status",
        headers=auth,
        json={"to": "waiting", "waiting_on": "title"},
    )

    assert response.status_code == 409, response.text
    assert _error(response)["message"] == "Moving back to Waiting on Title needs a short reason."

"""What a condition's history is allowed to carry (LP-916, screen S2-03).

TWO KINDS OF TEST, BECAUSE THE TWO RISKS LIVE IN DIFFERENT PLACES.

The VOCABULARY cases are unit tests against `ConditionEventPublic.from_model`, with `detail` built by
hand. They have to be: the collision they exist for involves `ROUND_RECEIVED`, whose rows carry
`condition_id = NULL`, so `events_for_condition` can never return one and the endpoint cannot show the
bug in both directions. Building the dict directly is also the only way to write the value a careless
future writer would store.

The RESOLUTION cases go through the endpoint, because `actor_name` and `round_number` are the two
fields that cannot be read from the event row at all — one lives in `users`, the other behind
`round_id` — and a test that stubbed them would be testing the stub.

THE COLLISION IS THE REASON THIS FILE EXISTS. `ConditionSourceKind` (how a round arrived) and
`VerdictSourceKind` (where the lender said it) BOTH contain `email`, and both are written under
`detail["source_kind"]` by different writers. Projecting one key into two fields without guarding by
KIND would render a lender's emailed answer as a condition sheet arriving by email, and nothing else
in the suite would notice: both values are individually valid members of their own enum.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

import pytest
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.main import app
from app.models import User, UserRole
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.schemas.condition import ConditionEventPublic
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from tests.models.conftest_helpers import make_company, make_condition, make_loan_file, make_round

API = "/api/v1"


def _event(kind: ConditionEventKind, detail: dict[str, Any]) -> ConditionEvent:
    """An event in memory, with `detail` exactly as written — no session, no flush.

    IN MEMORY ON PURPOSE. These cases are about the PROJECTION, and a database round trip would add a
    schema's opinions to a test whose subject is what `from_model` lets through.
    """
    return ConditionEvent(
        kind=kind,
        occurred_at=datetime(2026, 9, 12, 16, 31, tzinfo=UTC),
        detail=detail,
    )


# --------------------------------------------------------------------------- #
# The collision
# --------------------------------------------------------------------------- #


def test_a_lenders_emailed_verdict_is_not_a_sheet_arriving_by_email() -> None:
    """THE BUG THIS GUARD EXISTS FOR, IN THE DIRECTION THAT WOULD HAVE SHIPPED.

    `email` is a member of BOTH source vocabularies, so a verdict recorded from an email satisfies
    `ConditionSourceKind` too. Without the kind guard this event would have populated the round-level
    `source_kind`, and S2-03's history would say a condition sheet was forwarded to us on the day the
    lender actually answered one.
    """
    public = ConditionEventPublic.from_model(
        _event(
            ConditionEventKind.CONDITION_VERDICT_RECORDED,
            {"status": "cleared", "source_kind": "email", "source_date": "2026-09-12"},
        )
    )

    assert public.verdict_source_kind is not None
    assert public.verdict_source_kind.value == "email", "the lender emailed their answer"
    assert public.source_kind is None, "no sheet arrived; this is the collision the guard prevents"


def test_a_sheet_that_arrived_by_email_is_not_a_lenders_verdict() -> None:
    """THE SAME COLLISION, THE OTHER WAY. A forwarded condition sheet must not read as the lender
    answering — which would put a verdict's provenance on an event that states no answer at all."""
    public = ConditionEventPublic.from_model(
        _event(ConditionEventKind.ROUND_RECEIVED, {"source_kind": "email"})
    )

    assert public.source_kind is not None
    assert public.source_kind.value == "email", "the sheet was forwarded"
    assert public.verdict_source_kind is None, "nobody said anything about a condition"


def test_a_verdicts_date_does_not_leak_onto_events_that_state_no_verdict() -> None:
    """`source_date` is guarded by kind for the same reason as `source_kind`.

    A key name is not a contract. Today only the two verdict-bearing kinds store one; the guard is
    what stops a future writer's unrelated `source_date` rendering as "the lender said so on...".
    """
    public = ConditionEventPublic.from_model(
        _event(ConditionEventKind.ROUND_IMPORTED, {"source_date": "2026-09-12"})
    )

    assert public.verdict_source_date is None


# --------------------------------------------------------------------------- #
# The closed vocabularies
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "field",
    ["prep_status_from", "prep_status_to", "lender_status_from", "lender_status_to"],
)
def test_a_status_outside_the_enum_does_not_travel(field: str) -> None:
    """The rule the class docstring sets: every string exposed is drawn from a fixed set.

    `detail` is free-form JSONB. A writer that stored a status this build has never heard of must
    produce a field the client cannot misread, not a string that renders as an unrecognised value
    beside four real ones.
    """
    public = ConditionEventPublic.from_model(
        _event(ConditionEventKind.CONDITION_PREP_MOVED, {field: "on_fire"})
    )

    assert getattr(public, field) is None


def test_the_two_tracks_are_projected_from_the_keys_their_writers_use() -> None:
    """A `not_cleared` verdict carries BOTH pairs (LP-912 follow-up), and S2-03's line reads both:
    what the lender said, and what it did to our work."""
    public = ConditionEventPublic.from_model(
        _event(
            ConditionEventKind.CONDITION_VERDICT_RECORDED,
            {
                "status": "not_cleared",
                "source_kind": "phone",
                "source_date": "2026-09-18",
                "lender_status_from": "open",
                "lender_status_to": "not_cleared",
                "prep_status_from": "with_underwriter",
                "prep_status_to": "to_do",
            },
        )
    )

    assert public.lender_status_from is not None and public.lender_status_from.value == "open"
    assert public.lender_status_to is not None and public.lender_status_to.value == "not_cleared"
    assert public.prep_status_from is not None
    assert public.prep_status_from.value == "with_underwriter"
    assert public.prep_status_to is not None and public.prep_status_to.value == "to_do"
    assert public.verdict_source_date == date(2026, 9, 18), "the LENDER's date, not ours"


def test_an_unparseable_date_becomes_none_rather_than_today() -> None:
    """A VERDICT DATED BY OUR CLOCK IS A VERDICT ABOUT US (ADR-408).

    `_as_date` returns None rather than falling back, so a malformed value costs the line its date
    instead of inventing the one fact that makes a verdict checkable.
    """
    public = ConditionEventPublic.from_model(
        _event(
            ConditionEventKind.CONDITION_VERDICT_RECORDED,
            {"source_kind": "portal", "source_date": "the twelfth"},
        )
    )

    assert public.verdict_source_date is None


# --------------------------------------------------------------------------- #
# NPI
# --------------------------------------------------------------------------- #


def test_an_actor_name_in_detail_is_ignored() -> None:
    """THE DOOR `actor_name` OPENS, SHUT BEFORE ANYTHING WALKS THROUGH IT.

    Every other string this schema exposes is drawn from a closed vocabulary, which is what stops
    `detail={"reader": "Alex Rivera"}` reaching a client through a key that IS on the allow-list —
    the exact trick `test_condition_events_endpoint.py` plays one file over.

    `actor_name` CANNOT BE DEFENDED THAT WAY, because a person's name has no vocabulary. It is safe
    because of where it comes FROM: the `users` table, resolved by the caller. So the property that
    matters is that the key is never read from `detail` — and that property is the entire
    justification for the field being on the allow-list at all.

    Without this, a writer storing `detail["actor_name"] = "<borrower's name>"` would surface it
    through a field whose allow-list entry says it comes from `users`. Nothing else would notice:
    the value is a well-formed string under a key that is on the list.
    """
    public = ConditionEventPublic.from_model(
        _event(
            ConditionEventKind.CONDITION_PREP_MOVED,
            {"actor_name": "Alex Rivera", "prep_status_to": "waiting"},
        )
    )

    assert public.actor_name is None, "a name may come from `users`, never from `detail`"
    # The well-formed key beside it still comes through, so this is a source check rather than the
    # whole event being discarded.
    assert public.prep_status_to is not None
    assert public.prep_status_to.value == "waiting"

    # AND THE CALLER'S VALUE IS WHAT LANDS, so the field is not merely always-null.
    named = ConditionEventPublic.from_model(
        _event(ConditionEventKind.CONDITION_PREP_MOVED, {"actor_name": "Alex Rivera"}),
        actor_name="Priya Raman",
    )
    assert named.actor_name == "Priya Raman"


def test_the_lenders_words_never_reach_the_history() -> None:
    """RULE 7, AT THE LAYER THAT WOULD HAVE LEAKED IT.

    `detail` is NPI-classified and `readonly.condition_events` drops it whole. The history panel is
    the one door built to read these rows, so this asserts the door is narrow: a note's TEXT and the
    lender's code are absent from the projection even when the writer stored them, and only the COUNT
    travels.

    S2-03 draws "Underwriter note added in round 1: “8/28 Not in Upload”". The quote is dropped, and
    that is a recorded decision in `docs/tickets/LP-916.md`, not an oversight.
    """
    public = ConditionEventPublic.from_model(
        _event(
            ConditionEventKind.CONDITION_NOTE_ADDED,
            {
                "notes_added": 1,
                "lender_code": "6637",
                "text": "8/28 Not in Upload",
                "verbatim_text": "Provide the earnest money deposit",
            },
        )
    )

    assert public.notes_added == 1, "the count is what the sentence needs"
    body = public.model_dump()
    assert "lender_code" not in body, "an open string has no place in this projection"
    rendered = str(body)
    assert "Not in Upload" not in rendered
    assert "earnest money" not in rendered


# --------------------------------------------------------------------------- #
# What only the endpoint can resolve
# --------------------------------------------------------------------------- #


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


async def test_the_actor_is_named_and_a_system_event_is_not(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """ "— Priya Raman" NEEDS A NAME, AND `actor_user_id` IS A UUID.

    Resolved through `resolve_user_names`, the helper `overlay_admin.py` already shares, whose own
    docstring gives the reason a second lookup may not exist: "two lookups would eventually give one
    actor two names."

    AND NULL STAYS NULL. A system event has no actor — "a parse task has no actor, and naming the
    processor who uploaded the sheet would make the trail say something untrue" — so the line must be
    able to say what happened without attributing it to whoever touched the file last.
    """
    company = await make_company(db_session)
    loan_file = await make_loan_file(db_session, company=company)
    round_ = await make_round(db_session, company=company, loan_file=loan_file, round_number=2)
    condition = await make_condition(
        db_session, company=company, loan_file=loan_file, round_=round_
    )
    user = User(
        company_id=company.id,
        email=f"u-{uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("irrelevant"),
        first_name="Priya",
        last_name="Raman",
        role=UserRole.PROCESSOR,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        ConditionEvent(
            company_id=company.id,
            loan_file_id=loan_file.id,
            condition_id=condition.id,
            kind=ConditionEventKind.CONDITION_PREP_MOVED,
            actor_user_id=user.id,
            detail={"prep_status_from": "to_do", "prep_status_to": "waiting"},
        )
    )
    db_session.add(
        ConditionEvent(
            company_id=company.id,
            loan_file_id=loan_file.id,
            condition_id=condition.id,
            round_id=round_.id,
            kind=ConditionEventKind.CONDITION_SEEN_AGAIN,
            actor_user_id=None,
            detail={"lender_code": "7086"},
        )
    )
    await db_session.flush()

    auth = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    response = await client.get(f"{API}/conditions/{condition.id}/events", headers=auth)

    assert response.status_code == 200, response.text
    by_kind = {row["kind"]: row for row in response.json()}
    assert by_kind["condition_prep_moved"]["actor_name"] == "Priya Raman"
    assert by_kind["condition_seen_again"]["actor_name"] is None, "a system event names nobody"


async def test_the_round_number_comes_from_the_events_round_not_from_detail(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """ "Seen again in round 2" NEEDS A NUMBER THE DETAIL DOES NOT HOLD.

    The import's condition-level writers store `lender_code` and `changed`; the round is on the event
    row as `round_id`. So the number is resolved by a join — and resolved for the whole history at
    once, because a sheet that opens on every row click cannot afford a query per line.
    """
    company = await make_company(db_session)
    loan_file = await make_loan_file(db_session, company=company)
    round_ = await make_round(db_session, company=company, loan_file=loan_file, round_number=2)
    condition = await make_condition(
        db_session, company=company, loan_file=loan_file, round_=round_
    )
    user = User(
        company_id=company.id,
        email=f"u-{uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("irrelevant"),
        first_name="Test",
        last_name="Processor",
        role=UserRole.PROCESSOR,
        is_active=True,
    )
    db_session.add(user)
    db_session.add(
        ConditionEvent(
            company_id=company.id,
            loan_file_id=loan_file.id,
            condition_id=condition.id,
            round_id=round_.id,
            kind=ConditionEventKind.CONDITION_SEEN_AGAIN,
            detail={"lender_code": "7086"},
        )
    )
    await db_session.flush()

    auth = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    response = await client.get(f"{API}/conditions/{condition.id}/events", headers=auth)

    assert response.status_code == 200, response.text
    (row,) = [r for r in response.json() if r["kind"] == "condition_seen_again"]
    assert row["round_number"] == 2, "resolved from round_id, which is where the round actually is"


async def test_another_company_cannot_read_a_conditions_history(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """404, never 403 — confirming the id exists would be an oracle over another tenant's rows."""
    company = await make_company(db_session)
    loan_file = await make_loan_file(db_session, company=company)
    round_ = await make_round(db_session, company=company, loan_file=loan_file, round_number=1)
    condition = await make_condition(
        db_session, company=company, loan_file=loan_file, round_=round_
    )

    stranger_company = await make_company(db_session, name="Stranger")
    stranger = User(
        company_id=stranger_company.id,
        email=f"u-{uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("irrelevant"),
        first_name="Not",
        last_name="Yours",
        role=UserRole.PROCESSOR,
        is_active=True,
    )
    db_session.add(stranger)
    await db_session.flush()

    response = await client.get(
        f"{API}/conditions/{condition.id}/events",
        headers={"Authorization": f"Bearer {create_access_token(stranger.id)}"},
    )

    assert response.status_code == 404, response.text


async def test_a_real_move_reaches_the_history_with_its_target_and_owner(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """THROUGH THE REAL WRITER, NOT A HAND-BUILT EVENT (LP-916 review).

    Every prep-move event above is built with `prep_status_from` / `prep_status_to`, while
    `move_prep_status` stored bare `from` / `to`. So each real move reached the sheet as "Moved" with
    no target, and S2-03's "Moved to Waiting on Borrower" could not be rendered at all.
    """
    company = await make_company(db_session)
    loan_file = await make_loan_file(db_session, company=company)
    round_ = await make_round(db_session, company=company, loan_file=loan_file, round_number=1)
    condition = await make_condition(
        db_session, company=company, loan_file=loan_file, round_=round_
    )
    user = User(
        company_id=company.id,
        email=f"u-{uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("irrelevant"),
        first_name="Priya",
        last_name="Raman",
        role=UserRole.PROCESSOR,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    auth = {"Authorization": f"Bearer {create_access_token(user.id)}"}

    moved = await client.post(
        f"{API}/conditions/{condition.id}/prep-status",
        headers=auth,
        json={"to": "waiting", "waiting_on": "borrower"},
    )
    assert moved.status_code == 200, moved.text
    response = await client.get(f"{API}/conditions/{condition.id}/events", headers=auth)

    assert response.status_code == 200, response.text
    (event,) = [row for row in response.json() if row["kind"] == "condition_prep_moved"]
    assert (event["prep_status_from"], event["prep_status_to"]) == ("to_do", "waiting")
    assert event["waiting_on"] == "borrower"
    assert event["actor_name"] == "Priya Raman"


def test_waiting_on_is_projected_for_a_move_only() -> None:
    """A closed vocabulary, on the one kind that means it — the same guard-by-kind as the two sources."""
    moved = ConditionEventPublic.from_model(
        _event(ConditionEventKind.CONDITION_PREP_MOVED, {"waiting_on": "title"})
    )
    other = ConditionEventPublic.from_model(
        _event(ConditionEventKind.CONDITION_OWNER_CHANGED, {"waiting_on": "title"})
    )
    bad = ConditionEventPublic.from_model(
        _event(ConditionEventKind.CONDITION_PREP_MOVED, {"waiting_on": "Alex Rivera"})
    )

    assert moved.waiting_on is not None and moved.waiting_on.value == "title"
    assert other.waiting_on is None
    assert bad.waiting_on is None, "an open string never travels"

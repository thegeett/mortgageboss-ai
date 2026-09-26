"""One round's history — `GET /condition-rounds/{round_id}/events` (LP-909 §4, screen S1-09).

⚠️ THIS ROUTE IS THE FIRST READER OF AN INDEX BUILT FOR IT IN LP-904.
`ix_condition_events_round_occurred` has carried the comment "One round's history in time order — the
shape the round-details sheet reads (S1-09)" since `condition_events` was created, and nothing ever
read it. Every event insert — per created condition, per seen-again, per note, per round transition —
paid for an index serving a query that did not exist.

⚠️ AND THE HARDEST THING TO GET RIGHT HERE IS WHAT DOES *NOT* COME BACK. `ConditionEvent.detail` is
classified NPI: the model calls it "what changed, which is the lender's text",
`readonly.condition_events` drops it whole rather than scrubbing it, and `condition_import.py` states
the rule at its own write site. A history panel is not a reason to open that door, so the schema
projects named scalars — and `test_the_lenders_words_do_not_travel` is what makes that a guarantee
rather than a description.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import uuid4

import pytest
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.main import app
from app.models import Company, User, UserRole
from app.models.base import utcnow
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_round import ConditionRound, ConditionRoundCompleteness
from app.services.condition_rounds import create_round_from_paste
from app.services.loan_files import create_loan_file
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.fixture_helpers import portal_excerpt


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


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _url(round_id: object) -> str:
    return f"/api/v1/condition-rounds/{round_id}/events"


async def _user(db: AsyncSession, *, slug: str) -> tuple[Company, str]:
    company = Company(name=slug.title(), slug=slug)
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id,
        email=f"u@{slug}.com",
        hashed_password=hash_password("irrelevant"),
        first_name="Test",
        last_name="User",
        role=UserRole.PROCESSOR,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return company, create_access_token(user.id)


async def _round(db: AsyncSession, *, slug: str) -> tuple[ConditionRound, Company, str]:
    """A pasted round, which already carries TWO events of its own.

    ⚠️ TWO, NOT ONE, AND THIS DOCSTRING SAID ONE. `create_round_from_paste` parses INLINE — the rules
    read the text in the request — so it writes `ROUND_RECEIVED` and then `ROUND_PARSED` before a test
    adds anything. The first version of the ordering test below asserted an exact three-element list
    against this fixture and failed on the event it had not accounted for.

    Worth stating rather than quietly fixing: the test was right about the property and wrong about
    the fixture, so it broke on a correct implementation.
    """
    company, token = await _user(db, slug=slug)
    loan_file = await create_loan_file(db, company_id=company.id)
    round_ = await create_round_from_paste(
        db,
        loan_file=loan_file,
        text=portal_excerpt(),
        completeness=ConditionRoundCompleteness.PARTIAL,
    )
    return round_, company, token


async def _event(
    db: AsyncSession,
    *,
    round_: ConditionRound,
    company: Company,
    kind: ConditionEventKind,
    detail: dict[str, object],
    minutes: int,
) -> None:
    """Append an event at a controlled time, so ordering is asserted rather than assumed."""
    db.add(
        ConditionEvent(
            company_id=company.id,
            loan_file_id=round_.loan_file_id,
            round_id=round_.id,
            kind=kind,
            detail=detail,
            occurred_at=utcnow() + timedelta(minutes=minutes),
        )
    )
    await db.flush()


# --------------------------------------------------------------------------- #
# CRITICAL: the lender's words must not reach this response
# --------------------------------------------------------------------------- #


async def test_the_lenders_words_do_not_travel(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """⚠️ THE ASSERTION THE WHOLE SCHEMA DESIGN EXISTS FOR, AND THE ONE THAT MAKES IT A GUARANTEE.

    `detail` is free-form JSONB and NPI-classified. Every current writer keeps it to counts and
    identifiers — `condition_import.py` says so at its own write site ("WHAT CHANGED, NOT THE
    WORDING") — but the column CAN hold anything, and a schema that passed the dict through would
    export whatever a future writer put there, through a door built for a history panel.

    So this writes lender text into `detail` deliberately and asserts it does not come back. The
    projection is an allow-list of named scalars; anything else stays server-side. Without this, the
    projection is a description of current behaviour rather than a boundary.
    """
    round_, company, token = await _round(db_session, slug="events-npi")
    await _event(
        db_session,
        round_=round_,
        company=company,
        kind=ConditionEventKind.CONDITION_NOTE_ADDED,
        detail={
            "notes_added": 1,
            # The shapes a real writer might reach for, all of them the lender's or borrower's words.
            "text": "Provide an additional bank statement for Alex Rivera, account #9912.",
            "verbatim_text": "Short funds to close. Document sufficient funds.",
            "borrower": "Alex Rivera",
        },
        minutes=1,
    )

    response = await client.get(_url(round_.id), headers=_auth(token))

    assert response.status_code == 200, response.text
    body = response.text
    assert "Alex Rivera" not in body
    assert "account #9912" not in body
    assert "Short funds to close" not in body
    # And the container itself never appears, so a future key cannot ride along unnoticed.
    assert "detail" not in body
    assert "verbatim_text" not in body


async def test_only_the_named_scalars_are_exposed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The allow-list, stated as a set. A new key added to the response is a decision somebody makes,
    the same way `_MIRRORED` and the readonly EXCLUDED set are hand-written lists."""
    round_, _company, token = await _round(db_session, slug="events-fields")

    response = await client.get(_url(round_.id), headers=_auth(token))

    assert response.status_code == 200, response.text
    assert set(response.json()[0]) == {
        "kind",
        "occurred_at",
        "actor_user_id",
        "source_kind",
        "reader",
        "reader_version",
        "rows",
        "duplicates_dropped",
        "round_number",
        "created",
        "seen_again",
        "from_status",
        "filled_from",
    }


# --------------------------------------------------------------------------- #
# What the history actually says
# --------------------------------------------------------------------------- #


async def test_the_history_reads_oldest_first(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """⚠️ OLDEST FIRST, WHICH IS THE OPPOSITE OF THE ROUND STRIP. A history is read downwards as a
    sequence — pasted, then imported, then the PDF attached — so newest-first would run the story
    backwards. `list_rounds` is newest-first because a strip answers "what is current"; this answers
    "what happened", and the two orders are not interchangeable."""
    round_, company, token = await _round(db_session, slug="events-order")
    await _event(
        db_session,
        round_=round_,
        company=company,
        kind=ConditionEventKind.ROUND_IMPORTED,
        detail={"round_number": 2, "rows": 6, "created": 0, "seen_again": 6},
        minutes=2,
    )
    await _event(
        db_session,
        round_=round_,
        company=company,
        kind=ConditionEventKind.ROUND_ENRICHED,
        detail={"filled_from": "pdf"},
        minutes=4,
    )

    response = await client.get(_url(round_.id), headers=_auth(token))

    kinds = [event["kind"] for event in response.json()]

    # ⚠️ A RELATION OVER THE SEQUENCE, NOT AN EXACT LIST. The first version asserted exactly three
    # kinds and failed on a correct implementation: a pasted round parses inline, so `ROUND_PARSED`
    # sits between received and imported. Pinning the exact list makes this test break whenever a
    # writer legitimately adds an event, which trains the next person to loosen it rather than read
    # it — and the property is the ORDER, not the census.
    order = {kind: index for index, kind in enumerate(kinds)}
    for earlier, later in (
        (ConditionEventKind.ROUND_RECEIVED, ConditionEventKind.ROUND_PARSED),
        (ConditionEventKind.ROUND_PARSED, ConditionEventKind.ROUND_IMPORTED),
        (ConditionEventKind.ROUND_IMPORTED, ConditionEventKind.ROUND_ENRICHED),
    ):
        assert order[earlier.value] < order[later.value], (
            f"{earlier.value} happened before {later.value} and must be listed before it — "
            f"a history read downwards must not run the story backwards. Got: {kinds}"
        )

    # And the timestamps are non-decreasing, which is the property the ordering rests on rather than
    # an accident of insertion order.
    stamps = [event["occurred_at"] for event in response.json()]
    assert stamps == sorted(stamps)


async def test_an_imports_numbers_come_through(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """S1-09's middle line is "Imported: 0 new, 6 seen again", composed from these three scalars."""
    round_, company, token = await _round(db_session, slug="events-import")
    await _event(
        db_session,
        round_=round_,
        company=company,
        kind=ConditionEventKind.ROUND_IMPORTED,
        detail={"round_number": 2, "rows": 6, "created": 0, "seen_again": 6},
        minutes=2,
    )

    response = await client.get(_url(round_.id), headers=_auth(token))

    imported = next(
        e for e in response.json() if e["kind"] == ConditionEventKind.ROUND_IMPORTED.value
    )
    assert imported["round_number"] == 2
    assert imported["created"] == 0
    assert imported["seen_again"] == 6


async def test_a_system_event_has_no_actor(client: AsyncClient, db_session: AsyncSession) -> None:
    """⚠️ NULL IS A FACT HERE, NOT MISSING DATA. The model says why: "a parse task has no actor, and
    naming the processor who uploaded the sheet as the actor of the parse would make the trail say
    something untrue." The history must be able to distinguish the reader from a person."""
    round_, company, token = await _round(db_session, slug="events-actor")
    await _event(
        db_session,
        round_=round_,
        company=company,
        kind=ConditionEventKind.ROUND_PARSED,
        detail={"reader": "uwm", "reader_version": "v1", "rows": 6},
        minutes=1,
    )

    response = await client.get(_url(round_.id), headers=_auth(token))

    parsed = next(e for e in response.json() if e["kind"] == ConditionEventKind.ROUND_PARSED.value)
    assert parsed["actor_user_id"] is None
    assert parsed["reader"] == "uwm"


async def test_a_malformed_detail_does_not_break_the_history(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """⚠️ A COUNT STORED AS A STRING BECOMES None, NEVER A COERCION AND NEVER A 500. `detail` is
    written by six call sites and nothing constrains its shapes, so the projection reads defensively:
    `"6"` is not 6, and inventing that agreement would be this layer asserting something the writers
    do not guarantee. A history panel must not fail because one writer differed."""
    round_, company, token = await _round(db_session, slug="events-malformed")
    await _event(
        db_session,
        round_=round_,
        company=company,
        kind=ConditionEventKind.ROUND_IMPORTED,
        detail={"created": "0", "seen_again": True, "rows": 6},
        minutes=2,
    )

    response = await client.get(_url(round_.id), headers=_auth(token))

    assert response.status_code == 200, response.text
    imported = next(
        e for e in response.json() if e["kind"] == ConditionEventKind.ROUND_IMPORTED.value
    )
    assert imported["created"] is None, "a string is not an int"
    # ⚠️ `True` IS AN `int` IN PYTHON, which is why `_as_int` excludes bool explicitly. Without that
    # check a flag would render as the count 1.
    assert imported["seen_again"] is None, "a bool is not a count"
    assert imported["rows"] == 6, "the well-formed keys still come through"


# --------------------------------------------------------------------------- #
# CRITICAL: cross-tenant isolation
# --------------------------------------------------------------------------- #


async def test_another_companys_round_is_a_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """404, not 403 — `get_scoped_round` filters `company_id` INSIDE the statement, so another
    tenant's round is unfetchable rather than fetched and then refused. Distinguishing the two would
    confirm the id exists, which is an oracle over another tenant's rows."""
    round_a, _company_a, _token_a = await _round(db_session, slug="events-tenant-a")
    _company_b, token_b = await _user(db_session, slug="events-tenant-b")

    response = await client.get(_url(round_a.id), headers=_auth(token_b))

    assert response.status_code == 404


async def test_an_unauthenticated_read_is_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    round_, _company, _token = await _round(db_session, slug="events-anon")

    response = await client.get(_url(round_.id))

    assert response.status_code == 401


async def test_an_unknown_round_is_a_404(client: AsyncClient, db_session: AsyncSession) -> None:
    _company, token = await _user(db_session, slug="events-missing")

    response = await client.get(_url(uuid4()), headers=_auth(token))

    assert response.status_code == 404

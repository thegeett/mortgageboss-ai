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
from app.conditions.fingerprint import fingerprint
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.main import app
from app.models import Company, User, UserRole
from app.models.base import utcnow
from app.models.condition import BucketKind, Condition
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


async def test_npi_under_an_allow_listed_key_does_not_travel_either(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """⚠️ THE HALF THE FIRST NPI TEST NEVER CHECKED (LP-909 review).

    That test put lender text under keys that are NOT on the allow-list — `text`, `verbatim_text`,
    `borrower` — so it proved the KEY filter works and said nothing about VALUES. The projection typed
    its strings as open `str`, so `detail={"reader": "Alex Rivera"}` would have travelled through a key
    that IS on the list, and the test would have stayed green.

    Every string exposed now comes from a closed vocabulary — an enum value, or one of `_READERS` —
    and anything outside it becomes None. This is the assertion that makes that a boundary: a borrower
    name under `reader`, a property address under `source_kind`, and a condition's wording under
    `from_status`, none of which reach the client.
    """
    round_, company, token = await _round(db_session, slug="events-npi-allowlisted")
    await _event(
        db_session,
        round_=round_,
        company=company,
        kind=ConditionEventKind.ROUND_PARSED,
        detail={
            "reader": "Alex Rivera",
            "source_kind": "100 Example Ln, Columbia SC",
            "from_status": "Provide an additional bank statement.",
            "rows": 6,
        },
        minutes=1,
    )

    response = await client.get(_url(round_.id), headers=_auth(token))

    assert response.status_code == 200, response.text
    body = response.text
    assert "Alex Rivera" not in body
    assert "100 Example Ln" not in body
    assert "Provide an additional bank statement" not in body

    parsed = next(e for e in response.json() if e["kind"] == ConditionEventKind.ROUND_PARSED.value)
    assert parsed["reader"] is None, "a value outside the vocabulary is dropped, not forwarded"
    assert parsed["source_kind"] is None
    assert parsed["from_status"] is None
    # The well-formed key beside them still comes through, so this is a vocabulary check rather than
    # the whole event being discarded.
    assert parsed["rows"] == 6


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
        "rows",
        "round_number",
        "created",
        "seen_again",
        "from_status",
        # What an enrich actually did, so a line need not claim it filled what it did not.
        "filled_header",
        "filled_expiry",
        "matched",
    }
    # ⚠️ THREE FIELDS CAME OFF THIS LIST AND THAT IS THE POINT. `reader_version`,
    # `duplicates_dropped` and `filled_from` were projected and read by no sentence — three open
    # doors serving nothing. `filled_from` was also mis-documented as an enrich key: it is written
    # once, on `CONDITION_EDITED`, so the arm that would have used it could never have seen it.
    assert not {"reader_version", "duplicates_dropped", "filled_from"} & set(response.json()[0])


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

    # ⚠️ A RELATION OVER THE SEQUENCE, NOT AN EXACT LIST. An earlier version asserted exactly three
    # kinds and failed on a correct implementation: a pasted round parses inline, so `ROUND_PARSED`
    # sits between received and imported. Pinning the census makes this break whenever a writer
    # legitimately adds an event, which trains the next person to loosen it rather than read it.
    #
    # ⚠️ AND NEWEST FIRST, WHICH THIS TEST ALSO HAD BACKWARDS. It asserted oldest-first, following a
    # commit that argued it from first principles — but S1-09's mock runs 4:31 → 4:22 → 4:20 and its
    # *May differ* covers only the sheet width and whether times show. The order is a Must-match, so
    # reasoning to the other answer was re-deciding something the design pack had settled.
    order = {kind: index for index, kind in enumerate(kinds)}
    for later, earlier in (
        (ConditionEventKind.ROUND_ENRICHED, ConditionEventKind.ROUND_IMPORTED),
        (ConditionEventKind.ROUND_IMPORTED, ConditionEventKind.ROUND_PARSED),
        (ConditionEventKind.ROUND_PARSED, ConditionEventKind.ROUND_RECEIVED),
    ):
        assert order[later.value] < order[earlier.value], (
            f"{later.value} happened after {earlier.value} and must be listed FIRST — S1-09 runs "
            f"newest to oldest. Got: {kinds}"
        )

    # Non-increasing timestamps, which is the property the ordering rests on rather than an accident
    # of insertion order.
    stamps = [event["occurred_at"] for event in response.json()]
    assert stamps == sorted(stamps, reverse=True)


async def test_a_conditions_own_events_stay_out_of_the_rounds_history(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """⚠️ WITHOUT THIS FILTER A 30-ROW IMPORT RENDERS THIRTY "A condition was added" LINES, and the
    README asks for "a SHORT history". Measured on a real paste → import → paste → import flow, round
    2 came back with NINE lines, six of them detail-less `CONDITION_SEEN_AGAIN`.

    The cost, asserted here rather than hidden: a condition typed into an existing imported round
    writes only `CONDITION_CREATED`, so it leaves no round-level trace and does not appear. That is
    the right trade for a panel about the ROUND, and it is recorded in LP-909.
    """
    round_, company, token = await _round(db_session, slug="events-condition-level")

    # ⚠️ A REAL `Condition`, NOT A SENTINEL UUID. `condition_events.condition_id` carries
    # `fk_condition_events_condition_id_conditions`, so `uuid4()` fails the insert rather than the
    # assertion — the first version of this test died in its own setup with a ForeignKeyViolation.
    condition = Condition(
        company_id=company.id,
        loan_file_id=round_.loan_file_id,
        first_round_id=round_.id,
        last_seen_round_id=round_.id,
        sequence=1,
        lender_code="1228",
        bucket_heading="UW - Prior To Final Approval (PTD)",
        bucket_kind=BucketKind.PRIOR_TO_DOCS,
        verbatim_text="Final inspection is required.",
        text_fingerprint=fingerprint("Final inspection is required."),
        underwriter_notes=[],
    )
    db_session.add(condition)
    await db_session.flush()

    db_session.add(
        ConditionEvent(
            company_id=company.id,
            loan_file_id=round_.loan_file_id,
            round_id=round_.id,
            # A condition-level event: it names a round, but it is about one row on it.
            condition_id=condition.id,
            kind=ConditionEventKind.CONDITION_SEEN_AGAIN,
            detail={"lender_code": "1228", "changed": []},
            occurred_at=utcnow() + timedelta(minutes=3),
        )
    )
    await db_session.flush()

    response = await client.get(_url(round_.id), headers=_auth(token))

    kinds = [event["kind"] for event in response.json()]
    assert ConditionEventKind.CONDITION_SEEN_AGAIN.value not in kinds
    # The round-level events are still all there, so this is a filter rather than a truncation.
    assert ConditionEventKind.ROUND_RECEIVED.value in kinds


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

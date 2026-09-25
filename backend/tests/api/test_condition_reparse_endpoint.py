"""Reading a stored sheet again — `POST /condition-rounds/{round_id}/reparse` (LP-909 §3).

⚠️ THE ROUTE EXISTS BECAUSE TWO SCREENS ALREADY PROMISED IT. `RoundFailed` offers "Try again" and
`RoundReading`'s stranded copy says "you can try reading it again" — and until this endpoint there
was no way to re-read an existing round at all, so both took `onRetry` optionally and the dashboard
passed none. A paragraph offering a route with no control is a dead button wearing prose.

WHAT IS WORTH PINNING HERE, in order of how quietly it would break:

1. **The debounce depends on `updated_at` actually moving**, and for a stranded round nothing else
   on the row changes — so the one write the window is measured from is the one most likely not to
   happen. `test_a_second_press_inside_the_window_is_refused` and the `updated_at` test below are
   the pair that catch it.
2. **The window is the SERVER's.** The client's own guess was exactly `PARSE_SOFT_LIMIT_SECONDS`,
   which would call a round dead at the instant Celery raises `SoftTimeLimitExceeded`.
3. **Every refusal carries its own sentence** (spec §9.8), because "already imported", "it was
   pasted, there is no PDF" and "it is still being read" lead a processor to three different next
   actions.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import timedelta
from uuid import uuid4

import pytest
from app.conditions.limits import STRANDED_AFTER_SECONDS
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.main import app
from app.models import Company, User, UserRole
from app.models.base import utcnow
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_round import (
    ConditionRound,
    ConditionRoundCompleteness,
    ConditionRoundStatus,
    ConditionSourceKind,
)
from app.services.condition_rounds import (
    SheetBytes,
    create_round_from_paste,
    create_round_from_sheet,
)
from app.services.loan_files import create_loan_file
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.fixture_helpers import UWM_ROUND_1, portal_excerpt
from tests.conditions.uwm_pdf_fixture import render_uwm_pdf


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


@pytest.fixture(autouse=True)
def enqueued(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Capture the parse enqueue instead of reaching for a broker.

    ⚠️ AUTOUSE, BECAUSE EVERY SUCCESSFUL REPARSE ENQUEUES. A test that forgot this would make a real
    `.delay()` call against whatever broker the environment points at — which either hangs or fails
    for a reason that has nothing to do with the assertion being made.
    """
    from app.tasks import conditions as task_module

    calls: list[str] = []
    monkeypatch.setattr(
        task_module.parse_condition_round, "delay", lambda round_id: calls.append(round_id)
    )
    yield calls


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _url(round_id: object) -> str:
    return f"/api/v1/condition-rounds/{round_id}/reparse"


async def _user(db: AsyncSession, *, slug: str) -> tuple[Company, str]:
    company = Company(name=slug.title(), slug=f"{slug}-{uuid4().hex[:6]}")
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id,
        email=f"u-{uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("irrelevant"),
        first_name="Test",
        last_name="User",
        role=UserRole.PROCESSOR,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return company, create_access_token(user.id)


async def _pdf_round(
    db: AsyncSession,
    *,
    slug: str,
    status: ConditionRoundStatus = ConditionRoundStatus.PARSE_FAILED,
) -> tuple[ConditionRound, str]:
    """A round backed by real stored bytes, left in whatever state the test needs."""
    company, token = await _user(db, slug=slug)
    loan_file = await create_loan_file(db, company_id=company.id)
    round_ = await create_round_from_sheet(
        db,
        loan_file=loan_file,
        sheet=SheetBytes(
            content=render_uwm_pdf(UWM_ROUND_1), source_kind=ConditionSourceKind.PDF_UPLOAD
        ),
    )
    round_.status = status
    if status is ConditionRoundStatus.PARSE_FAILED:
        round_.parse_report = {
            "failure_kind": "unreadable",
            "failure_detail": "This PDF could not be opened.",
        }
    await db.flush()
    return round_, token


async def _events(db: AsyncSession, round_id: object) -> list[ConditionEvent]:
    result = await db.execute(
        select(ConditionEvent).where(ConditionEvent.round_id == round_id)  # type: ignore[arg-type]
    )
    return list(result.scalars().all())


async def _age(db: AsyncSession, round_: ConditionRound, *, seconds: float) -> None:
    """Backdate the row so the stranded window has passed.

    ⚠️ SETTING `updated_at` EXPLICITLY BEATS `onupdate`, which is what makes this work: SQLAlchemy
    applies `onupdate` only when no value is otherwise supplied. The same property is what lets the
    service write the timestamp deliberately.
    """
    round_.updated_at = utcnow() - timedelta(seconds=seconds)
    await db.flush()


# --------------------------------------------------------------------------- #
# The path that exists for screen S1-03's "Try again"
# --------------------------------------------------------------------------- #


async def test_a_failed_round_is_read_again(
    client: AsyncClient, db_session: AsyncSession, enqueued: list[str]
) -> None:
    """Back to `PARSING`, the failure cleared, and a reader actually queued."""
    round_, token = await _pdf_round(db_session, slug="reparse-failed")

    response = await client.post(_url(round_.id), headers=_auth(token))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == ConditionRoundStatus.PARSING.value
    # ⚠️ THE FAILURE IS CLEARED, NOT LEFT BEHIND. A stale `failure_kind` would render the failure
    # banner over a round that is mid-parse — the screen contradicting the status beside it.
    assert body["parse_report"]["failure_kind"] is None
    assert body["parse_report"]["failure_detail"] is None
    assert enqueued == [str(round_.id)], "a PARSING round with nothing queued is stranded"


async def test_the_reparse_is_recorded_as_its_own_event(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """⚠️ `ROUND_REPARSE_REQUESTED`, NOT `ROUND_RECEIVED` REUSED — and the distinction is what the
    enum member and its migration were spent on. Screen S1-09 renders this history, and "Condition
    sheet received" for an event where nothing was received is the class of statement this stage
    keeps deleting from comments and screens."""
    round_, token = await _pdf_round(db_session, slug="reparse-event")

    await client.post(_url(round_.id), headers=_auth(token))

    events = await _events(db_session, round_.id)
    reparse = [e for e in events if e.kind is ConditionEventKind.ROUND_REPARSE_REQUESTED]
    assert len(reparse) == 1
    # Metadata only (spec §9.5): where it came from, never the sheet's text.
    assert reparse[0].detail == {"from_status": ConditionRoundStatus.PARSE_FAILED.value}
    assert reparse[0].actor_user_id is not None, "a person asked for this, unlike a parse"


# --------------------------------------------------------------------------- #
# The debounce — and the write it silently depends on
# --------------------------------------------------------------------------- #


async def test_a_stranded_round_can_be_read_again(
    client: AsyncClient, db_session: AsyncSession, enqueued: list[str]
) -> None:
    """A round that has sat in `PARSING` past the window is genuinely abandoned: the worker is dead
    by `PARSE_HARD_LIMIT_SECONDS` and nothing will move it."""
    round_, token = await _pdf_round(
        db_session, slug="reparse-stranded", status=ConditionRoundStatus.PARSING
    )
    await _age(db_session, round_, seconds=STRANDED_AFTER_SECONDS + 60)

    response = await client.post(_url(round_.id), headers=_auth(token))

    assert response.status_code == 200, response.text
    assert enqueued == [str(round_.id)]


async def test_a_round_still_being_read_is_refused(
    client: AsyncClient, db_session: AsyncSession, enqueued: list[str]
) -> None:
    """⚠️ THE CLIENT USED TO CALL THIS DEAD. `STRANDED_AFTER_MS` was 5 minutes — exactly
    `PARSE_SOFT_LIMIT_SECONDS` — so the UI offered "Try again" at the instant Celery raises
    `SoftTimeLimitExceeded`, with 60 seconds of hard-limit runway left in which the task could still
    finish or settle `PARSE_FAILED` itself with a real reason. Reparsing then would have raced a
    live worker rather than rescued a stuck one."""
    round_, token = await _pdf_round(
        db_session, slug="reparse-young", status=ConditionRoundStatus.PARSING
    )
    await _age(db_session, round_, seconds=STRANDED_AFTER_SECONDS - 60)

    response = await client.post(_url(round_.id), headers=_auth(token))

    assert response.status_code == 409
    assert "still being read" in response.text
    assert enqueued == [], "a refused reparse must not queue a second reader"


async def test_a_second_press_inside_the_window_is_refused(
    client: AsyncClient, db_session: AsyncSession, enqueued: list[str]
) -> None:
    """⚠️ WHAT MAKES THIS IDEMPOTENT IN THE SENSE THAT MATTERS: pressing twice cannot produce two
    readers. The first reparse bumps `updated_at`, so the second lands inside the window and is
    refused WITH A REASON.

    Measured from `updated_at` rather than `created_at` for exactly this. From `created_at` a
    stranded round stays reparsable forever, so the second press would queue a second parse — and
    while both are guarded on `PARSING` so only one settles, the loser writes nothing and SAYS
    nothing, which is a control that appears to work and reports no outcome.
    """
    round_, token = await _pdf_round(db_session, slug="reparse-twice")

    first = await client.post(_url(round_.id), headers=_auth(token))
    assert first.status_code == 200

    second = await client.post(_url(round_.id), headers=_auth(token))

    assert second.status_code == 409
    assert "still being read" in second.text
    assert enqueued == [str(round_.id)], "the second press must not queue a second reader"


async def test_the_reparse_moves_updated_at_even_when_nothing_else_changes(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """⚠️ THE WRITE THE WHOLE DEBOUNCE RESTS ON, AND THE ONE MOST LIKELY NOT TO HAPPEN (LP-909
    review).

    `TimestampMixin.updated_at` has `onupdate=utcnow`, but that is Python-side and fires only when
    SQLAlchemy actually EMITS an UPDATE — which it does only if some value genuinely changed. This
    round is the case where nothing does: it is ALREADY `PARSING`, so the status assignment is a
    no-op, and its `parse_report` ALREADY carries both failure keys as `None`, so the new dict the
    service builds compares equal to the old one.

    Without the service writing `updated_at` deliberately, no UPDATE is issued, the timestamp stays
    put, and the debounce above silently does nothing — a processor could queue a reader per click.
    So this is deliberately the one round shape where the explicit write is the ONLY thing that can
    move the row.
    """
    round_, token = await _pdf_round(
        db_session, slug="reparse-touch", status=ConditionRoundStatus.PARSING
    )
    round_.parse_report = {"failure_kind": None, "failure_detail": None}
    await _age(db_session, round_, seconds=STRANDED_AFTER_SECONDS + 60)
    before = round_.updated_at

    response = await client.post(_url(round_.id), headers=_auth(token))
    assert response.status_code == 200, response.text

    await db_session.refresh(round_)
    assert round_.updated_at > before, (
        "nothing else on this row changed, so only the service's explicit write can have moved it — "
        "and if it did not move, the debounce is inert"
    )


# --------------------------------------------------------------------------- #
# Refusals — each with its own sentence (spec §9.8)
# --------------------------------------------------------------------------- #


async def test_a_pasted_round_is_refused_because_there_is_no_pdf(
    client: AsyncClient, db_session: AsyncSession, enqueued: list[str]
) -> None:
    """⚠️ REFUSED BY NAME RATHER THAN LET THROUGH. `parse_round` reads the sheet from STORAGE, and a
    pasted round has no stored bytes — `raw_text` is its source. Letting it through would settle
    `bytes_unavailable` and blame storage for something that was never there, when the true answer
    is "paste them again, or upload the lender's PDF"."""
    company, token = await _user(db_session, slug="reparse-paste")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    round_ = await create_round_from_paste(
        db_session,
        loan_file=loan_file,
        text=portal_excerpt(),
        completeness=ConditionRoundCompleteness.PARTIAL,
    )
    round_.status = ConditionRoundStatus.PARSE_FAILED
    await db_session.flush()

    response = await client.post(_url(round_.id), headers=_auth(token))

    assert response.status_code == 409
    assert "no stored sheet" in response.text
    assert enqueued == []


async def test_a_draft_is_refused_and_told_what_to_do_instead(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """⚠️ `DRAFT` IS DELIBERATELY NOT REPARSABLE. Re-reading in place would silently replace rows a
    processor may already have edited — `update_draft` refuses a stale write for exactly that
    reason, and a reparse that ignored it would be the same overwrite through a different door. The
    honest route is discard and upload again: a new round, a new number, the old one still visible.
    """
    round_, token = await _pdf_round(
        db_session, slug="reparse-draft", status=ConditionRoundStatus.DRAFT
    )

    response = await client.post(_url(round_.id), headers=_auth(token))

    assert response.status_code == 409
    assert "discard this round and upload the sheet again" in response.text


async def test_an_imported_round_is_refused(client: AsyncClient, db_session: AsyncSession) -> None:
    """Its rows became the file's conditions, and ADR-404 forbids taking those back."""
    round_, token = await _pdf_round(
        db_session, slug="reparse-imported", status=ConditionRoundStatus.IMPORTED
    )

    response = await client.post(_url(round_.id), headers=_auth(token))

    assert response.status_code == 409
    assert "part of the file" in response.text


async def test_a_discarded_round_is_refused(client: AsyncClient, db_session: AsyncSession) -> None:
    round_, token = await _pdf_round(
        db_session, slug="reparse-discarded", status=ConditionRoundStatus.DISCARDED
    )

    response = await client.post(_url(round_.id), headers=_auth(token))

    assert response.status_code == 409
    assert "discarded" in response.text.lower()


async def test_a_broker_that_refuses_the_reparse_fails_the_round_rather_than_stranding_it(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """⚠️ THE WORST VERSION OF THE STRANDED ROUND, WHICH IS WHY THIS ENQUEUE IS GUARDED WHERE THE
    UPLOAD DOOR'S IS NOT. The round is committed back to `PARSING` BEFORE the enqueue, so a broker
    that is down strands the round the processor just asked to rescue — they pressed "Try again" and
    watched it hang a second time.

    kombu's `OperationalError`, not `sqlalchemy.exc`'s: two unrelated classes share the name and
    `.delay()` raises kombu's, so catching the other would be a guard that never fires.
    """
    from app.tasks import conditions as task_module
    from kombu.exceptions import OperationalError

    def _broker_down(_round_id: str) -> None:
        raise OperationalError("broker unreachable")

    monkeypatch.setattr(task_module.parse_condition_round, "delay", _broker_down)

    round_, token = await _pdf_round(db_session, slug="reparse-broker")

    response = await client.post(_url(round_.id), headers=_auth(token))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == ConditionRoundStatus.PARSE_FAILED.value
    assert body["parse_report"]["failure_kind"] == "enqueue_failed"
    # ⚠️ THE SENTENCE MUST NOT BLAME THE LENDER'S PDF, which was read fine or never read at all.
    assert "could not be queued" in body["parse_report"]["failure_detail"]
    assert "broker" not in body["parse_report"]["failure_detail"].lower()


# --------------------------------------------------------------------------- #
# CRITICAL: cross-tenant isolation
# --------------------------------------------------------------------------- #


async def test_another_companys_round_is_a_404(
    client: AsyncClient, db_session: AsyncSession, enqueued: list[str]
) -> None:
    """404, not 403 — `get_scoped_round` filters `company_id` INSIDE the statement, so another
    tenant's round is unfetchable rather than fetched and then refused. Distinguishing the two would
    confirm the id exists, which is an oracle over another tenant's rows."""
    round_a, _token_a = await _pdf_round(db_session, slug="reparse-tenant-a")
    _company_b, token_b = await _user(db_session, slug="reparse-tenant-b")

    response = await client.post(_url(round_a.id), headers=_auth(token_b))

    assert response.status_code == 404
    assert enqueued == []


async def test_an_unauthenticated_reparse_is_refused(
    client: AsyncClient, db_session: AsyncSession, enqueued: list[str]
) -> None:
    round_, _token = await _pdf_round(db_session, slug="reparse-anon")

    response = await client.post(_url(round_.id))

    assert response.status_code == 401
    assert enqueued == []


async def test_an_unknown_round_is_a_404(client: AsyncClient, db_session: AsyncSession) -> None:
    _company, token = await _user(db_session, slug="reparse-missing")

    response = await client.post(_url(uuid4()), headers=_auth(token))

    assert response.status_code == 404

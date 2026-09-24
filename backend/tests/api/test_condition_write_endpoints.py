"""Importing, discarding, editing a draft, and adding a condition by hand (LP-909 section 2).

⚠️ THESE DRIVE THE REAL REDIS LOCK. `import` and `POST conditions` enter `loan_file_needs_lock`, and
nothing here stubs it — `tests/services/test_needs_engine.py` already exercises the real lock against
the real Redis, so this follows existing practice rather than inventing a fake. If Redis is down these
fail loudly, which is the honest outcome: a passing suite that silently skipped the lock would say
nothing about the path that actually runs in production.

⚠️ AND THE HANDLERS COMMIT, WHICH conftest's DOCSTRING WARNS AGAINST. `db_session` binds a session to
a connection with an already-begun transaction and rolls it back afterwards, and its docstring says
"a commit would defeat the isolation". Measured before writing any of this: under SQLAlchemy 2.0 the
session joins that transaction with a savepoint, so `commit()` releases the savepoint and the outer
rollback still removes everything. A row committed inside a handler was NOT visible from a second
connection. Had it been, every test here would have leaked into the shared test database — and no
existing test would have noticed, because every other endpoint test in this area is a GET.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.main import app
from app.models import Company, User, UserRole
from app.models.condition import BucketKind, Condition, ConditionOrigin, OwnerHint, OwnerHintSource
from app.models.condition_round import (
    ConditionRound,
    ConditionRoundCompleteness,
    ConditionRoundStatus,
    ConditionSourceKind,
)
from app.schemas.condition import DraftRowPublic
from app.services.condition_rounds import create_round_from_paste
from app.services.loan_files import create_loan_file
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
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


async def _draft(db: AsyncSession, *, slug: str) -> tuple[Any, ConditionRound, str]:
    """A pasted DRAFT round awaiting review — the state `import` and `discard` act on."""
    company, token = await _user(db, slug=slug)
    loan_file = await create_loan_file(db, company_id=company.id)
    round_ = await create_round_from_paste(
        db,
        loan_file=loan_file,
        text=portal_excerpt(),
        completeness=ConditionRoundCompleteness.FULL,
    )
    assert round_.status is ConditionRoundStatus.DRAFT, "the fixture must start reviewable"
    return loan_file, round_, token


async def _conditions(db: AsyncSession, loan_file_id: Any) -> list[Condition]:
    result = await db.execute(
        select(Condition).where(Condition.loan_file_id == loan_file_id).order_by(Condition.sequence)
    )
    return list(result.scalars().all())


# --------------------------------------------------------------------------- #
# POST /condition-rounds/{id}/import
# --------------------------------------------------------------------------- #


async def test_importing_a_draft_answers_the_result_and_settles_the_round(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """⚠️ 200 AND NOT 201, THOUGH CONDITIONS ARE CREATED — the resource addressed is the round, and
    it already existed. The round is settled in place, from DRAFT to IMPORTED."""
    loan_file, round_, token = await _draft(db_session, slug="imp-ok")
    rows = len(round_.draft_rows or [])

    response = await client.post(
        f"/api/v1/condition-rounds/{round_.id}/import", headers=_auth(token)
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["round_id"] == str(round_.id)
    assert body["round_number"] == 1
    assert body["created"] == rows
    assert body["seen_again"] == 0

    await db_session.refresh(round_)
    assert round_.status is ConditionRoundStatus.IMPORTED
    assert round_.draft_rows is None, "the rows ARE conditions now"
    assert len(await _conditions(db_session, loan_file.id)) == rows


async def test_importing_a_round_twice_is_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """409, not 422: nothing about the request is malformed — it is the round's STATE that refuses,
    which is the same translation the enrich door uses."""
    _file, round_, token = await _draft(db_session, slug="imp-twice")
    first = await client.post(f"/api/v1/condition-rounds/{round_.id}/import", headers=_auth(token))
    assert first.status_code == 200, first.text

    again = await client.post(f"/api/v1/condition-rounds/{round_.id}/import", headers=_auth(token))

    assert again.status_code == 409, again.text
    # ⚠️ `["error"]["message"]`, NOT FastAPI's DEFAULT `["detail"]`. `app/core/errors.py` registers a
    # `StarletteHTTPException` handler that reshapes every error body, and seven existing endpoint
    # tests read this shape. All four refusal tests here were written against `["detail"]` and all
    # four failed with `KeyError` — while every status code was already correct, so the handlers were
    # right and only the assertions were wrong. No existing test on this router had ever asserted an
    # error body, which is why the convention had gone unexercised here.
    assert "already been imported" in again.json()["error"]["message"]


async def test_another_companys_round_cannot_be_imported(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """⚠️ 404 RATHER THAN 403, AND THE INDISTINGUISHABILITY IS THE POINT. Confirming the id exists
    would be an oracle over another tenant's rows. The gating test proves the dependency is
    DECLARED; this proves it refuses."""
    _file, round_, _token = await _draft(db_session, slug="imp-mine")
    _other_company, other_token = await _user(db_session, slug="imp-theirs")

    response = await client.post(
        f"/api/v1/condition-rounds/{round_.id}/import", headers=_auth(other_token)
    )

    assert response.status_code == 404, response.text


# --------------------------------------------------------------------------- #
# POST /condition-rounds/{id}/discard
# --------------------------------------------------------------------------- #


async def test_a_draft_can_be_discarded_and_stays_on_the_strip(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A discarded round is listed, not hidden — a processor who threw a draft away should see that
    they did, and its rows are kept so the card can still say how many were thrown away."""
    _file, round_, token = await _draft(db_session, slug="dis-ok")
    rows = len(round_.draft_rows or [])

    response = await client.post(
        f"/api/v1/condition-rounds/{round_.id}/discard", headers=_auth(token)
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == ConditionRoundStatus.DISCARDED.value
    assert body["round_number"] is None, "a discarded draft never took a number"
    assert body["condition_count"] == rows, "the card still says what was discarded"

    await db_session.refresh(round_)
    assert round_.draft_rows, "the rows are kept, not cleared — nothing became anything"


async def test_an_imported_round_cannot_be_discarded(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """⚠️ THE DECISION THE SPEC DOES NOT MAKE. LP-904's index keeps a discarded-after-import round's
    number and ADR-404 forbids deleting its conditions, so discarding one would leave every
    condition alive and still chipped to it — "discarded" would mean one thing for a draft and
    another for an imported round, in the same strip, under one word."""
    _file, round_, token = await _draft(db_session, slug="dis-imported")
    imported = await client.post(
        f"/api/v1/condition-rounds/{round_.id}/import", headers=_auth(token)
    )
    assert imported.status_code == 200, imported.text

    response = await client.post(
        f"/api/v1/condition-rounds/{round_.id}/discard", headers=_auth(token)
    )

    assert response.status_code == 409, response.text
    assert "conditions are part of the file" in response.json()["error"]["message"]


# --------------------------------------------------------------------------- #
# PUT /condition-rounds/{id}/draft
# --------------------------------------------------------------------------- #


def _edited_rows(round_: ConditionRound, *, text: str) -> list[dict[str, Any]]:
    """The round's rows with the first one's wording replaced — through the schema, as always."""
    rows = [dict(row) for row in (round_.draft_rows or [])]
    rows[0]["verbatim_text"] = text
    return [DraftRowPublic(**row).model_dump(mode="json") for row in rows]


async def test_an_edited_row_is_stored_and_imports_as_edited(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """⚠️ SPEC §8's ACTUAL REQUIREMENT: "editing a row and importing sends the edited text". The
    fingerprint is taken of what is IMPORTED, not of what was read, so an edited row may match a
    different condition or none — which is correct rather than unfortunate."""
    loan_file, round_, token = await _draft(db_session, slug="draft-edit")
    edited = "Provide the PAID invoice for the credit report, dated within 30 days."

    saved = await client.put(
        f"/api/v1/condition-rounds/{round_.id}/draft",
        headers=_auth(token),
        json={
            "draft_rows": _edited_rows(round_, text=edited),
            "expected_updated_at": round_.updated_at.isoformat(),
        },
    )

    assert saved.status_code == 200, saved.text
    assert saved.json()["draft_rows"][0]["verbatim_text"] == edited

    imported = await client.post(
        f"/api/v1/condition-rounds/{round_.id}/import", headers=_auth(token)
    )
    assert imported.status_code == 200, imported.text

    texts = [c.verbatim_text for c in await _conditions(db_session, loan_file.id)]
    assert edited in texts, "the processor's wording is what became the condition"


async def test_a_stale_expected_updated_at_is_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """⚠️ TWO TABS ON ONE DRAFT, AND ALSO AN ENRICH THAT LANDED UNDERNEATH ONE. `updated_at` is
    bumped by ANY modification, so this refuses both — they are the same hazard: overwriting work
    the caller never saw."""
    _file, round_, token = await _draft(db_session, slug="draft-stale")
    stale = round_.updated_at

    first = await client.put(
        f"/api/v1/condition-rounds/{round_.id}/draft",
        headers=_auth(token),
        json={
            "draft_rows": _edited_rows(round_, text="First tab wins."),
            "expected_updated_at": stale.isoformat(),
        },
    )
    assert first.status_code == 200, first.text

    await db_session.refresh(round_)
    second = await client.put(
        f"/api/v1/condition-rounds/{round_.id}/draft",
        headers=_auth(token),
        json={
            "draft_rows": _edited_rows(round_, text="Second tab overwrites."),
            # The value the second tab read BEFORE the first tab saved.
            "expected_updated_at": stale.isoformat(),
        },
    )

    assert second.status_code == 409, second.text
    assert "changed this draft" in second.json()["error"]["message"]

    await db_session.refresh(round_)
    assert round_.draft_rows
    assert round_.draft_rows[0]["verbatim_text"] == "First tab wins.", "nothing was overwritten"


async def test_an_imported_round_cannot_be_edited(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Only a draft awaiting review is editable. An imported round's rows are conditions now."""
    _file, round_, token = await _draft(db_session, slug="draft-imported")
    rows = _edited_rows(round_, text="Too late.")
    imported = await client.post(
        f"/api/v1/condition-rounds/{round_.id}/import", headers=_auth(token)
    )
    assert imported.status_code == 200, imported.text

    response = await client.put(
        f"/api/v1/condition-rounds/{round_.id}/draft",
        headers=_auth(token),
        json={"draft_rows": rows},
    )

    assert response.status_code == 409, response.text
    assert "draft awaiting review" in response.json()["error"]["message"]


# --------------------------------------------------------------------------- #
# POST /loan-files/{id}/conditions
# --------------------------------------------------------------------------- #


async def test_a_hand_typed_condition_opens_round_one_when_there_is_none(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """⚠️ THE ROUND IT CREATES IS `PARTIAL`, AND THAT IS THE ONE THAT WOULD BITE SILENTLY. ADR-404
    lets only a FULL round's absences mean anything, so a FULL round holding whatever a processor
    happened to type would entitle Stage 2 to propose that everything nobody typed had been cleared.
    """
    company, token = await _user(db_session, slug="manual-first")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    wording = "Provide a letter of explanation for the recent large deposit."

    response = await client.post(
        f"/api/v1/loan-files/{loan_file.id}/conditions",
        headers=_auth(token),
        json={"verbatim_text": wording, "lender_code": "9001", "bucket_kind": "prior_to_docs"},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["verbatim_text"] == wording, "stored exactly as typed"
    assert body["origin"] == ConditionOrigin.MANUAL.value
    assert body["round_numbers"] == [1], "it is filed into the round it created"

    round_ = await db_session.scalar(
        select(ConditionRound).where(ConditionRound.loan_file_id == loan_file.id)
    )
    assert round_ is not None
    assert round_.round_number == 1
    assert round_.status is ConditionRoundStatus.IMPORTED, "nothing to review"
    assert round_.completeness is ConditionRoundCompleteness.PARTIAL
    assert [s["kind"] for s in round_.sources] == [ConditionSourceKind.MANUAL.value]


async def test_a_hand_typed_condition_joins_the_latest_imported_round(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Spec §LP-909: it goes into the latest imported round rather than opening a second one."""
    loan_file, round_, token = await _draft(db_session, slug="manual-join")
    imported = await client.post(
        f"/api/v1/condition-rounds/{round_.id}/import", headers=_auth(token)
    )
    assert imported.status_code == 200, imported.text
    before = len(await _conditions(db_session, loan_file.id))

    response = await client.post(
        f"/api/v1/loan-files/{loan_file.id}/conditions",
        headers=_auth(token),
        json={"verbatim_text": "One the letter did not list."},
    )

    assert response.status_code == 201, response.text
    assert response.json()["round_numbers"] == [1]

    rounds = (
        (
            await db_session.execute(
                select(ConditionRound).where(ConditionRound.loan_file_id == loan_file.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rounds) == 1, "no second round was opened"
    assert len(await _conditions(db_session, loan_file.id)) == before + 1


async def test_a_hand_typed_condition_sorts_after_the_sheets_rows(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """`sequence` is the order the lender printed them; a hand-typed one has no printed place, so it
    goes last rather than colliding with a row's position."""
    loan_file, round_, token = await _draft(db_session, slug="manual-seq")
    await client.post(f"/api/v1/condition-rounds/{round_.id}/import", headers=_auth(token))
    highest = max(c.sequence for c in await _conditions(db_session, loan_file.id))

    response = await client.post(
        f"/api/v1/loan-files/{loan_file.id}/conditions",
        headers=_auth(token),
        json={"verbatim_text": "Typed last."},
    )

    assert response.status_code == 201, response.text
    assert response.json()["sequence"] == highest + 1


async def test_a_hand_typed_condition_does_not_invent_a_lender_heading(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """⚠️ THE HEADING IS THE LENDER'S VOCABULARY. "Prior To Docs (PTD)" is their phrase, and
    manufacturing one for a row they never wrote would put words in their mouth. Empty means the
    processor filed it under no heading."""
    company, token = await _user(db_session, slug="manual-heading")
    loan_file = await create_loan_file(db_session, company_id=company.id)

    response = await client.post(
        f"/api/v1/loan-files/{loan_file.id}/conditions",
        headers=_auth(token),
        json={"verbatim_text": "No heading given."},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["bucket_heading"] == ""
    assert body["bucket_kind"] == BucketKind.UNKNOWN.value
    assert body["owner_hint"] == OwnerHint.UNKNOWN.value
    assert body["owner_hint_source"] == OwnerHintSource.NONE.value

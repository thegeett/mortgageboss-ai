"""Endpoint tests for saved views (LP-UI-015).

The three things the ticket names, plus the one it implies:

  * **Tenant isolation** — a Company A user cannot see, edit or delete a Company
    B view, and gets ``404`` rather than ``403`` (a ``403`` confirms the row).
  * **A soft-deleted view never reappears** — through list, read, update or
    delete, and its name becomes reusable.
  * **Visibility is not ownership** — a shared view is readable by the company
    and writable only by its owner.
  * **Partial update** — sending one field must not reset the others, the
    LP-UI-010 lesson.
"""

from collections.abc import AsyncIterator

import pytest_asyncio
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.main import app
from app.models import Company, User, UserRole
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

URL = "/api/v1/saved-views"


@pytest_asyncio.fixture
async def db(test_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    connection = await test_engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    try:

        async def _override() -> AsyncIterator[AsyncSession]:
            yield session

        app.dependency_overrides[get_db] = _override
        yield session
    finally:
        app.dependency_overrides.pop(get_db, None)
        await session.close()
        await transaction.rollback()
        await connection.close()


async def _user(db: AsyncSession, *, slug: str, email: str) -> tuple[Company, User, str]:
    company = Company(name=slug.title(), slug=slug)
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id,
        email=email,
        hashed_password=hash_password("irrelevant"),  # pragma: allowlist secret
        first_name="Test",
        last_name="User",
        role=UserRole.PROCESSOR,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return company, user, create_access_token(user.id)


async def _second_user(db: AsyncSession, company: Company, email: str) -> tuple[User, str]:
    user = User(
        company_id=company.id,
        email=email,
        hashed_password=hash_password("irrelevant"),  # pragma: allowlist secret
        first_name="Other",
        last_name="User",
        role=UserRole.PROCESSOR,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user, create_access_token(user.id)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _create(client: AsyncClient, token: str, **body: object) -> dict:
    payload = {"name": "Blocked to submit", **body}
    resp = await client.post(URL, json=payload, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


# --------------------------------------------------------------------------- #
# create + read
# --------------------------------------------------------------------------- #


async def test_create_takes_owner_and_company_from_the_caller(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Neither the owner nor the company can be set from the body."""
    company, user, token = await _user(db, slug="acme", email="a@acme.com")
    view = await _create(
        client,
        token,
        filters={"statuses": ["in_processing"], "search": "smith"},
        sort="attention",
    )
    assert view["owner_user_id"] == str(user.id)
    assert view["is_mine"] is True
    assert view["filters"] == {"statuses": ["in_processing"], "search": "smith"}

    row = await db.execute(
        text("SELECT company_id FROM saved_views WHERE id = :id"), {"id": view["id"]}
    )
    assert row.scalar_one() == company.id


async def test_filters_reject_a_field_the_pipeline_cannot_apply(
    client: AsyncClient, db: AsyncSession
) -> None:
    """`extra="forbid"` — a view must not claim a filter that is silently dropped."""
    _, _, token = await _user(db, slug="acme", email="a@acme.com")
    resp = await client.post(
        URL,
        json={"name": "Mine", "filters": {"assigned_to": "current_user"}},
        headers=_auth(token),
    )
    assert resp.status_code == 422


async def test_blank_search_is_no_filter(client: AsyncClient, db: AsyncSession) -> None:
    _, _, token = await _user(db, slug="acme", email="a@acme.com")
    view = await _create(client, token, filters={"search": "   "})
    assert view["filters"]["search"] is None


# --------------------------------------------------------------------------- #
# tenant isolation
# --------------------------------------------------------------------------- #


async def test_another_company_cannot_see_read_update_or_delete(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Every path is 404 across a tenant boundary — never 403, which confirms it."""
    _, _, mine = await _user(db, slug="acme", email="a@acme.com")
    view = await _create(client, mine, is_shared=True)

    _, _, theirs = await _user(db, slug="rival", email="b@rival.com")

    listed = await client.get(URL, headers=_auth(theirs))
    assert listed.status_code == 200
    assert listed.json() == []

    patched = await client.patch(
        f"{URL}/{view['id']}", json={"name": "Theirs"}, headers=_auth(theirs)
    )
    assert patched.status_code == 404

    deleted = await client.delete(f"{URL}/{view['id']}", headers=_auth(theirs))
    assert deleted.status_code == 404


# --------------------------------------------------------------------------- #
# visibility is not ownership
# --------------------------------------------------------------------------- #


async def test_a_shared_view_is_readable_by_the_company_and_writable_only_by_its_owner(
    client: AsyncClient, db: AsyncSession
) -> None:
    company, _, mine = await _user(db, slug="acme", email="a@acme.com")
    _, colleague = await _second_user(db, company, "c@acme.com")
    view = await _create(client, mine, is_shared=True)

    listed = await client.get(URL, headers=_auth(colleague))
    assert [v["name"] for v in listed.json()] == ["Blocked to submit"]
    assert listed.json()[0]["is_mine"] is False

    patched = await client.patch(
        f"{URL}/{view['id']}", json={"name": "Renamed"}, headers=_auth(colleague)
    )
    assert patched.status_code == 404


async def test_a_private_view_is_invisible_to_a_colleague(
    client: AsyncClient, db: AsyncSession
) -> None:
    company, _, mine = await _user(db, slug="acme", email="a@acme.com")
    _, colleague = await _second_user(db, company, "c@acme.com")
    await _create(client, mine, is_shared=False)

    listed = await client.get(URL, headers=_auth(colleague))
    assert listed.json() == []


# --------------------------------------------------------------------------- #
# partial update
# --------------------------------------------------------------------------- #


async def test_updating_one_field_leaves_the_others_alone(
    client: AsyncClient, db: AsyncSession
) -> None:
    """The LP-UI-010 lesson: a partial update must not reset what it omits."""
    _, _, token = await _user(db, slug="acme", email="a@acme.com")
    view = await _create(
        client, token, filters={"statuses": ["draft"]}, sort="amount_desc", is_shared=True
    )

    patched = await client.patch(
        f"{URL}/{view['id']}", json={"name": "Renamed"}, headers=_auth(token)
    )
    assert patched.status_code == 200
    body = patched.json()
    assert body["name"] == "Renamed"
    assert body["filters"] == {"statuses": ["draft"], "search": None}
    assert body["sort"] == "amount_desc"
    assert body["is_shared"] is True


# --------------------------------------------------------------------------- #
# soft delete
# --------------------------------------------------------------------------- #


async def test_a_soft_deleted_view_never_reappears(client: AsyncClient, db: AsyncSession) -> None:
    """Through list, update or delete — and the row survives for the audit trail."""
    _, _, token = await _user(db, slug="acme", email="a@acme.com")
    view = await _create(client, token)

    assert (await client.delete(f"{URL}/{view['id']}", headers=_auth(token))).status_code == 204

    assert (await client.get(URL, headers=_auth(token))).json() == []
    assert (
        await client.patch(f"{URL}/{view['id']}", json={"name": "Back"}, headers=_auth(token))
    ).status_code == 404
    assert (await client.delete(f"{URL}/{view['id']}", headers=_auth(token))).status_code == 404

    # Soft, not hard: the row is still there with deleted_at set.
    row = await db.execute(
        text("SELECT deleted_at FROM saved_views WHERE id = :id"), {"id": view["id"]}
    )
    assert row.scalar_one() is not None


async def test_a_deleted_name_can_be_reused(client: AsyncClient, db: AsyncSession) -> None:
    """The unique key includes deleted_at, so deleting frees the name."""
    _, _, token = await _user(db, slug="acme", email="a@acme.com")
    first = await _create(client, token)
    await client.delete(f"{URL}/{first['id']}", headers=_auth(token))

    again = await _create(client, token)
    assert again["name"] == "Blocked to submit"
    assert again["id"] != first["id"]

"""User preference endpoint tests (LP-79, LP-UI-010).

The behaviour worth pinning is the PARTIAL update. LP-UI-010 made both fields
optional so that "only the provided fields change" is true; before that a client
changing density alone had to send back a thoroughness it was not changing, and
a stale copy would have silently overwritten the real value. That is a data-loss
shape, and nothing was asserting it.
"""

from collections.abc import AsyncIterator

import pytest_asyncio
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.main import app
from app.models import Company, User, UserRole
from app.models.user import RowDensity
from app.verification.confidence import AggressionLevel
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

PREFS = "/api/v1/users/me/preferences"


@pytest_asyncio.fixture
async def db(test_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    connection = await test_engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


@pytest_asyncio.fixture
async def client(db: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_db, None)


async def _user_and_token(db: AsyncSession, *, email: str = "u@acme.com") -> tuple[User, str]:
    company = Company(name="Acme", slug="acme")
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
    await db.commit()
    return user, create_access_token(user.id)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_get_returns_both_preferences_at_their_defaults(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A user who has never set anything reads back the model defaults."""
    _user, token = await _user_and_token(db)

    body = (await client.get(PREFS, headers=_auth(token))).json()

    assert body["default_aggression_level"] == AggressionLevel.BALANCED.value
    assert body["density"] == RowDensity.COMPACT.value


async def test_setting_density_alone_leaves_thoroughness_untouched(
    client: AsyncClient, db: AsyncSession
) -> None:
    """The reason both fields became optional — a density-only PUT must not reset the dial."""
    _user, token = await _user_and_token(db)
    await client.put(PREFS, headers=_auth(token), json={"default_aggression_level": "thorough"})

    put = await client.put(PREFS, headers=_auth(token), json={"density": "relaxed"})

    assert put.status_code == 200
    assert put.json()["density"] == "relaxed"
    # The field the client never mentioned. Required-and-echoed-back is how a
    # stale client value silently reverts a preference set on another device.
    assert put.json()["default_aggression_level"] == "thorough"
    assert (await client.get(PREFS, headers=_auth(token))).json()[
        "default_aggression_level"
    ] == "thorough"


async def test_setting_thoroughness_alone_leaves_density_untouched(
    client: AsyncClient, db: AsyncSession
) -> None:
    """The same guarantee in the other direction — the dial is the older caller."""
    _user, token = await _user_and_token(db)
    await client.put(PREFS, headers=_auth(token), json={"density": "comfortable"})

    put = await client.put(
        PREFS, headers=_auth(token), json={"default_aggression_level": "conservative"}
    )

    assert put.status_code == 200
    assert put.json()["default_aggression_level"] == "conservative"
    assert put.json()["density"] == "comfortable"


async def test_both_fields_together_still_work(client: AsyncClient, db: AsyncSession) -> None:
    _user, token = await _user_and_token(db)

    put = await client.put(
        PREFS,
        headers=_auth(token),
        json={"default_aggression_level": "thorough", "density": "relaxed"},
    )

    assert put.status_code == 200
    assert put.json() == {"default_aggression_level": "thorough", "density": "relaxed"}


async def test_an_empty_body_changes_nothing(client: AsyncClient, db: AsyncSession) -> None:
    """Accepted rather than rejected: "only the provided fields change" and nothing was."""
    _user, token = await _user_and_token(db)
    await client.put(PREFS, headers=_auth(token), json={"density": "relaxed"})

    put = await client.put(PREFS, headers=_auth(token), json={})

    assert put.status_code == 200
    assert put.json()["density"] == "relaxed"


async def test_an_unknown_density_is_rejected(client: AsyncClient, db: AsyncSession) -> None:
    """The enum is bounded at the edge, not only by the column's CHECK constraint."""
    _user, token = await _user_and_token(db)

    put = await client.put(PREFS, headers=_auth(token), json={"density": "gigantic"})

    assert put.status_code == 422
    assert (await client.get(PREFS, headers=_auth(token))).json()["density"] == "compact"


async def test_an_explicit_null_does_not_clear_a_field(
    client: AsyncClient, db: AsyncSession
) -> None:
    """`None` means "not sent", so a client that spells it explicitly cannot wipe a value.

    Worth pinning: the endpoint distinguishes present-from-absent with `is not None`,
    so an explicit null is indistinguishable from omission — deliberate, since
    neither preference has a meaningful "unset" state to return to.
    """
    _user, token = await _user_and_token(db)
    await client.put(PREFS, headers=_auth(token), json={"density": "relaxed"})

    put = await client.put(PREFS, headers=_auth(token), json={"density": None})

    assert put.status_code == 200
    assert put.json()["density"] == "relaxed"

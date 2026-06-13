"""Pytest fixtures and configuration.

Database tests use an isolated test database (separate from the dev database,
auto-created if missing) and the **transaction-rollback isolation** pattern:
each test runs inside a transaction that is rolled back at the end, so tests
never commit and never see each other's data.
"""

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from app.core.config import settings
from app.main import app
from app.models import Base
from httpx import ASGITransport, AsyncClient
from sqlalchemy import NullPool, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """HTTP client for testing the FastAPI app."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


def _test_database_url() -> URL:
    """Derive the test database URL, separate from the dev database.

    Honors a ``TEST_DATABASE_URL`` env var if set; otherwise takes the
    configured (dev) database URL and appends ``_test`` to the database name.
    Never returns the dev database.
    """
    override = os.getenv("TEST_DATABASE_URL")
    if override:
        return make_url(override)
    dev_url = make_url(str(settings.database_url))
    return dev_url.set(database=f"{dev_url.database}_test")


async def _ensure_test_database_exists(url: URL) -> None:
    """Create the test database if it does not already exist.

    ``CREATE DATABASE`` cannot run inside a transaction, so we connect to the
    ``postgres`` maintenance database with AUTOCOMMIT and issue it there.
    """
    admin_engine = create_async_engine(
        url.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )
    try:
        async with admin_engine.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": url.database},
            )
            if not exists:
                # The identifier can't be parameterized, but it is derived from
                # our own settings (dev db name + "_test"), never user input.
                await conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    finally:
        await admin_engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def test_engine() -> AsyncIterator[AsyncEngine]:
    """Session-scoped engine pointed at an isolated test database.

    Creates the test database if needed, builds the whole schema once via
    ``Base.metadata.create_all`` (tests use create_all, not migrations — see
    ADR-039), and drops it again at the end of the session.
    """
    url = _test_database_url()
    dev_db = make_url(str(settings.database_url)).database
    # Safety net: refuse to build/drop schema against the dev database.
    assert url.database and url.database != dev_db, (
        f"Refusing to use {url.database!r} as the test database "
        f"(must differ from dev database {dev_db!r})"
    )

    await _ensure_test_database_exists(url)

    engine = create_async_engine(url, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Function-scoped session wrapped in a transaction that is rolled back.

    Transaction-rollback isolation, step by step:

    1. Open a dedicated connection from the engine.
    2. Begin a transaction on that connection.
    3. Bind an ``AsyncSession`` to the *same* connection, so everything the
       test does happens inside that one transaction.
    4. Yield the session to the test.
    5. Roll the transaction back afterwards — nothing is ever committed, so the
       test leaves no residue and the next test starts clean.

    Tests should ``flush`` (not ``commit``) to push pending changes to the
    database within the transaction; a commit would defeat the isolation.
    """
    connection = await test_engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()

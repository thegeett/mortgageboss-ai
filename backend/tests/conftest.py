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
from app.ai.client import get_anthropic_client
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


@pytest.fixture(autouse=True)
def _pin_ai_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deterministic AI-provider baseline for the WHOLE suite.

    ``app/core/config.py`` builds the ``settings`` singleton at import from ``.env`` (``env_file=".env"``),
    which is gitignored and per-worktree — so without this, a local ``AI_PROVIDER=bedrock`` (or any other
    override) silently changes the suite's result. This autouse fixture pins the provider to the shipped
    default (``anthropic``) so every test runs against a known baseline regardless of the ambient ``.env``.

    It is autouse by design: a test must OPT OUT (by monkeypatching the provider itself) to exercise a
    different provider, rather than opt in to hermeticity. Provider-specific tests already do exactly that
    (e.g. ``test_provider_selection_b1.py``'s ``_use_bedrock``); their own per-test monkeypatch runs after
    this fixture and wins within the test body, with both unwound cleanly at teardown.
    """
    monkeypatch.setattr(settings, "ai_provider", "anthropic")
    # ⚠️ AND NEUTER THE KEY (LP-491). Pinning the provider makes the suite deterministic, but it also
    # means any test that reaches a REAL reasoner bills the direct Anthropic API with the developer's
    # own key. That is not hypothetical: LP-490 shipped a test whose reasoner seam covered ONE ai group
    # while every other group fell through to the live model — roughly 40-60 real calls before the
    # runtime (133s for one file) gave it away. A dummy key turns that from a silent charge into an
    # auth error the test surfaces immediately. A test that genuinely needs a key sets its own.
    monkeypatch.setattr(
        settings, "anthropic_api_key", "sk-ant-test-not-a-real-key"
    )  # pragma: allowlist secret
    # ⚠️ TWO REPORTED FOOTGUNS IN THE LINE ABOVE, closed here.
    #  1. A dummy key is WEAKER than no key. With the key unset, client.py fails immediately with
    #     AIClientError("ANTHROPIC_API_KEY is not configured") — offline, instant. With a dummy key it
    #     BUILDS a real AsyncAnthropic and issues an HTTPS request that fails on auth, which in a
    #     network-isolated CI is a socket timeout rather than a fast, legible error. The point of the
    #     fixture is to surface a leaked call, so the client cache is cleared and the escape hatch below
    #     is made real rather than implied.
    #  2. `get_anthropic_client` is @cache'd, so "a test that genuinely needs a key sets its own" did not
    #     work — it received the already-built dummy-key client. Clearing the cache on setup AND teardown
    #     makes that sentence true.
    get_anthropic_client.cache_clear()
    yield
    get_anthropic_client.cache_clear()


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

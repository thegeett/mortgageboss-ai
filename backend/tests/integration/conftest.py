"""Integration-suite fixtures (LP-45) — the reusable foundation for Epic 6.

These exercise the **real stack**: real HTTP (httpx ``AsyncClient`` via
``ASGITransport``), real DB (the root ``test_engine`` + a commit-safe savepoint
session), real auth (real JWTs), real routing/DI/services/tenant-scoping, and
real local storage (a temp dir). Only two things are mocked — the AI and Celery
``.delay`` — because they are slow/costly/non-deterministic/external (see
ADR-152).

Composability is the point: ``company_a``/``user_a``/``auth_client`` give a
ready Company A actor; ``company_b``/``user_b`` give a second tenant for
isolation tests; the :mod:`factories` helpers build entities inline. The root
``tests/conftest.py`` provides ``test_engine`` (hierarchical conftest), reused —
not duplicated — here.
"""

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from app.api import documents as documents_api
from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models import Company, User
from app.storage import get_storage_backend
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from tests.integration import factories


@pytest.fixture(autouse=True)
def storage_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point the storage backend at an isolated temp dir (never real ./storage).

    Autouse so every upload/download/factory round-trips real bytes safely.
    """
    monkeypatch.setattr(settings, "storage_local_path", str(tmp_path / "storage"))
    get_storage_backend.cache_clear()
    yield
    get_storage_backend.cache_clear()


class Dispatch:
    """Holds the mocked Celery ``.delay`` entry points for assertions."""

    def __init__(self, process: MagicMock, reprocess: MagicMock) -> None:
        self.process = process
        self.reprocess = reprocess


@pytest.fixture(autouse=True)
def mock_dispatch(monkeypatch: pytest.MonkeyPatch) -> Dispatch:
    """Stub Celery dispatch (``process_document.delay`` / ``reprocess_document.delay``).

    Autouse so no test ever needs a real broker; assert against ``.process`` /
    ``.reprocess`` to prove an endpoint enqueued background work.
    """
    process = MagicMock()
    reprocess = MagicMock()
    monkeypatch.setattr(documents_api.process_document, "delay", process)
    monkeypatch.setattr(documents_api.reprocess_document, "delay", reprocess)
    return Dispatch(process, reprocess)


@pytest_asyncio.fixture
async def db(test_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Commit-safe session: endpoint ``commit()``s hit SAVEPOINTs inside one outer
    transaction that is rolled back afterwards (writes never leak between tests).
    """
    connection = await test_engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


@pytest_asyncio.fixture
async def client(db: AsyncSession) -> AsyncIterator[AsyncClient]:
    """Unauthenticated HTTP client against the real app, sharing the test ``db``."""

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_db, None)


# --- Company A (the actor) -------------------------------------------------- #


@pytest_asyncio.fixture
async def company_a(db: AsyncSession) -> Company:
    return await factories.make_company(db, slug="company-a")


@pytest_asyncio.fixture
async def user_a(db: AsyncSession, company_a: Company) -> User:
    return await factories.make_user(db, company=company_a, email="actor@company-a.com")


@pytest_asyncio.fixture
async def auth_client(client: AsyncClient, user_a: User) -> AsyncClient:
    """The Company A actor's client — a real Bearer token attached."""
    client.headers["Authorization"] = f"Bearer {factories.token_for(user_a)}"
    return client


# --- Company B (the other tenant; owns resources A must never reach) -------- #


@pytest_asyncio.fixture
async def company_b(db: AsyncSession) -> Company:
    return await factories.make_company(db, slug="company-b")


@pytest_asyncio.fixture
async def user_b(db: AsyncSession, company_b: Company) -> User:
    return await factories.make_user(db, company=company_b, email="owner@company-b.com")

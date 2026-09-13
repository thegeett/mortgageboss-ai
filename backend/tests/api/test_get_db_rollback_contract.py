"""The transaction contract LP-850's "a refusal writes nothing" rests on, pinned.

`compose_request` and `request_docs_for_finding` CREATE needs items before they reach the draft,
and the draft is where the open-draft conflict is raised. Nothing in those services undoes those
rows — the guarantee is entirely that the route's `HTTPException` propagates into `get_db`, whose
`except Exception: await session.rollback()` discards them.

That is a real guarantee and it holds (measured below). It was also, until this file, asserted
nowhere: every API test overrides `get_db` with a bare `yield db` that never rolls back, so no
test in the suite could have noticed the day it stopped being true.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from app.core.database import DbSession
from app.models import Company
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

_app = FastAPI()
_SLUGS: dict[str, str] = {}


@_app.post("/flush-then-refuse")
async def _flush_then_refuse(db: DbSession) -> dict[str, str]:
    """What a refused request does: write, then raise the way the three LP-850 routes do."""
    db.add(Company(name="Rollback probe", slug=_SLUGS["flush"]))
    await db.flush()
    raise HTTPException(409, detail="refused after flushing")


@_app.post("/commit-then-refuse")
async def _commit_then_refuse(db: DbSession) -> dict[str, str]:
    """The POSITIVE CONTROL's route: a write the rollback cannot reach."""
    db.add(Company(name="Rollback probe", slug=_SLUGS["commit"]))
    await db.commit()
    raise HTTPException(409, detail="refused after committing")


@pytest_asyncio.fixture
async def probe_client(
    test_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    """A client over the REAL `get_db`, pointed at the test database.

    `get_db` builds its own session from `async_session_maker`, which is bound to the DEV database
    — that is why every other API test overrides the dependency. This test cannot override it (the
    override is the thing under test), so it re-points the session maker instead.
    """
    import app.core.database as database

    monkeypatch.setattr(
        database,
        "async_session_maker",
        async_sessionmaker(bind=test_engine, expire_on_commit=False),
    )
    async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://probe") as client:
        yield client


async def _rows_for(engine: AsyncEngine, slug: str) -> list[str]:
    """Read on a SEPARATE session, so this sees committed state and nothing else."""
    async with AsyncSession(bind=engine) as check:
        return [
            c.slug
            for c in (await check.execute(select(Company).where(Company.slug == slug))).scalars()
        ]


async def test_an_httpexception_rolls_back_what_the_route_had_written(
    probe_client: AsyncClient, test_engine: AsyncEngine
) -> None:
    """THE GUARANTEE. A 409 raised after a flush leaves nothing behind."""
    _SLUGS["flush"] = f"rollback-flush-{uuid4().hex[:8]}"

    resp = await probe_client.post("/flush-then-refuse")

    assert resp.status_code == 409
    assert await _rows_for(test_engine, _SLUGS["flush"]) == [], (
        "get_db did not roll back the refused route's write — LP-850's 'a refusal writes nothing' "
        "is false, and the needs items compose_request created survive the 409"
    )


async def test_positive_control_the_checker_can_see_a_row_that_survives(
    probe_client: AsyncClient, test_engine: AsyncEngine
) -> None:
    """Without this, the test above passes on a checker that can never find anything.

    It is the same shape of mistake the assertion above is guarding against, so it gets the same
    treatment: prove the instrument reads before trusting it to read zero.
    """
    _SLUGS["commit"] = f"rollback-commit-{uuid4().hex[:8]}"

    resp = await probe_client.post("/commit-then-refuse")

    assert resp.status_code == 409
    assert await _rows_for(test_engine, _SLUGS["commit"]) == [_SLUGS["commit"]], (
        "the checker cannot see a committed row, so it proves nothing about an absent one"
    )

    async with AsyncSession(bind=test_engine) as cleanup:
        for row in (
            await cleanup.execute(select(Company).where(Company.slug == _SLUGS["commit"]))
        ).scalars():
            await cleanup.delete(row)
        await cleanup.commit()

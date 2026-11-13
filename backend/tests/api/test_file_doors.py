"""Every loan-file door, under "restrict loan files to their team" (LP-MB-Admin-06, ADR-446).

For each route in `file_doors.DOORS`, on a company with the setting ON and a file whose team is one
processor:

- a processor NOT on the team gets exactly what a missing id gets (the same status and body; an empty
  answer from a list or count), and the request writes nothing;
- the processor on the team, an admin, and a processor marked `sees_all_loans` get past the gate;
- with the setting OFF, the processor not on the team gets past it too.

"Past the gate" is not 404, not 422 (a refused body would hide whether the gate let them through)
and not a server error; a list or count includes the file. Each (door, caller) builds its own shop,
because a door that writes (a delete, a send) would otherwise change what the next caller finds.

NOTHING WRITTEN is measured from Postgres, not from the tables the door is about:
`pg_stat_xact_user_tables` counts every row inserted, updated or deleted in this transaction, in any
table, including inside a SAVEPOINT that was rolled back.
"""

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import pytest
import pytest_asyncio
from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.storage import get_storage_backend
from celery.app.task import Task
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.api.file_door_fixtures import PDF, Shop, bearer, build
from tests.api.file_doors import DOORS, Door

MISMO = Path(__file__).resolve().parents[1] / "fixtures" / "mismo" / "MISMO16940192.xml"

Caller = Literal["outsider", "member", "admin", "sees_all", "outsider_setting_off"]
CALLERS: tuple[Caller, ...] = ("outsider", "member", "admin", "sees_all", "outsider_setting_off")


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Storage in a temp dir, and no task leaves the process: a door that enqueues work (a reparse,
    a send) is tested for whether it got past the gate, not for the work."""
    monkeypatch.setattr(settings, "storage_local_path", str(tmp_path / "storage"))
    monkeypatch.setattr(Task, "apply_async", lambda *_a, **_k: None)
    # Upload links are minted only where the deployment receives mail; the door is about the gate.
    monkeypatch.setattr(settings, "receiving_enabled", True)
    get_storage_backend.cache_clear()
    yield
    get_storage_backend.cache_clear()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=True)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_db, None)


def _fill(value: Any, subs: dict[str, str]) -> Any:
    if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
        return subs[value[1:-1]]
    if isinstance(value, dict):
        return {k: _fill(v, subs) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v, subs) for v in value]
    return value


async def _send(
    client: AsyncClient, door: Door, subs: dict[str, str], headers: dict[str, str]
) -> Response:
    path = door.path.format(**{**subs, **door.params})
    kwargs: dict[str, Any] = {"headers": headers, "params": door.query}
    if door.upload is not None:
        form_field, kind = door.upload
        content = PDF if kind == "pdf" else MISMO.read_bytes()
        name = "sheet.pdf" if kind == "pdf" else "file.xml"
        mime = "application/pdf" if kind == "pdf" else "application/xml"
        kwargs["files"] = [(form_field, (name, content, mime))]
    elif door.body is not None:
        kwargs["json"] = _fill(door.body, subs)
    return await client.request(door.method, path, **kwargs)


async def _writes(db: AsyncSession) -> int:
    """Rows inserted, updated or deleted so far in this transaction, in every table."""
    total = await db.scalar(
        text(
            "SELECT coalesce(sum(n_tup_ins + n_tup_upd + n_tup_del), 0) "
            "FROM pg_stat_xact_user_tables"
        )
    )
    return int(total or 0)


def _shows_the_file(response: Response, shop: Shop) -> bool:
    return shop.loan_file.display_id in response.text or str(shop.loan_file.id) in response.text


def _missing(door: Door, subs: dict[str, str]) -> dict[str, str]:
    """The same path with its first id replaced by one that exists nowhere."""
    first = door.path.split("{", 1)[1].split("}", 1)[0]
    return {**subs, first: str(uuid4())}


@pytest.mark.parametrize("caller", CALLERS)
@pytest.mark.parametrize("door", DOORS, ids=[door.id for door in DOORS])
async def test_door(
    door: Door, caller: Caller, client: AsyncClient, db_session: AsyncSession
) -> None:
    shop = await build(db_session, client, door.fixture)
    if caller == "outsider_setting_off":
        shop.company.settings = {"restrict_loans_to_team": False}
    await db_session.flush()
    user = {
        "outsider": shop.outsider,
        "outsider_setting_off": shop.outsider,
        "member": shop.member,
        "admin": shop.admin,
        "sees_all": shop.sees_all,
    }[caller]
    # The request reads its rows fresh, as a real one does, not the fixture's objects.
    db_session.expunge_all()

    before = await _writes(db_session)
    response = await _send(client, door, shop.subs, bearer(user))

    if caller == "outsider":
        assert await _writes(db_session) == before, "a hidden file was written to"
        if door.empty is not None:
            assert response.status_code == 200, response.text
            assert not _shows_the_file(response, shop), response.text
            if door.empty == "counts":
                assert all(view["count"] == 0 for view in response.json()), response.text
            return
        missing = await _send(client, door, _missing(door, shop.subs), bearer(shop.admin))
        assert missing.status_code == 404, missing.text
        assert (response.status_code, response.json()) == (missing.status_code, missing.json())
        return

    assert response.status_code not in (404, 422), response.text
    assert response.status_code < 500, response.text
    if door.empty == "counts":
        assert all(view["count"] == 1 for view in response.json()), response.text
    elif door.empty is not None:
        assert _shows_the_file(response, shop), response.text

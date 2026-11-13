"""Loan teams, Part 1 (LP-MB-Admin-05): who works a file, the internal loan officer, the pipeline
filter, and handing a person's files over.

The real app, with the database bound to the test's rollback session.
"""

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from app.api import loan_files as loan_files_api
from app.core.config import settings
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.main import app
from app.models import ActivityLog, Company, CompanyAuditLog, LoanFile, User, UserRole
from app.models.activity_log import ActivityType
from app.models.loan_team import LoanTeamMember
from app.services import loan_teams as team_service
from app.services.inbound_participants import is_participant
from app.services.loan_files import create_loan_file
from app.storage import get_storage_backend
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.user_factory import make_user

API = "/api/v1"
A, LO, P = UserRole.ADMIN, UserRole.LOAN_OFFICER, UserRole.PROCESSOR
MISMO = Path(__file__).resolve().parents[1] / "fixtures" / "mismo" / "MISMO16940192.xml"


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Storage in a temp dir (the MISMO import writes the raw file), and no AI-needs enqueue."""
    monkeypatch.setattr(settings, "storage_local_path", str(tmp_path / "storage"))
    monkeypatch.setattr(loan_files_api, "_enqueue_ai_needs", lambda *_: None)
    get_storage_backend.cache_clear()
    yield
    get_storage_backend.cache_clear()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_db, None)


@dataclass
class Shop:
    company_id: UUID
    admin: UUID
    lo: UUID
    lo2: UUID
    proc: UUID
    proc2: UUID
    file: UUID
    file_id: str


async def _person(
    db: AsyncSession, company_id: UUID, first: str, *roles: UserRole, active: bool = True
) -> User:
    user = make_user(
        company_id=company_id,
        email=f"{first.lower()}-{uuid4().hex[:6]}@acme.com",
        hashed_password="x",  # pragma: allowlist secret
        first_name=first,
        last_name="Test",
        is_active=active,
        roles=roles,
    )
    db.add(user)
    await db.flush()
    return user


async def _shop(db: AsyncSession, name: str = "Acme") -> Shop:
    company = Company(name=name, slug=f"{name.lower()}-{uuid4().hex[:8]}")
    db.add(company)
    await db.flush()
    admin = await _person(db, company.id, "Ada", A)
    company.owner_user_id = admin.id
    lo = await _person(db, company.id, "Lou", LO)
    lo2 = await _person(db, company.id, "Lena", LO)
    proc = await _person(db, company.id, "Pat", P)
    proc2 = await _person(db, company.id, "Elena", P)
    loan_file = await create_loan_file(db, company_id=company.id)
    await db.flush()
    shop = Shop(
        company.id, admin.id, lo.id, lo2.id, proc.id, proc2.id, loan_file.id, loan_file.display_id
    )
    db.expunge_all()
    return shop


def _as(user_id: UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _team(shop: Shop) -> str:
    return f"{API}/loan-files/{shop.file_id}/team"


async def _file(db: AsyncSession, shop: Shop) -> LoanFile:
    db.expunge_all()
    loan_file = await db.get(LoanFile, shop.file)
    assert loan_file is not None
    return loan_file


async def _changes(db: AsyncSession, file_id: UUID) -> list[str]:
    db.expunge_all()
    rows = await db.scalars(
        select(ActivityLog.summary)
        .where(
            ActivityLog.loan_file_id == file_id,
            ActivityLog.activity_type == ActivityType.LOAN_TEAM_CHANGED,
        )
        .order_by(ActivityLog.created_at)
    )
    return list(rows)


async def _set_lo(
    client: AsyncClient, shop: Shop, user_id: UUID | None, who: UUID | None = None
) -> Any:
    return await client.put(
        f"{_team(shop)}/loan-officer",
        json={"user_id": str(user_id) if user_id else None},
        headers=_as(who or shop.admin),
    )


# --------------------------------------------------------------------------- #
# Who may change a team
# --------------------------------------------------------------------------- #


async def test_a_processor_may_not_change_any_team(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    shop = await _shop(db_session)
    await client.post(
        f"{_team(shop)}/members", json={"user_id": str(shop.proc)}, headers=_as(shop.admin)
    )
    member_id = (await client.get(_team(shop), headers=_as(shop.admin))).json()["processors"][0][
        "id"
    ]
    me = _as(shop.proc)

    put = await client.put(
        f"{_team(shop)}/loan-officer", json={"user_id": str(shop.lo)}, headers=me
    )
    post = await client.post(
        f"{_team(shop)}/members", json={"user_id": str(shop.proc2)}, headers=me
    )
    delete = await client.delete(f"{_team(shop)}/members/{member_id}", headers=me)
    read = await client.get(_team(shop), headers=me)

    assert (put.status_code, post.status_code, delete.status_code) == (403, 403, 403)
    assert read.status_code == 200 and read.json()["can_change"] is False


async def test_a_loan_officer_changes_their_own_files_only(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    shop = await _shop(db_session)
    other = await create_loan_file(db_session, company_id=shop.company_id)
    await db_session.flush()
    await _set_lo(client, shop, shop.lo)  # the admin makes Lou this file's LO

    own = await client.post(
        f"{_team(shop)}/members", json={"user_id": str(shop.proc)}, headers=_as(shop.lo)
    )
    theirs = await client.post(
        f"{API}/loan-files/{other.display_id}/team/members",
        json={"user_id": str(shop.proc)},
        headers=_as(shop.lo),
    )

    assert own.status_code == 200
    assert own.json()["can_change"] is True
    assert theirs.status_code == 403


async def test_an_admin_changes_any_team(client: AsyncClient, db_session: AsyncSession) -> None:
    shop = await _shop(db_session)
    resp = await client.post(
        f"{_team(shop)}/members", json={"user_id": str(shop.proc)}, headers=_as(shop.admin)
    )
    assert resp.status_code == 200
    assert [p["name"] for p in resp.json()["processors"]] == ["Pat Test"]


# --------------------------------------------------------------------------- #
# Who may be on a team
# --------------------------------------------------------------------------- #


async def test_eligibility(client: AsyncClient, db_session: AsyncSession) -> None:
    shop = await _shop(db_session)
    gone = await _person(db_session, shop.company_id, "Gone", P, active=False)
    other = await _shop(db_session, "Other")

    proc_as_lo = await _set_lo(client, shop, shop.proc)
    lo_as_proc = await client.post(
        f"{_team(shop)}/members", json={"user_id": str(shop.lo)}, headers=_as(shop.admin)
    )
    admin_only = await client.post(
        f"{_team(shop)}/members", json={"user_id": str(shop.admin)}, headers=_as(shop.admin)
    )
    inactive = await client.post(
        f"{_team(shop)}/members", json={"user_id": str(gone.id)}, headers=_as(shop.admin)
    )
    foreign = await client.post(
        f"{_team(shop)}/members", json={"user_id": str(other.proc)}, headers=_as(shop.admin)
    )

    assert proc_as_lo.status_code == 422
    assert (
        proc_as_lo.json()["error"]["message"]
        == "Pat Test needs the Loan officer role to be a loan officer"
    )
    assert (
        lo_as_proc.json()["error"]["message"]
        == "Lou Test needs the Processor role to be a processor"
    )
    assert admin_only.status_code == 422
    assert inactive.status_code == foreign.status_code == 422
    assert await _changes(db_session, shop.file) == []


async def test_adding_someone_already_on_the_team_changes_nothing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    shop = await _shop(db_session)
    body = {"user_id": str(shop.proc)}
    await client.post(f"{_team(shop)}/members", json=body, headers=_as(shop.admin))
    again = await client.post(f"{_team(shop)}/members", json=body, headers=_as(shop.admin))
    assert again.status_code == 200
    assert len(again.json()["processors"]) == 1
    assert await _changes(db_session, shop.file) == ["Ada Test added Pat Test as processor"]


# --------------------------------------------------------------------------- #
# The internal loan officer and the text fields
# --------------------------------------------------------------------------- #


async def test_assigning_changing_and_clearing_writes_the_text_through(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    shop = await _shop(db_session)
    lou = await db_session.get(User, shop.lo)
    lena = await db_session.get(User, shop.lo2)
    assert lou and lena
    lou_email, lena_email = lou.email, lena.email

    await _set_lo(client, shop, shop.lo)
    after_assign = await _file(db_session, shop)
    assert (after_assign.loan_officer_name, after_assign.loan_officer_email) == (
        "Lou Test",
        lou_email,
    )
    assert await is_participant(db_session, loan_file_id=shop.file, address=lou_email)

    await _set_lo(client, shop, shop.lo2)
    after_change = await _file(db_session, shop)
    assert (after_change.loan_officer_name, after_change.loan_officer_email) == (
        "Lena Test",
        lena_email,
    )
    assert await is_participant(db_session, loan_file_id=shop.file, address=lena_email)

    await _set_lo(client, shop, None)
    after_clear = await _file(db_session, shop)
    assert (after_clear.loan_officer_name, after_clear.loan_officer_email) == (None, None)
    assert await _changes(db_session, shop.file) == [
        "Ada Test made Lou Test the loan officer",
        "Ada Test changed the loan officer from Lou Test to Lena Test",
        "Ada Test removed Lena Test as loan officer",
    ]
    db_session.expunge_all()
    detail = (
        await db_session.scalars(
            select(ActivityLog.detail)
            .where(ActivityLog.loan_file_id == shop.file)
            .order_by(ActivityLog.created_at)
        )
    ).all()
    assert detail[1] == {
        "slot": "loan_officer",
        "from_user_id": str(shop.lo),
        "to_user_id": str(shop.lo2),
        "from_name": "Lou Test",
        "to_name": "Lena Test",
    }


async def test_clearing_leaves_text_that_no_longer_matches_the_person(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    shop = await _shop(db_session)
    await _set_lo(client, shop, shop.lo)
    # The person's account name changed since; the text still holds the old one.
    await db_session.execute(
        text("UPDATE users SET first_name = 'Louis' WHERE id = :u"), {"u": shop.lo}
    )

    await _set_lo(client, shop, None)

    cleared = await _file(db_session, shop)
    assert cleared.loan_officer_name == "Lou Test"  # not this person's any more: kept
    assert cleared.loan_officer_email is None  # still theirs: cleared


async def test_the_text_fields_follow_an_internal_loan_officer(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    shop = await _shop(db_session)
    url = f"{API}/loan-files/{shop.file_id}"
    external = await client.patch(
        url, json={"loan_officer_name": "Broker Bob"}, headers=_as(shop.admin)
    )
    await _set_lo(client, shop, shop.lo)

    internal = await client.patch(
        url, json={"loan_officer_name": "Someone Else"}, headers=_as(shop.admin)
    )
    unchanged = await client.patch(
        url,
        json={"loan_officer_name": "Lou Test", "loan_amount": "250000"},
        headers=_as(shop.admin),
    )

    assert external.status_code == 200
    assert (internal.status_code, internal.json()["error"]["message"]) == (
        422,
        "Change the loan officer on the Team card",
    )
    assert unchanged.status_code == 200


async def test_two_loan_officers_at_once_one_wins(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Staged: the other assignment committed after this request looked, so its insert collides."""
    shop = await _shop(db_session)
    await _set_lo(client, shop, shop.lo)

    async def _looked_too_soon(*_: Any) -> None:
        return None

    monkeypatch.setattr(team_service, "_loan_officer", _looked_too_soon)
    resp = await _set_lo(client, shop, shop.lo2)

    assert resp.status_code == 409
    monkeypatch.undo()
    db_session.expunge_all()
    live = await db_session.scalars(
        select(LoanTeamMember.user_id).where(
            LoanTeamMember.loan_file_id == shop.file,
            LoanTeamMember.team_role == "loan_officer",
            LoanTeamMember.deleted_at.is_(None),
        )
    )
    assert list(live) == [shop.lo]


async def test_removing_a_member(client: AsyncClient, db_session: AsyncSession) -> None:
    shop = await _shop(db_session)
    await client.post(
        f"{_team(shop)}/members", json={"user_id": str(shop.proc)}, headers=_as(shop.admin)
    )
    team = (await _set_lo(client, shop, shop.lo)).json()

    gone_proc = await client.delete(
        f"{_team(shop)}/members/{team['processors'][0]['id']}", headers=_as(shop.admin)
    )
    gone_lo = await client.delete(
        f"{_team(shop)}/members/{team['loan_officer']['id']}", headers=_as(shop.admin)
    )
    missing = await client.delete(f"{_team(shop)}/members/{uuid4()}", headers=_as(shop.admin))

    assert gone_proc.json()["processors"] == []
    assert gone_lo.json()["loan_officer"] is None
    assert missing.status_code == 404
    assert (await _file(db_session, shop)).loan_officer_name is None


# --------------------------------------------------------------------------- #
# The creator joins
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("creator", "expect"),
    [("lo", "loan_officer"), ("proc", "processor"), ("admin", None)],
)
async def test_the_creator_joins_by_role(
    client: AsyncClient, db_session: AsyncSession, creator: str, expect: str | None
) -> None:
    shop = await _shop(db_session)
    resp = await client.post(f"{API}/loan-files", json={}, headers=_as(getattr(shop, creator)))

    assert resp.status_code == 201
    team = resp.json()["team"]
    if expect == "loan_officer":
        assert team["loan_officer"]["user_id"] == str(shop.lo)
        assert resp.json()["loan_officer_name"] == "Lou Test"
    elif expect == "processor":
        assert [p["user_id"] for p in team["processors"]] == [str(shop.proc)]
    else:
        assert team == {"loan_officer": None, "processors": []}


@pytest.mark.parametrize(("creator", "slot"), [("lo", "loan_officer"), ("proc", "processor")])
async def test_the_creator_joins_on_a_mismo_import(
    client: AsyncClient, db_session: AsyncSession, creator: str, slot: str
) -> None:
    shop = await _shop(db_session)
    resp = await client.post(
        f"{API}/loan-files/import-mismo",
        files={"file": ("loan.xml", MISMO.read_bytes(), "application/xml")},
        headers=_as(getattr(shop, creator)),
    )
    assert resp.status_code == 201, resp.text
    team = resp.json()["loan_file"]["team"]
    if slot == "loan_officer":
        assert team["loan_officer"]["user_id"] == str(shop.lo)
    else:
        assert [p["user_id"] for p in team["processors"]] == [str(shop.proc)]


# --------------------------------------------------------------------------- #
# The pipeline filter and saved views
# --------------------------------------------------------------------------- #


async def test_the_assignee_filter(client: AsyncClient, db_session: AsyncSession) -> None:
    shop = await _shop(db_session)
    mine = (await client.post(f"{API}/loan-files", json={}, headers=_as(shop.proc))).json()[
        "display_id"
    ]
    lou_file = (await client.post(f"{API}/loan-files", json={}, headers=_as(shop.lo))).json()[
        "display_id"
    ]

    def ids(resp: Any) -> set[str]:
        return {row["display_id"] for row in resp.json()["items"]}

    me = await client.get(f"{API}/loan-files?assignee=me", headers=_as(shop.proc))
    unassigned = await client.get(f"{API}/loan-files?assignee=unassigned", headers=_as(shop.admin))
    by_id = await client.get(f"{API}/loan-files?assignee={shop.lo}", headers=_as(shop.admin))
    with_status = await client.get(
        f"{API}/loan-files?assignee=me&status=submitted", headers=_as(shop.proc)
    )
    with_search = await client.get(
        f"{API}/loan-files?assignee=me&search={mine}", headers=_as(shop.proc)
    )
    bad = await client.get(f"{API}/loan-files?assignee=nobody", headers=_as(shop.admin))

    assert ids(me) == {mine}
    assert ids(unassigned) == {shop.file_id}
    assert ids(by_id) == {lou_file}
    assert ids(with_status) == set()
    assert ids(with_search) == {mine}
    assert bad.status_code == 422
    rows = {
        row["display_id"]: row
        for row in (await client.get(f"{API}/loan-files", headers=_as(shop.admin))).json()["items"]
    }
    assert rows[lou_file]["loan_officer_display"] == {"name": "Lou Test", "external": False}
    assert rows[mine]["team"]["processors"][0]["name"] == "Pat Test"


async def test_an_external_loan_officer_shows_as_external(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    shop = await _shop(db_session)
    await client.patch(
        f"{API}/loan-files/{shop.file_id}",
        json={"loan_officer_name": "Broker Bob"},
        headers=_as(shop.admin),
    )
    rows = (await client.get(f"{API}/loan-files", headers=_as(shop.admin))).json()["items"]
    assert rows[0]["loan_officer_display"] == {"name": "Broker Bob", "external": True}


async def test_a_saved_view_with_assignee_me_counts_each_viewers_files(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    shop = await _shop(db_session)
    await client.post(f"{API}/loan-files", json={}, headers=_as(shop.proc))
    await client.post(f"{API}/loan-files", json={}, headers=_as(shop.proc))
    await client.post(f"{API}/loan-files", json={}, headers=_as(shop.proc2))
    created = await client.post(
        f"{API}/saved-views",
        json={"name": "My files", "filters": {"assignee": "me"}, "is_shared": True},
        headers=_as(shop.proc),
    )
    assert created.status_code == 201, created.text

    def count(resp: Any) -> int:
        return next(v["count"] for v in resp.json() if v["name"] == "My files")

    pat = await client.get(f"{API}/saved-views?with_counts=true", headers=_as(shop.proc))
    elena = await client.get(f"{API}/saved-views?with_counts=true", headers=_as(shop.proc2))
    assert (count(pat), count(elena)) == (2, 1)


# --------------------------------------------------------------------------- #
# Handing someone's files over
# --------------------------------------------------------------------------- #


async def test_reassign_moves_every_place_audits_once_and_logs_each_file(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    shop = await _shop(db_session)
    first = (await client.post(f"{API}/loan-files", json={}, headers=_as(shop.proc))).json()[
        "display_id"
    ]
    second = (await client.post(f"{API}/loan-files", json={}, headers=_as(shop.proc))).json()[
        "display_id"
    ]

    resp = await client.post(
        f"{API}/users/{shop.proc}/reassign-loans",
        json={"to_user_id": str(shop.proc2)},
        headers=_as(shop.admin),
    )

    assert resp.json() == {"moved": 2}
    for display_id in (first, second):
        team = (
            await client.get(f"{API}/loan-files/{display_id}/team", headers=_as(shop.admin))
        ).json()
        assert [p["user_id"] for p in team["processors"]] == [str(shop.proc2)]
    db_session.expunge_all()
    audits = list(
        await db_session.scalars(
            select(CompanyAuditLog).where(
                CompanyAuditLog.action == "loans_reassigned",
                CompanyAuditLog.company_id == shop.company_id,
            )
        )
    )
    assert len(audits) == 1
    assert audits[0].detail == {
        "count": 2,
        "from_user_id": str(shop.proc),
        "to_user_id": str(shop.proc2),
    }
    moved = await db_session.scalar(
        select(ActivityLog.summary)
        .where(
            ActivityLog.activity_type == ActivityType.LOAN_TEAM_CHANGED,
            ActivityLog.summary.like("%moved%"),
        )
        .limit(1)
    )
    assert moved == "Ada Test moved Pat Test's place as processor to Elena Test"


async def test_reassign_refuses_a_target_missing_a_slots_role(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    shop = await _shop(db_session)
    await client.post(f"{API}/loan-files", json={}, headers=_as(shop.lo))

    resp = await client.post(
        f"{API}/users/{shop.lo}/reassign-loans",
        json={"to_user_id": str(shop.proc)},
        headers=_as(shop.admin),
    )

    assert (resp.status_code, resp.json()["error"]["message"]) == (
        422,
        "Pat Test needs the Loan officer role to take these files",
    )
    db_session.expunge_all()
    still = await db_session.scalar(
        select(LoanTeamMember.user_id).where(
            LoanTeamMember.user_id == shop.lo, LoanTeamMember.deleted_at.is_(None)
        )
    )
    assert still == shop.lo


async def test_reassign_is_tenant_scoped_and_admin_only(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    shop = await _shop(db_session)
    other = await _shop(db_session, "Other")
    await client.post(f"{API}/loan-files", json={}, headers=_as(other.proc))

    foreign_source = await client.post(
        f"{API}/users/{other.proc}/reassign-loans",
        json={"to_user_id": str(shop.proc2)},
        headers=_as(shop.admin),
    )
    foreign_target = await client.post(
        f"{API}/users/{shop.proc}/reassign-loans",
        json={"to_user_id": str(other.proc2)},
        headers=_as(shop.admin),
    )
    by_processor = await client.post(
        f"{API}/users/{shop.proc}/reassign-loans",
        json={"to_user_id": str(shop.proc2)},
        headers=_as(shop.proc),
    )

    assert (foreign_source.status_code, foreign_target.status_code, by_processor.status_code) == (
        404,
        404,
        403,
    )


async def test_assignable_lists_eligible_people_with_their_load(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    shop = await _shop(db_session)
    await client.post(f"{API}/loan-files", json={}, headers=_as(shop.proc))

    los = await client.get(f"{API}/users/assignable?team_role=loan_officer", headers=_as(shop.proc))
    procs = await client.get(f"{API}/users/assignable?team_role=processor", headers=_as(shop.proc))

    assert los.status_code == 200  # any signed-in person may ask
    assert [p["name"] for p in los.json()] == ["Lena Test", "Lou Test"]
    counts = {p["name"]: p["file_count"] for p in procs.json()}
    assert counts == {"Elena Test": 0, "Pat Test": 1}
    people = (await client.get(f"{API}/users", headers=_as(shop.admin))).json()
    assert next(p for p in people if p["id"] == str(shop.proc))["file_count"] == 1

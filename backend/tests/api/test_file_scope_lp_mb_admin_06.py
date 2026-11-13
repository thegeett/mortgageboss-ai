"""Restrict loan files to their team (LP-MB-Admin-06, ADR-446): the decision, the predicate, and the
places a rule is more than "404 on a hidden file" (that is `test_file_doors.py`).

The real app, with the database bound to the test's rollback session.
"""

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from app.api import loan_files as loan_files_api
from app.api.dependencies import get_current_actor
from app.core.config import settings
from app.core.database import get_db
from app.core.file_scope import FileScope
from app.core.jwt import create_access_token
from app.main import app
from app.models import Company, LoanFile, User, UserRole
from app.models.base import utcnow
from app.models.communication import Communication, CommunicationDirection, CommunicationStatus
from app.models.helpers import scope_files
from app.models.inbound_message import InboundMessage, InboundRoutingState
from app.models.loan_team import LoanTeamMember, TeamRole
from app.models.needs_item import NeedsItemStatus
from app.models.saved_view import SavedView
from app.services.evidence import record_sent
from app.services.loan_files import create_loan_file
from app.services.processor_copy import copy_recipient
from app.services.reminders import build_suggestions
from app.storage import get_storage_backend
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs
from tests.integration.factories import make_needs_item
from tests.user_factory import make_user

API = "/api/v1"
A, LO, P = UserRole.ADMIN, UserRole.LOAN_OFFICER, UserRole.PROCESSOR
MISMO = Path(__file__).resolve().parents[1] / "fixtures" / "mismo" / "MISMO16940192.xml"
REFUSAL = (
    "You would not be able to see this file. Leave the loan officer blank to be its loan "
    "officer, or ask an admin to create it."
)


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
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


def _as(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


async def _company(db: AsyncSession, *, restricted: bool = True) -> Company:
    company = Company(
        name="Broker Shop",
        slug=f"broker-{uuid4().hex[:8]}",
        settings={"restrict_loans_to_team": restricted},
    )
    db.add(company)
    await db.flush()
    return company


async def _person(
    db: AsyncSession, company: Company, first: str, *roles: UserRole, sees_all: bool = False
) -> User:
    user = make_user(
        company_id=company.id,
        email=f"{first.lower()}-{uuid4().hex[:6]}@broker.example.com",
        hashed_password="x",  # pragma: allowlist secret
        first_name=first,
        last_name="Scope",
        roles=roles,
        sees_all_loans=sees_all,
    )
    db.add(user)
    await db.flush()
    return user


async def _file_on_team(
    db: AsyncSession, company: Company, *members: User, role: TeamRole = TeamRole.PROCESSOR
) -> LoanFile:
    loan_file = await create_loan_file(db, company_id=company.id)
    for member in members:
        db.add(LoanTeamMember(loan_file_id=loan_file.id, user_id=member.id, team_role=role))
    await db.flush()
    return loan_file


# --------------------------------------------------------------------------- #
# FileScope.for_actor: every branch
# --------------------------------------------------------------------------- #


def _actor_scope(*roles: UserRole, restricted: bool, sees_all: bool = False) -> FileScope:
    user = make_user(
        company_id=uuid4(),
        email="x@example.com",
        hashed_password="x",  # pragma: allowlist secret
        first_name="X",
        last_name="Y",
        roles=roles,
        sees_all_loans=sees_all,
    )
    user.id = uuid4()
    user.company = Company(settings={"restrict_loans_to_team": restricted})
    return get_current_actor(user).scope


def test_the_setting_off_sees_every_file() -> None:
    scope = _actor_scope(P, restricted=False)
    assert scope.restricted_to_user_id is None and not scope.restricted


def test_the_setting_on_restricts_a_processor_to_their_own_files() -> None:
    user_scope = _actor_scope(P, restricted=True)
    assert user_scope.restricted


def test_the_setting_on_restricts_a_loan_officer() -> None:
    assert _actor_scope(LO, restricted=True).restricted


def test_view_all_sees_every_file_with_the_setting_on() -> None:
    assert not _actor_scope(A, restricted=True).restricted
    assert not _actor_scope(P, A, restricted=True).restricted


def test_sees_all_loans_sees_every_file_with_the_setting_on() -> None:
    assert not _actor_scope(P, restricted=True, sees_all=True).restricted


def test_no_roles_is_restricted() -> None:
    assert _actor_scope(restricted=True).restricted


def test_the_restriction_is_to_the_actors_own_id() -> None:
    user = make_user(
        company_id=uuid4(),
        email="x@example.com",
        hashed_password="x",  # pragma: allowlist secret
        first_name="X",
        last_name="Y",
        roles=[P],
    )
    user.id = uuid4()
    user.company = Company(settings={"restrict_loans_to_team": True})
    actor = get_current_actor(user)
    assert actor.scope == FileScope(company_id=user.company_id, restricted_to_user_id=user.id)
    assert FileScope.system(user.company_id) == FileScope(user.company_id, None)


# --------------------------------------------------------------------------- #
# scope_files, as SQL
# --------------------------------------------------------------------------- #


async def test_scope_files_counts_only_live_team_rows(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    other = await _company(db_session)
    pat = await _person(db_session, company, "Pat", P)
    mine = await _file_on_team(db_session, company, pat)
    left = await _file_on_team(db_session, company, pat)
    nobodys = await _file_on_team(db_session, company)
    theirs = await _file_on_team(db_session, other)
    gone = await db_session.scalar(
        select(LoanTeamMember).where(LoanTeamMember.loan_file_id == left.id)
    )
    assert gone is not None
    gone.deleted_at = utcnow()
    await db_session.flush()

    async def ids(scope: FileScope) -> set[UUID]:
        return set(await db_session.scalars(scope_files(select(LoanFile.id), scope)))

    assert await ids(FileScope(company.id, pat.id)) == {mine.id}
    assert await ids(FileScope.system(company.id)) == {mine.id, left.id, nobodys.id}
    assert theirs.id not in await ids(FileScope.system(company.id))


# --------------------------------------------------------------------------- #
# Creating a file under the setting (Decided 4)
# --------------------------------------------------------------------------- #


async def _file_count(db: AsyncSession, company: Company) -> int:
    return int(
        await db.scalar(
            select(func.count()).select_from(LoanFile).where(LoanFile.company_id == company.id)
        )
        or 0
    )


async def test_a_loan_officer_naming_another_loan_officer_is_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company = await _company(db_session)
    lou = await _person(db_session, company, "Lou", LO)
    before = await _file_count(db_session, company)
    resp = await client.post(
        f"{API}/loan-files",
        json={"loan_officer_name": "Lena Other", "loan_officer_email": "lena@other.example.com"},
        headers=_as(lou),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["message"] == REFUSAL
    assert await _file_count(db_session, company) == before


async def test_the_same_create_is_allowed_with_the_setting_off(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company = await _company(db_session, restricted=False)
    lou = await _person(db_session, company, "Lou", LO)
    resp = await client.post(
        f"{API}/loan-files",
        json={"loan_officer_name": "Lena Other", "loan_officer_email": "lena@other.example.com"},
        headers=_as(lou),
    )
    assert resp.status_code == 201, resp.text


async def test_a_loan_officer_who_leaves_it_blank_creates_and_opens_the_file(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company = await _company(db_session)
    lou = await _person(db_session, company, "Lou", LO)
    resp = await client.post(f"{API}/loan-files", json={}, headers=_as(lou))
    assert resp.status_code == 201, resp.text
    opened = await client.get(f"{API}/loan-files/{resp.json()['display_id']}", headers=_as(lou))
    assert opened.status_code == 200, opened.text


async def test_an_admin_with_no_slot_creates_and_opens_the_file(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company = await _company(db_session)
    ada = await _person(db_session, company, "Ada", A)
    resp = await client.post(f"{API}/loan-files", json={}, headers=_as(ada))
    assert resp.status_code == 201, resp.text
    assert resp.json()["team"] == {"loan_officer": None, "processors": []}
    opened = await client.get(f"{API}/loan-files/{resp.json()['display_id']}", headers=_as(ada))
    assert opened.status_code == 200, opened.text


@pytest.mark.parametrize("names_another", [True, False])
async def test_a_mismo_import_that_names_another_loan_officer_is_refused(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    names_another: bool,
) -> None:
    """The import path refuses the same creator. The fixture MISMO names no loan officer, so the
    import is wrapped to name one, as a broker's export would; without it, Lou takes the slot."""
    real = loan_files_api.create_loan_file_from_mismo

    async def naming(*args: object, **kwargs: object) -> LoanFile:
        loan_file = await real(*args, **kwargs)  # type: ignore[arg-type]
        if names_another:
            loan_file.loan_officer_name = "Lena Other"
            loan_file.loan_officer_email = "lena@other.example.com"
        return loan_file

    monkeypatch.setattr(loan_files_api, "create_loan_file_from_mismo", naming)
    company = await _company(db_session)
    lou = await _person(db_session, company, "Lou", LO)
    before = await _file_count(db_session, company)
    resp = await client.post(
        f"{API}/loan-files/import-mismo",
        files={"file": ("loan.xml", MISMO.read_bytes(), "application/xml")},
        headers=_as(lou),
    )
    if not names_another:
        assert resp.status_code == 201, resp.text
        assert resp.json()["loan_file"]["team"]["loan_officer"]["user_id"] == str(lou.id)
        return
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["message"] == REFUSAL
    assert await _file_count(db_session, company) == before


# --------------------------------------------------------------------------- #
# The Inbox (ADR-421): unrouted mail stays for everyone
# --------------------------------------------------------------------------- #


async def _message(
    db: AsyncSession, company: Company, loan_file: LoanFile | None
) -> InboundMessage:
    message = InboundMessage(
        company_id=company.id,
        loan_file_id=loan_file.id if loan_file else None,
        ingest_key=uuid4().hex,
        from_address="borrower@example.com",
        subject="Statements",
        routing_state=InboundRoutingState.ROUTED if loan_file else InboundRoutingState.UNROUTED,
    )
    db.add(message)
    await db.flush()
    return message


async def test_the_inbox_keeps_unrouted_mail_and_hides_another_teams(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company = await _company(db_session)
    pat = await _person(db_session, company, "Pat", P)
    other = await _person(db_session, company, "Ola", P)
    mine = await _file_on_team(db_session, company, pat)
    theirs = await _file_on_team(db_session, company, other)
    unrouted = await _message(db_session, company, None)
    on_mine = await _message(db_session, company, mine)
    on_theirs = await _message(db_session, company, theirs)

    resp = await client.get(f"{API}/inbound/queue", headers=_as(pat))
    assert resp.status_code == 200, resp.text
    seen = {row["id"] for row in resp.json()}
    assert str(unrouted.id) in seen
    assert str(on_mine.id) in seen
    assert str(on_theirs.id) not in seen


async def test_moving_mail_to_a_hidden_file_is_404_and_to_their_own_works(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company = await _company(db_session)
    pat = await _person(db_session, company, "Pat", P)
    other = await _person(db_session, company, "Ola", P)
    mine = await _file_on_team(db_session, company, pat)
    theirs = await _file_on_team(db_session, company, other)
    message = await _message(db_session, company, None)

    hidden = await client.post(
        f"{API}/inbound/messages/{message.id}/move",
        json={"file_identifier": theirs.display_id},
        headers=_as(pat),
    )
    assert hidden.status_code == 404, hidden.text
    moved = await client.post(
        f"{API}/inbound/messages/{message.id}/move",
        json={"file_identifier": mine.display_id},
        headers=_as(pat),
    )
    assert moved.status_code == 200, moved.text


# --------------------------------------------------------------------------- #
# Reminders and saved-view counts: "all" means all I can see
# --------------------------------------------------------------------------- #


async def _overdue_need(db: AsyncSession, loan_file: LoanFile) -> None:
    need = await make_needs_item(db, loan_file=loan_file)
    need.status = NeedsItemStatus.REQUESTED
    need.requested_at = utcnow().replace(year=utcnow().year - 1)
    await db.flush()


async def test_reminders_are_only_for_the_users_files(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    pat = await _person(db_session, company, "Pat", P)
    mine = await _file_on_team(db_session, company, pat)
    theirs = await _file_on_team(db_session, company)
    await _overdue_need(db_session, mine)
    await _overdue_need(db_session, theirs)

    restricted = await build_suggestions(db_session, scope=FileScope(company.id, pat.id))
    everyone = await build_suggestions(db_session, scope=FileScope.system(company.id))
    assert {s.loan_file_id for s in restricted} == {mine.id}
    assert {s.loan_file_id for s in everyone} == {mine.id, theirs.id}


async def test_the_all_files_count_is_the_files_the_user_can_see(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company = await _company(db_session)
    pat = await _person(db_session, company, "Pat", P)
    await _file_on_team(db_session, company, pat)
    await _file_on_team(db_session, company)
    await _file_on_team(db_session, company)
    db_session.add(
        SavedView(
            company_id=company.id,
            owner_user_id=pat.id,
            name="All files",
            filters={},
            is_shared=True,
        )
    )
    await db_session.flush()

    views = await client.get(f"{API}/saved-views?with_counts=true", headers=_as(pat))
    files = await client.get(f"{API}/loan-files", headers=_as(pat))
    assert views.status_code == 200 and files.status_code == 200
    (all_files,) = views.json()
    assert all_files["count"] == files.json()["total"] == 1


# --------------------------------------------------------------------------- #
# The processor's copy (point 11)
# --------------------------------------------------------------------------- #


async def _sent_by(db: AsyncSession, loan_file: LoanFile, approver: User) -> None:
    row = Communication(
        loan_file_id=loan_file.id,
        direction=CommunicationDirection.OUTBOUND,
        status=CommunicationStatus.SENT,
        recipient="jane@borrower.example",
        subject="Documents",
        body="Please send.",
        sent_at=utcnow(),
        send_requested_at=utcnow(),
    )
    db.add(row)
    await db.flush()
    await record_sent(db, loan_file=loan_file, communication=row, approver_user_id=approver.id)


@dataclass
class _Copy:
    company: Company
    sender: User
    loan_file: LoanFile


async def _sender_who_left(db: AsyncSession, *, restricted: bool) -> _Copy:
    company = await _company(db, restricted=restricted)
    sender = await _person(db, company, "Pat", P)
    loan_file = await _file_on_team(db, company)  # Pat sent from it, and is not on its team now
    await _sent_by(db, loan_file, sender)
    return _Copy(company, sender, loan_file)


async def test_no_copy_for_a_sender_who_left_the_team(db_session: AsyncSession) -> None:
    case = await _sender_who_left(db_session, restricted=True)
    with capture_logs() as logs:
        assert await copy_recipient(db_session, case.loan_file) is None
    assert [log for log in logs if log["event"] == "processor_copy_no_team_sender"] == [
        {
            "event": "processor_copy_no_team_sender",
            "log_level": "info",
            "loan_file_id": str(case.loan_file.id),
        }
    ]


async def test_the_copy_goes_to_them_with_the_setting_off(db_session: AsyncSession) -> None:
    case = await _sender_who_left(db_session, restricted=False)
    assert await copy_recipient(db_session, case.loan_file) == case.sender


async def test_the_copy_goes_to_the_latest_sender_still_on_the_team(
    db_session: AsyncSession,
) -> None:
    case = await _sender_who_left(db_session, restricted=True)
    stayer = await _person(db_session, case.company, "Sam", P)
    db_session.add(
        LoanTeamMember(
            loan_file_id=case.loan_file.id, user_id=stayer.id, team_role=TeamRole.PROCESSOR
        )
    )
    await _sent_by(db_session, case.loan_file, stayer)
    await _sent_by(db_session, case.loan_file, case.sender)  # the newest, and off the team
    assert await copy_recipient(db_session, case.loan_file) == stayer


# --------------------------------------------------------------------------- #
# UserPublic.restricted (Decided 1)
# --------------------------------------------------------------------------- #


async def test_me_says_whether_the_user_is_restricted(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    on = await _company(db_session)
    off = await _company(db_session, restricted=False)
    cases = [
        (await _person(db_session, on, "Pat", P), True),
        (await _person(db_session, on, "Lou", LO), True),
        (await _person(db_session, on, "Ada", A), False),
        (await _person(db_session, on, "Sal", P, sees_all=True), False),
        (await _person(db_session, off, "Pia", P), False),
    ]
    for user, restricted in cases:
        me = await client.get(f"{API}/auth/me", headers=_as(user))
        assert me.status_code == 200, me.text
        assert me.json()["restricted"] is restricted, user.first_name

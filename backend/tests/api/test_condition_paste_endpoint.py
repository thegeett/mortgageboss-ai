"""The paste endpoint (LP-907 section 1, spec §LP-907, screens S1-06 and S1-07).

⚠️ 201 AND A FINISHED ROUND, where the upload door answers 202 and a `PARSING` one. The two differ
because the work does, and the contract has to say so: a client that polled this round waiting for
`DRAFT` would poll a round that was already there.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.main import app
from app.models import Company, User, UserRole
from app.models.condition_round import ConditionRoundCompleteness, ConditionRoundStatus
from app.schemas.condition import MAX_PASTE_CHARS
from app.services.loan_files import create_loan_file
from httpx import ASGITransport, AsyncClient
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
    company = Company(name=slug.title(), slug=slug)
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id,
        email=f"u@{slug}.com",
        hashed_password=hash_password("irrelevant"),
        first_name="Test",
        last_name="User",
        role=UserRole.PROCESSOR,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return company, create_access_token(user.id)


def _url(file_id: object) -> str:
    return f"/api/v1/loan-files/{file_id}/condition-rounds/paste"


async def test_a_paste_comes_back_as_a_finished_draft(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company, token = await _user(db_session, slug="paste-happy")
    loan_file = await create_loan_file(db_session, company_id=company.id)

    response = await client.post(
        _url(loan_file.id),
        headers=_auth(token),
        json={"text": portal_excerpt(), "completeness": ConditionRoundCompleteness.PARTIAL.value},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == ConditionRoundStatus.DRAFT.value
    assert body["sheet_format"] == "uwm_approval_letter"
    assert len(body["draft_rows"]) == 6
    assert body["draft_rows"][3]["verbatim_text"] == "Provide copy of invoice for credit report."
    assert body["parse_report"]["reader"] == "uwm"
    assert body["parse_report"]["needs_ai"] is False
    assert body["sources"][0]["kind"] == "paste"
    # ⚠️ A paste has no letter, so the side panel is told so rather than shown empty fields (S1-07).
    assert body["header"] is None
    assert body["date_printed"] is None


async def test_text_the_rules_cannot_split_still_returns_a_draft(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The LP-908 seam, visible in the response rather than hidden: the round is usable now, and
    `needs_ai` says an AI split is still owed."""
    company, token = await _user(db_session, slug="paste-prose")
    loan_file = await create_loan_file(db_session, company_id=company.id)

    response = await client.post(
        _url(loan_file.id),
        headers=_auth(token),
        json={
            "text": "Please send whatever you have for this file when you can.",
            "completeness": ConditionRoundCompleteness.PARTIAL.value,
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == ConditionRoundStatus.DRAFT.value
    assert body["sheet_format"] == "pasted_text"
    assert body["parse_report"]["needs_ai"] is True
    assert body["parse_report"]["ai_used"] is False


async def test_completeness_is_required(client: AsyncClient, db_session: AsyncSession) -> None:
    """⚠️ NO DEFAULT AT THE BOUNDARY (ADR-404). The UI defaults the control to "just some"; the API
    refusing to guess is what makes that a decision rather than a fallback."""
    company, token = await _user(db_session, slug="paste-nocomp")
    loan_file = await create_loan_file(db_session, company_id=company.id)

    response = await client.post(
        _url(loan_file.id), headers=_auth(token), json={"text": portal_excerpt()}
    )

    assert response.status_code == 422


async def test_an_empty_paste_is_refused(client: AsyncClient, db_session: AsyncSession) -> None:
    company, token = await _user(db_session, slug="paste-empty")
    loan_file = await create_loan_file(db_session, company_id=company.id)

    response = await client.post(
        _url(loan_file.id),
        headers=_auth(token),
        json={"text": "", "completeness": ConditionRoundCompleteness.FULL.value},
    )

    assert response.status_code == 422


async def test_an_oversized_paste_is_refused_before_a_reader_sees_it(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The ceiling is on the request schema, so the rules never run on a body this size."""
    company, token = await _user(db_session, slug="paste-huge")
    loan_file = await create_loan_file(db_session, company_id=company.id)

    response = await client.post(
        _url(loan_file.id),
        headers=_auth(token),
        json={
            "text": "x" * (MAX_PASTE_CHARS + 1),
            "completeness": ConditionRoundCompleteness.FULL.value,
        },
    )

    assert response.status_code == 422


async def test_another_companys_loan_file_is_a_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """CRITICAL: cross-tenant isolation. The same 404 as a missing file — distinguishing them would
    confirm the id exists, an oracle over another tenant's rows."""
    company_a, _token_a = await _user(db_session, slug="paste-tenant-a")
    loan_file_a = await create_loan_file(db_session, company_id=company_a.id)
    _company_b, token_b = await _user(db_session, slug="paste-tenant-b")

    response = await client.post(
        _url(loan_file_a.id),
        headers=_auth(token_b),
        json={"text": portal_excerpt(), "completeness": ConditionRoundCompleteness.FULL.value},
    )

    assert response.status_code == 404


async def test_a_missing_loan_file_is_a_404(client: AsyncClient, db_session: AsyncSession) -> None:
    _company, token = await _user(db_session, slug="paste-missing")

    response = await client.post(
        _url(uuid4()),
        headers=_auth(token),
        json={"text": portal_excerpt(), "completeness": ConditionRoundCompleteness.FULL.value},
    )

    assert response.status_code == 404


async def test_an_unauthenticated_paste_is_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company, _token = await _user(db_session, slug="paste-anon")
    loan_file = await create_loan_file(db_session, company_id=company.id)

    response = await client.post(
        _url(loan_file.id),
        json={"text": portal_excerpt(), "completeness": ConditionRoundCompleteness.FULL.value},
    )

    assert response.status_code == 401

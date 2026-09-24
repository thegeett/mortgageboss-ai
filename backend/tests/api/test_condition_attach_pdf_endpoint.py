"""Attaching the lender's PDF to an existing round (LP-907 section 2, spec §LP-907, screen S1-09).

⚠️ 200, NOT 201 OR 202, AND THE TESTS SAY SO DELIBERATELY. Nothing is created: no second round, and
no new conditions when the PDF carries what the paste already had. A 201 would tell a client
something was created and invite it to look for a new id.

THE ROUTE IS NOT UNDER `/loan-files`, so `ScopedLoanFile` — the tenant gate every nested condition
route uses — cannot apply. The scoping lives in `get_scoped_round` instead, and the cross-tenant test
below is what proves it rather than assuming it.
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
from app.models.condition_round import (
    ConditionRound,
    ConditionRoundCompleteness,
    ConditionRoundStatus,
)
from app.services.condition_rounds import create_round_from_paste
from app.services.loan_files import create_loan_file
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.fixture_helpers import UWM_ROUND_2, portal_excerpt
from tests.conditions.uwm_pdf_fixture import render_uwm_pdf


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


async def _pasted_round(db: AsyncSession, *, slug: str) -> tuple[ConditionRound, str]:
    company, token = await _user(db, slug=slug)
    loan_file = await create_loan_file(db, company_id=company.id)
    round_ = await create_round_from_paste(
        db,
        loan_file=loan_file,
        text=portal_excerpt(),
        completeness=ConditionRoundCompleteness.PARTIAL,
    )
    return round_, token


def _url(round_id: object) -> str:
    return f"/api/v1/condition-rounds/{round_id}/attach-pdf"


def _pdf_part() -> dict[str, tuple[str, bytes, str]]:
    return {"file": ("round2.pdf", render_uwm_pdf(UWM_ROUND_2), "application/pdf")}


async def test_attaching_the_pdf_enriches_the_same_round(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Spec §8 step 3, through the API: the header, expiry dates and printed date arrive, no new
    conditions are added, and the round is the same one."""
    round_, token = await _pasted_round(db_session, slug="attach-happy")

    response = await client.post(_url(round_.id), headers=_auth(token), files=_pdf_part())

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["round_id"] == str(round_.id)
    assert body["filled_header"] is True
    assert body["filled_expiry"] is True
    assert body["filled_date_printed"] is True
    assert body["added"] == 0, "the PDF carries the six conditions the paste already had"
    assert body["status"] == ConditionRoundStatus.DRAFT.value
    assert body["sheet_format"] == "uwm_approval_letter"


async def test_the_response_reports_counts_never_the_lenders_words(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """⚠️ ADR-405. `unmatched_existing` is a NUMBER, and the test is built so it can actually FAIL.

    A round whose paste carries a condition the PDF does not is set up deliberately, so there IS a
    lender's sentence the response could leak. Asserting against a response with nothing to leak
    would be a guard with no failure mode — the fault this ticket's own review caught in my last
    commit.
    """
    company, token = await _user(db_session, slug="attach-counts")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    extra = (
        "Closing (PTF)\n 9999         Invoice                       Provide the parking receipt."
    )
    round_ = await create_round_from_paste(
        db_session,
        loan_file=loan_file,
        text=f"{portal_excerpt()}\n{extra}",
        completeness=ConditionRoundCompleteness.PARTIAL,
    )

    response = await client.post(_url(round_.id), headers=_auth(token), files=_pdf_part())
    body = response.json()

    assert response.status_code == 200, response.text
    # The set-up guarantees there is something unmatched, so the count is load-bearing.
    assert body["unmatched_existing"] == 1
    assert "Provide the parking receipt." not in response.text
    assert any("kept, not removed" in warning for warning in body["warnings"])


async def test_attaching_twice_is_refused(client: AsyncClient, db_session: AsyncSession) -> None:
    """The guard is "no PDF source yet", so the second attach refuses rather than merging the same
    sheet into the round again."""
    round_, token = await _pasted_round(db_session, slug="attach-twice")

    first = await client.post(_url(round_.id), headers=_auth(token), files=_pdf_part())
    second = await client.post(_url(round_.id), headers=_auth(token), files=_pdf_part())

    assert first.status_code == 200
    assert second.status_code == 409
    assert "already has the lender's PDF" in second.text


async def test_something_that_is_not_a_pdf_is_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    round_, token = await _pasted_round(db_session, slug="attach-notpdf")

    response = await client.post(
        _url(round_.id),
        headers=_auth(token),
        files={"file": ("notes.txt", b"just some text", "application/pdf")},
    )

    assert response.status_code == 422
    # ⚠️ THE MESSAGE THE CODE ACTUALLY EMITS, checked rather than guessed. Plain text is not
    # identifiable at all, so `assess` never reaches the "declared X but is Y" mismatch branch and
    # the honest sentence is that the type could not be established. An earlier version of this
    # test asserted "must be a PDF", which is the sentence for a file that sniffs as something
    # recognisable and wrong — a string the code never produces for this input.
    assert "could not be identified" in response.text


async def test_another_companys_round_is_a_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """CRITICAL: cross-tenant isolation, and this route cannot lean on `ScopedLoanFile` — the path
    has no loan file in it. The same 404 as a missing round: distinguishing them would confirm the
    id exists, an oracle over another tenant's rows."""
    round_a, _token_a = await _pasted_round(db_session, slug="attach-tenant-a")
    _company_b, token_b = await _user(db_session, slug="attach-tenant-b")

    response = await client.post(_url(round_a.id), headers=_auth(token_b), files=_pdf_part())

    assert response.status_code == 404
    # And nothing was merged into it.
    await db_session.refresh(round_a)
    assert round_a.header is None
    assert len(round_a.sources) == 1


async def test_a_missing_round_is_a_404(client: AsyncClient, db_session: AsyncSession) -> None:
    _company, token = await _user(db_session, slug="attach-missing")

    response = await client.post(_url(uuid4()), headers=_auth(token), files=_pdf_part())

    assert response.status_code == 404


async def test_an_unauthenticated_attach_is_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    round_, _token = await _pasted_round(db_session, slug="attach-anon")

    response = await client.post(_url(round_.id), files=_pdf_part())

    assert response.status_code == 401

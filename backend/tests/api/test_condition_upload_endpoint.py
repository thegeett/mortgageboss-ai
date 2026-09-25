"""The condition-sheet upload endpoint (LP-905 section 1, spec §6).

⚠️ THE CROSS-TENANT TEST IS THE POINT OF THIS FILE, and it was nearly deferred to section 2. The
review's argument for writing it now was cost rather than principle: the fixture, the pattern and a
worked example already exist (`tests/api/test_documents_endpoints.py`'s "CRITICAL: cross-tenant
isolation"), so it is a handful of lines against machinery that works. Deferring it would have left
this stage's signature failure in place for one more commit — a believed property with nothing
executing it — and the one time such a property was finally checked here, six of LP-904's guards
failed on their first run.

WHAT IS NOT TESTED HERE, AND WHERE IT IS. This file covers the door's REFUSALS — every test below
returns before the round is created. What happens to an accepted sheet is a property of
`parse_round`, which the door only enqueues, so it is pinned in `tests/tasks/test_condition_parse.py`
against a round created through the same `create_round_from_sheet` this endpoint calls.

⚠️ THAT SPLIT ONCE HID A REAL DEFECT, AND THE PARAGRAPH HERE HELPED. It used to say the success case
"belongs to section 2" and stop — which read as a plan and was treated as coverage. Section 2 then
tested the parse only for an upload whose rules READ cleanly, so the branch where a reader asks for
the AI went unexercised at every door but paste, and a sheet arriving as a PDF waited forever for a
split nobody queued. The parse tests are now parameterised over `PDF_UPLOAD` and `EMAIL` for exactly
that reason. A deferral is only honest while it names where the property actually gets checked.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pymupdf
import pytest
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.main import app
from app.models import Company, User, UserRole
from app.services.loan_files import create_loan_file
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """⚠️ SHADOWS THE ROOT `client` FIXTURE, AND MUST.

    `tests/conftest.py`'s `client` builds an `AsyncClient` over the app but overrides NOTHING, so the
    request resolves `get_db` to a fresh session of its own. The suite isolates tests by running each
    inside a transaction that is rolled back and never committed — so a user this test FLUSHED is
    invisible to that other session, `get_user_by_id` returns None, and `get_current_user` raises 401
    on every request.

    That is exactly how this file first failed: five tests returned 401 and the only one that passed
    was the one asserting 401, which made the failure look uniform rather than like a missing
    override. `tests/api/test_documents_endpoints.py` defines the same shadowing fixture for the same
    reason; there is no shared one to import.
    """

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_db, None)


async def _make_user(db: AsyncSession, *, slug: str) -> tuple[Company, User, str]:
    """A company with one processor, and a token for them — the repo's existing shape."""
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
    return company, user, create_access_token(user.id)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _url(loan_file_id: object) -> str:
    return f"/api/v1/loan-files/{loan_file_id}/condition-rounds/uploads"


def _pdf() -> bytes:
    document = pymupdf.open()
    document.new_page().insert_text((72.0, 100.0), "LOAN APPROVAL CONDITIONS", fontsize=9)
    return bytes(document.tobytes())


# --------------------------------------------------------------------------- #
# CRITICAL: cross-tenant isolation
# --------------------------------------------------------------------------- #


async def test_company_b_cannot_open_a_round_on_company_a_file(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """⚠️ 404, NOT 403 — the file is out of scope, not forbidden.

    `get_loan_file` builds from `_scoped(company_id)` and returns None for another company's file,
    so B is told the file does not exist rather than that it exists and is theirs to envy. And the
    service beneath takes no `company_id` at all: it derives every one — the storage path, the
    round, the event, the activity — from `loan_file.company_id`. A mismatched (company, file) pair
    is therefore UNCONSTRUCTIBLE rather than merely unchecked, which is a stronger property than a
    check performed after the lookup.
    """
    company_a, _user_a, _token_a = await _make_user(db_session, slug="cond-company-a")
    _company_b, _user_b, token_b = await _make_user(db_session, slug="cond-company-b")
    a_file = await create_loan_file(db_session, company_id=company_a.id)

    response = await client.post(
        _url(a_file.id),
        headers=_auth(token_b),
        files={"file": ("sheet.pdf", _pdf(), "application/pdf")},
    )

    assert response.status_code == 404


async def test_an_unauthenticated_upload_is_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company, _user, _token = await _make_user(db_session, slug="cond-company-anon")
    loan_file = await create_loan_file(db_session, company_id=company.id)

    response = await client.post(
        _url(loan_file.id), files={"file": ("sheet.pdf", _pdf(), "application/pdf")}
    )

    assert response.status_code == 401


# --------------------------------------------------------------------------- #
# Boundary validation
# --------------------------------------------------------------------------- #


async def test_a_non_pdf_is_refused_with_the_reason(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """422 with the service's own reason, never a generic failure (spec §9.8)."""
    company, _user, token = await _make_user(db_session, slug="cond-company-png")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    response = await client.post(
        _url(loan_file.id),
        headers=_auth(token),
        files={"file": ("sheet.pdf", png, "application/pdf")},
    )

    assert response.status_code == 422
    # The browser declared application/pdf, so the message quotes that claim back.
    assert "image/png" in str(response.json())


async def test_an_oversized_upload_is_refused_before_it_is_all_in_memory(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """413, from a CHUNKED read that aborts at the limit.

    The cap is lowered for the test rather than a 20 MB body being constructed: the property is that
    the read stops, and asserting it with real megabytes would only prove the machine has memory.

    ⚠️ THE PARAMETER MUST BE TYPED `pytest.MonkeyPatch`, AND AN EARLIER VERSION SAID `object`.
    That made it a plain annotation rather than a request for pytest's fixture, so nothing was
    patched, the cap stayed at 20 MB, and the upload ran to completion — failing much later on
    `ModuleNotFoundError: app.tasks.conditions`. The test was accidentally proving section 2's
    absence instead of the 413. The `# type: ignore[attr-defined]` I had added to quiet
    `object.setattr` silenced the one complaint that named the mistake.
    """
    from app.core.config import settings

    company, _user, token = await _make_user(db_session, slug="cond-company-big")
    loan_file = await create_loan_file(db_session, company_id=company.id)

    # The endpoint reads `settings.condition_sheet_max_bytes` at call time off the module-level
    # singleton, so patching the attribute is what takes effect.
    #
    # ⚠️ 100, NOT 1024 — the fixture PDF is 843 bytes, so a 1024-byte cap would not be exceeded and
    # this test would pass through to the success path while still claiming to assert a 413. The cap
    # is lowered below the real payload rather than the payload padded above the cap: the property
    # is that the chunked read ABORTS, and a megabyte of filler would only prove the machine has
    # memory.
    monkeypatch.setattr(settings, "condition_sheet_max_bytes", 100)

    response = await client.post(
        _url(loan_file.id),
        headers=_auth(token),
        files={"file": ("sheet.pdf", _pdf(), "application/pdf")},
    )

    assert response.status_code == 413
    assert "limit" in str(response.json())


async def test_an_empty_upload_is_refused(client: AsyncClient, db_session: AsyncSession) -> None:
    company, _user, token = await _make_user(db_session, slug="cond-company-empty")
    loan_file = await create_loan_file(db_session, company_id=company.id)

    response = await client.post(
        _url(loan_file.id),
        headers=_auth(token),
        files={"file": ("sheet.pdf", b"", "application/pdf")},
    )

    assert response.status_code == 422


async def test_an_unknown_loan_file_is_a_404(client: AsyncClient, db_session: AsyncSession) -> None:
    from uuid import uuid4

    _company, _user, token = await _make_user(db_session, slug="cond-company-missing")

    response = await client.post(
        _url(uuid4()),
        headers=_auth(token),
        files={"file": ("sheet.pdf", _pdf(), "application/pdf")},
    )

    assert response.status_code == 404

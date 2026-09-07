"""LP-815 — the only unauthenticated surface in this codebase.

`POST /api/v1/upload/{token}` writes a document onto a loan file with no session, no user and no
company: the token in the path is the entire credential. So these cases are about what that costs
and what bounds it.

THE PROBING TESTS ARE THE POINT. A token is guessed by trying, and every distinguishable answer is a
rung on that ladder — "expired" confirms a token existed, "wrong file" confirms one exists somewhere.
Unknown, expired, revoked and spent must be one answer, and each of those states is built for real
here rather than asserted about a fixture that could not reach them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest_asyncio
from app.core.database import get_db
from app.main import app
from app.models import Company, LoanProgram, User, UserRole
from app.models.base import utcnow
from app.models.document import Document, UploadSource
from app.models.upload_link import UploadLink, hash_token
from app.services.loan_files import create_loan_file
from app.services.upload_links import mint_upload_link
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

API = "/api/v1"
_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "attachments"
_PDF = (_FIXTURES / "clean.pdf").read_bytes()
_ZIP_AS_PDF = (_FIXTURES / "zip_named_as.pdf").read_bytes()


@pytest_asyncio.fixture
async def db(test_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    connection = await test_engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


@pytest_asyncio.fixture
async def client(db: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    try:
        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as http_client:
            yield http_client
    finally:
        app.dependency_overrides.pop(get_db, None)


async def _company_user_token(db: AsyncSession, *, slug: str):
    from app.core.jwt import create_access_token

    company = Company(name=slug, slug=f"{slug}-{uuid4().hex[:6]}")
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id,
        email=f"u-{uuid4().hex[:6]}@{slug}.com",
        hashed_password="x",  # pragma: allowlist secret
        first_name="Pat",
        last_name="Processor",
        role=UserRole.PROCESSOR,
    )
    db.add(user)
    await db.flush()
    return company, create_access_token(user.id)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _file_with_link(db: AsyncSession, *, slug: str, **kwargs):
    company, jwt = await _company_user_token(db, slug=slug)
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    minted = await mint_upload_link(db, loan_file=loan_file, **kwargs)
    return company, jwt, loan_file, minted


# --------------------------------------------------------------------------------------------- #
# The token is never stored, and never handed back
# --------------------------------------------------------------------------------------------- #
async def test_the_row_holds_a_hash_and_not_the_token(db: AsyncSession) -> None:
    """THE DIFFERENCE FROM `inbox_token`, which is stored in the clear because a borrower types it.

    Nobody has to recognise this one, so a database read — a backup, a readonly view, a dump — is
    not a way in.
    """
    _company, _jwt, _loan_file, minted = await _file_with_link(db, slug="hashed")

    assert minted.link.token_hash != minted.token
    assert minted.link.token_hash == hash_token(minted.token)
    assert len(minted.link.token_hash) == 64
    assert minted.token not in minted.link.token_hash


async def test_listing_links_never_carries_a_token(client: AsyncClient, db: AsyncSession) -> None:
    """There is none to carry, and the list must not grow one by accident."""
    _company, jwt, loan_file, minted = await _file_with_link(db, slug="listed")
    await db.commit()

    resp = await client.get(
        f"{API}/loan-files/{loan_file.display_id}/upload-links", headers=_auth(jwt)
    )

    assert resp.status_code == 200
    body = resp.text
    assert minted.token not in body
    assert minted.link.token_hash not in body


async def test_minting_returns_the_url_once(client: AsyncClient, db: AsyncSession) -> None:
    company, jwt = await _company_user_token(db, slug="minted")
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    await db.commit()

    resp = await client.post(
        f"{API}/loan-files/{loan_file.display_id}/upload-links",
        json={"recipient_email": "jane@example.com"},
        headers=_auth(jwt),
    )

    assert resp.status_code == 201
    url = resp.json()["url"]
    assert "/upload/" in url
    # The row that was created holds only the hash of what is in that URL.
    token = url.rsplit("/", 1)[-1]
    stored = (
        await db.execute(select(UploadLink).where(UploadLink.loan_file_id == loan_file.id))
    ).scalar_one()
    assert stored.token_hash == hash_token(token)


# --------------------------------------------------------------------------------------------- #
# Probing — every failure is one answer
# --------------------------------------------------------------------------------------------- #
async def test_unknown_expired_revoked_and_spent_are_indistinguishable(
    client: AsyncClient, db: AsyncSession
) -> None:
    """FOUR REAL STATES, each built rather than asserted about.

    Every distinguishable answer is a rung on the ladder a token is guessed by: "expired" confirms a
    token existed, which is more than a guesser had before they asked.
    """
    _c1, _j1, _f1, expired = await _file_with_link(db, slug="probe-expired")
    expired.link.expires_at = utcnow() - timedelta(hours=1)
    _c2, _j2, _f2, revoked = await _file_with_link(db, slug="probe-revoked")
    revoked.link.revoked_at = utcnow()
    _c3, _j3, _f3, spent = await _file_with_link(db, slug="probe-spent", max_uses=1)
    spent.link.uses = 1
    await db.commit()

    answers = []
    for token in ("never-existed-at-all", expired.token, revoked.token, spent.token):
        resp = await client.get(f"{API}/upload/{token}")
        answers.append((resp.status_code, resp.json()))

    assert {status for status, _ in answers} == {404}
    assert len({repr(body) for _, body in answers}) == 1


async def test_a_live_link_describes_itself(client: AsyncClient, db: AsyncSession) -> None:
    """THE CONTROL. Without it, the four-way test above passes against a route that 404s always."""
    _company, _jwt, loan_file, minted = await _file_with_link(
        db, slug="describe", purpose="Documents for your loan application"
    )
    await db.commit()

    resp = await client.get(f"{API}/upload/{minted.token}")

    assert resp.status_code == 200
    assert resp.json()["reference"] == loan_file.display_id
    assert resp.json()["purpose"] == "Documents for your loan application"


async def test_the_page_names_nobody(client: AsyncClient, db: AsyncSession) -> None:
    """Anyone the borrower forwarded the email to holds this link. A page confirming "yes, Jane
    Borrower, 42 Maple Avenue" turns a leaked link into a disclosure as well as a write.

    Asserted against a file that HAS a borrower and a property, so the absence is a choice.
    """
    from app.models.borrower import Borrower
    from app.models.property import Property

    _company, _jwt, loan_file, minted = await _file_with_link(db, slug="anonymous")
    db.add(
        Borrower(
            loan_file_id=loan_file.id,
            first_name="Jane",
            last_name="Borrower",
            email="jane@example.com",
            is_primary=True,
        )
    )
    db.add(Property(loan_file_id=loan_file.id, address_line="42 Maple Avenue"))
    await db.commit()

    body = (await client.get(f"{API}/upload/{minted.token}")).text

    assert "Jane" not in body
    assert "Maple" not in body
    assert "jane@example.com" not in body


# --------------------------------------------------------------------------------------------- #
# Redeeming
# --------------------------------------------------------------------------------------------- #
async def test_a_borrower_uploads_with_no_session(client: AsyncClient, db: AsyncSession) -> None:
    """No Authorization header anywhere in this request. The token is the whole credential."""
    _company, _jwt, loan_file, minted = await _file_with_link(db, slug="upload")
    await db.commit()

    resp = await client.post(
        f"{API}/upload/{minted.token}",
        files={"file": ("statement.pdf", _PDF, "application/pdf")},
    )

    assert resp.status_code == 201
    document = (
        await db.execute(select(Document).where(Document.loan_file_id == loan_file.id))
    ).scalar_one()
    assert document.upload_source is UploadSource.SECURE_LINK
    # ADR-056 — a borrower delivered this. Naming the processor who minted the link would make the
    # provenance say something untrue.
    assert document.uploaded_by_user_id is None
    assert document.file_size_bytes == len(_PDF)


async def test_the_stored_bytes_are_the_uploaded_bytes(
    client: AsyncClient, db: AsyncSession
) -> None:
    """THE LP-806 LESSON. A recorded size taken from anywhere but the bytes agrees with a document
    containing something else, and it is the one number anybody would check."""
    from app.storage import get_storage_backend

    _company, _jwt, loan_file, minted = await _file_with_link(db, slug="bytes")
    await db.commit()

    await client.post(
        f"{API}/upload/{minted.token}", files={"file": ("s.pdf", _PDF, "application/pdf")}
    )

    document = (
        await db.execute(select(Document).where(Document.loan_file_id == loan_file.id))
    ).scalar_one()
    assert await get_storage_backend().read(document.storage_path) == _PDF


async def test_an_unsafe_file_is_refused_with_a_reason(
    client: AsyncClient, db: AsyncSession
) -> None:
    """THE SAME GATE AS INBOUND MAIL, and it must be: a stranger's bytes over a channel whose only
    authentication is a token in a URL is the inbound-attachment threat model exactly.

    The REASON reaches the borrower, because "rejected" makes them send the same file again.
    """
    _company, _jwt, loan_file, minted = await _file_with_link(db, slug="unsafe")
    await db.commit()

    resp = await client.post(
        f"{API}/upload/{minted.token}",
        files={"file": ("everything.pdf", _ZIP_AS_PDF, "application/pdf")},
    )

    assert resp.status_code == 400
    assert "zip" in resp.json()["error"]["message"].lower()
    assert (
        await db.execute(select(Document).where(Document.loan_file_id == loan_file.id))
    ).first() is None


async def test_an_oversized_file_is_refused(client: AsyncClient, db: AsyncSession) -> None:
    """A route anybody can reach with no size bound is a way to fill a bucket."""
    from app.services.upload_links import MAX_UPLOAD_BYTES

    _company, _jwt, _loan_file, minted = await _file_with_link(db, slug="huge")
    await db.commit()

    resp = await client.post(
        f"{API}/upload/{minted.token}",
        files={"file": ("big.pdf", b"%PDF-" + b"0" * MAX_UPLOAD_BYTES, "application/pdf")},
    )

    assert resp.status_code == 400
    assert "larger than" in resp.json()["error"]["message"]


async def test_the_use_counter_bounds_a_leaked_link(client: AsyncClient, db: AsyncSession) -> None:
    _company, _jwt, _loan_file, minted = await _file_with_link(db, slug="spent", max_uses=1)
    await db.commit()

    first = await client.post(
        f"{API}/upload/{minted.token}", files={"file": ("a.pdf", _PDF, "application/pdf")}
    )
    second = await client.post(
        f"{API}/upload/{minted.token}", files={"file": ("b.pdf", _PDF, "application/pdf")}
    )

    assert first.status_code == 201
    assert second.status_code == 404


async def test_a_refused_upload_does_not_spend_a_use(client: AsyncClient, db: AsyncSession) -> None:
    """THE COUNTER MOVES ON A DELIVERED DOCUMENT. A borrower whose first attempt was a zip must not
    be locked out of their remaining tries by the mistake."""
    _company, _jwt, _loan_file, minted = await _file_with_link(db, slug="nospend", max_uses=1)
    await db.commit()

    refused = await client.post(
        f"{API}/upload/{minted.token}", files={"file": ("z.pdf", _ZIP_AS_PDF, "application/pdf")}
    )
    accepted = await client.post(
        f"{API}/upload/{minted.token}", files={"file": ("a.pdf", _PDF, "application/pdf")}
    )

    assert refused.status_code == 400
    assert accepted.status_code == 201


async def test_the_response_says_nothing_about_the_file(
    client: AsyncClient, db: AsyncSession
) -> None:
    """An acknowledgement and a refusal reason are the whole vocabulary. Anything else is a read
    primitive on a write-only capability."""
    _company, _jwt, loan_file, minted = await _file_with_link(db, slug="quiet")
    await db.commit()

    resp = await client.post(
        f"{API}/upload/{minted.token}", files={"file": ("a.pdf", _PDF, "application/pdf")}
    )

    assert resp.json() == {"status": "received"}
    assert loan_file.display_id not in resp.text


# --------------------------------------------------------------------------------------------- #
# Revoking, and the file-scoped side
# --------------------------------------------------------------------------------------------- #
async def test_revoking_stops_a_live_link(client: AsyncClient, db: AsyncSession) -> None:
    _company, jwt, loan_file, minted = await _file_with_link(db, slug="revoke")
    await db.commit()
    assert (await client.get(f"{API}/upload/{minted.token}")).status_code == 200

    revoked = await client.delete(
        f"{API}/loan-files/{loan_file.display_id}/upload-links/{minted.link.id}",
        headers=_auth(jwt),
    )

    assert revoked.status_code == 200
    assert (await client.get(f"{API}/upload/{minted.token}")).status_code == 404


async def test_another_companys_link_cannot_be_revoked(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A REAL link on a real other company's file, and the same 404 as one that never existed."""
    _theirs, _their_jwt, _their_file, theirs = await _file_with_link(db, slug="rev-theirs")
    _mine, my_jwt = await _company_user_token(db, slug="rev-mine")
    my_file = await create_loan_file(db, company_id=_mine.id, loan_program=LoanProgram.CONVENTIONAL)
    await db.commit()

    real_but_theirs = await client.delete(
        f"{API}/loan-files/{my_file.display_id}/upload-links/{theirs.link.id}",
        headers=_auth(my_jwt),
    )
    never_existed = await client.delete(
        f"{API}/loan-files/{my_file.display_id}/upload-links/{uuid4()}", headers=_auth(my_jwt)
    )

    assert real_but_theirs.status_code == never_existed.status_code == 404
    assert real_but_theirs.json() == never_existed.json()
    # And it is still live for the company that owns it.
    assert (await client.get(f"{API}/upload/{theirs.token}")).status_code == 200


async def test_another_companys_file_cannot_be_minted_against(
    client: AsyncClient, db: AsyncSession
) -> None:
    theirs, _their_jwt = await _company_user_token(db, slug="mint-theirs")
    _mine, my_jwt = await _company_user_token(db, slug="mint-mine")
    their_file = await create_loan_file(
        db, company_id=theirs.id, loan_program=LoanProgram.CONVENTIONAL
    )
    await db.commit()

    resp = await client.post(
        f"{API}/loan-files/{their_file.display_id}/upload-links", json={}, headers=_auth(my_jwt)
    )

    assert resp.status_code == 404


async def test_the_four_states_are_indistinguishable_on_the_WRITE_path_too(
    client: AsyncClient, db: AsyncSession
) -> None:
    """The same four states, against POST rather than GET (review finding).

    `test_unknown_expired_revoked_and_spent_are_indistinguishable` pins the property on the describe
    route. Both endpoints happen to share `resolve_link`, so POST behaves identically today — which
    is exactly why the property is pinned where it was tested rather than where it has to hold.
    Move the usability check out of `resolve_link` into the GET handler, or give POST its own
    resolution path, and this endpoint starts answering differently with nothing failing.

    POST is the more dangerous of the two to leak state from: it is the one that writes, so a
    distinguishable refusal tells a prober which token is worth spending an upload on.
    """
    _c1, _j1, _f1, expired = await _file_with_link(db, slug="post-expired")
    expired.link.expires_at = utcnow() - timedelta(hours=1)
    _c2, _j2, _f2, revoked = await _file_with_link(db, slug="post-revoked")
    revoked.link.revoked_at = utcnow()
    _c3, _j3, _f3, spent = await _file_with_link(db, slug="post-spent", max_uses=1)
    spent.link.uses = 1
    await db.commit()

    answers = []
    for token in ("never-existed-at-all", expired.token, revoked.token, spent.token):
        resp = await client.post(
            f"{API}/upload/{token}",
            files={"file": ("statement.pdf", _PDF, "application/pdf")},
        )
        answers.append((resp.status_code, resp.json()))

    assert {status for status, _ in answers} == {404}
    assert len({repr(body) for _, body in answers}) == 1


async def test_a_live_link_still_accepts_on_the_write_path(
    client: AsyncClient, db: AsyncSession
) -> None:
    """The control for the four-way POST test, and it has to actually POST.

    Four refusals that all look alike is also what a route refusing everything produces. My first
    version of this asserted that the other test function existed, which is a tautology wearing a
    control's name — the shape this review has spent its time objecting to.
    """
    _company, _jwt, loan_file, minted = await _file_with_link(db, slug="post-live")
    await db.commit()

    resp = await client.post(
        f"{API}/upload/{minted.token}",
        files={"file": ("statement.pdf", _PDF, "application/pdf")},
    )

    assert resp.status_code == 201
    assert (
        await db.execute(select(Document).where(Document.loan_file_id == loan_file.id))
    ).scalar_one() is not None

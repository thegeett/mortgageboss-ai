"""Endpoint tests for LP-71 — document replace, versions, and staleness resolution.

The replace flow (old → historical, new → current, both kept, audited, processing
enqueued for the new), the version-history endpoint, and the staleness resolve
(waive/accept, audited). Plus the tenant gate (404 cross-company) and the 409 when
replacing a non-current version.
"""

from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from app.api import documents as documents_api
from app.core.config import settings
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.main import app
from app.models import Company, User, UserRole
from app.models.document import Document, DocumentStatus, StalenessResolution, UploadSource
from app.services.loan_files import create_loan_file
from app.storage import get_storage_backend
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

PDF_BYTES = b"%PDF-1.7\n%corrected statement\n"


@pytest.fixture(autouse=True)
def _storage_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "storage_local_path", str(tmp_path / "storage"))
    get_storage_backend.cache_clear()
    yield
    get_storage_backend.cache_clear()


@pytest.fixture(autouse=True)
def _mock_enqueue(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    delay = MagicMock()
    monkeypatch.setattr(documents_api.process_document, "delay", delay)
    return delay


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


async def _make_user(db: AsyncSession, *, slug: str) -> tuple[Company, User, str]:
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


async def _document(db: AsyncSession, loan_file_id, *, document_type: str = "bank_statement"):
    doc = Document(
        loan_file_id=loan_file_id,
        original_filename="statement.pdf",
        mime_type="application/pdf",
        file_size_bytes=10,
        storage_path=f"{loan_file_id}/orig.pdf",
        document_type=document_type,
        status=DocumentStatus.COMPLETED,
        upload_source=UploadSource.USER_UPLOAD,
    )
    db.add(doc)
    await db.flush()
    return doc


async def _activity_types(client: AsyncClient, ident: str, token: str) -> set[str]:
    rows = (await client.get(f"/api/v1/loan-files/{ident}/activity", headers=_auth(token))).json()
    return {entry["activity_type"] for entry in rows}


# --------------------------------------------------------------------------- #
# Replace
# --------------------------------------------------------------------------- #


async def test_replace_supersedes_and_returns_current(
    client: AsyncClient, db_session: AsyncSession, _mock_enqueue: MagicMock
) -> None:
    company, _user, token = await _make_user(db_session, slug="acme")
    lf = await create_loan_file(db_session, company_id=company.id)
    old = await _document(db_session, lf.id)

    resp = await client.post(
        f"/api/v1/documents/{old.id}/replace",
        headers=_auth(token),
        files=[("file", ("corrected.pdf", PDF_BYTES, "application/pdf"))],
    )
    assert resp.status_code == 201
    new = resp.json()
    assert new["is_current"] is True
    assert new["version"] == 2
    assert new["version_count"] == 2
    assert new["supersedes_document_id"] == str(old.id)
    # The new version's processing was enqueued.
    _mock_enqueue.assert_called_once()

    # The old document is now historical (both kept).
    await db_session.refresh(old)
    assert old.is_current is False
    assert old.deleted_at is None
    assert "document_replaced" in await _activity_types(client, lf.display_id, token)


async def test_replace_lists_both_versions(client: AsyncClient, db_session: AsyncSession) -> None:
    company, _user, token = await _make_user(db_session, slug="acme")
    lf = await create_loan_file(db_session, company_id=company.id)
    old = await _document(db_session, lf.id)
    await client.post(
        f"/api/v1/documents/{old.id}/replace",
        headers=_auth(token),
        files=[("file", ("corrected.pdf", PDF_BYTES, "application/pdf"))],
    )

    versions = (
        await client.get(f"/api/v1/documents/{old.id}/versions", headers=_auth(token))
    ).json()
    assert len(versions) == 2
    assert [v["version"] for v in versions] == [1, 2]  # oldest → newest
    assert [v["is_current"] for v in versions] == [False, True]
    # Fitness: the historical one is superseded, the current is fit.
    by_version = {v["version"]: v for v in versions}
    assert by_version[1]["package_fit"]["reason"] == "superseded"
    assert by_version[2]["package_fit"]["fit"] is True


async def test_replacing_a_historical_version_is_409(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company, _user, token = await _make_user(db_session, slug="acme")
    lf = await create_loan_file(db_session, company_id=company.id)
    old = await _document(db_session, lf.id)
    await client.post(
        f"/api/v1/documents/{old.id}/replace",
        headers=_auth(token),
        files=[("file", ("v2.pdf", PDF_BYTES, "application/pdf"))],
    )
    # old is now historical — replacing it again is a conflict.
    resp = await client.post(
        f"/api/v1/documents/{old.id}/replace",
        headers=_auth(token),
        files=[("file", ("v3.pdf", PDF_BYTES, "application/pdf"))],
    )
    assert resp.status_code == 409


async def test_replace_cross_company_is_404(client: AsyncClient, db_session: AsyncSession) -> None:
    company_b, _ub, _tb = await _make_user(db_session, slug="globex")
    _ca, _ua, token_a = await _make_user(db_session, slug="acme")
    lf_b = await create_loan_file(db_session, company_id=company_b.id)
    doc_b = await _document(db_session, lf_b.id)

    resp = await client.post(
        f"/api/v1/documents/{doc_b.id}/replace",
        headers=_auth(token_a),
        files=[("file", ("x.pdf", PDF_BYTES, "application/pdf"))],
    )
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# Staleness resolution
# --------------------------------------------------------------------------- #


async def test_resolve_staleness_waive(client: AsyncClient, db_session: AsyncSession) -> None:
    company, _user, token = await _make_user(db_session, slug="acme")
    lf = await create_loan_file(db_session, company_id=company.id)
    doc = await _document(db_session, lf.id)

    resp = await client.post(
        f"/api/v1/documents/{doc.id}/resolve-staleness",
        headers=_auth(token),
        json={"action": "waive", "reason": "lender accepted the prior period"},
    )
    assert resp.status_code == 200
    await db_session.refresh(doc)
    assert doc.staleness_resolution is StalenessResolution.WAIVED
    assert "document_staleness_resolved" in await _activity_types(client, lf.display_id, token)


async def test_resolve_staleness_accept(client: AsyncClient, db_session: AsyncSession) -> None:
    company, _user, token = await _make_user(db_session, slug="acme")
    lf = await create_loan_file(db_session, company_id=company.id)
    doc = await _document(db_session, lf.id)

    resp = await client.post(
        f"/api/v1/documents/{doc.id}/resolve-staleness",
        headers=_auth(token),
        json={"action": "accept"},
    )
    assert resp.status_code == 200
    await db_session.refresh(doc)
    assert doc.staleness_resolution is StalenessResolution.ACCEPTED


async def test_resolve_staleness_bad_action_is_422(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company, _user, token = await _make_user(db_session, slug="acme")
    lf = await create_loan_file(db_session, company_id=company.id)
    doc = await _document(db_session, lf.id)
    resp = await client.post(
        f"/api/v1/documents/{doc.id}/resolve-staleness",
        headers=_auth(token),
        json={"action": "delete"},
    )
    assert resp.status_code == 422


async def test_resolve_staleness_cross_company_is_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company_b, _ub, _tb = await _make_user(db_session, slug="globex")
    _ca, _ua, token_a = await _make_user(db_session, slug="acme")
    lf_b = await create_loan_file(db_session, company_id=company_b.id)
    doc_b = await _document(db_session, lf_b.id)
    resp = await client.post(
        f"/api/v1/documents/{doc_b.id}/resolve-staleness",
        headers=_auth(token_a),
        json={"action": "waive"},
    )
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# A normal upload is standalone/current (multiples not auto-replaced)
# --------------------------------------------------------------------------- #


async def test_normal_upload_is_current_standalone(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company, _user, token = await _make_user(db_session, slug="acme")
    lf = await create_loan_file(db_session, company_id=company.id)
    resp = await client.post(
        f"/api/v1/loan-files/{lf.display_id}/documents",
        headers=_auth(token),
        files=[("files", ("paystub.pdf", PDF_BYTES, "application/pdf"))],
    )
    assert resp.status_code == 201
    doc = resp.json()[0]
    assert doc["is_current"] is True
    assert doc["version"] == 1
    assert doc["version_count"] == 1
    assert doc["package_fit"]["fit"] is True  # current + (no date yet) fresh

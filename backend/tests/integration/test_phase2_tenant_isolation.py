"""LP-73 tenant-isolation pass — a Company A user can't reach Company B's Phase-2 data.

A multi-tenant tool with borrower PII must never leak across companies. This sweeps the
Phase-2 surfaces (documents + versioning/staleness, the tier-detail/naming/qualification
responses, the needs list + disposition flow, activity) and asserts a cross-company
request gets ``404`` — never another company's data, never a ``403`` that confirms
existence. (Per-feature 404 tests exist; this is the consolidated capstone sweep.)
"""

from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from app.api import documents as documents_api
from app.core.config import settings
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.main import app
from app.models import Company, User, UserRole
from app.models.document import Document, DocumentStatus, UploadSource
from app.services.loan_files import create_loan_file
from app.services.needs_items import create_needs_item
from app.storage import get_storage_backend
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture(autouse=True)
def _storage_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "storage_local_path", str(tmp_path / "storage"))
    get_storage_backend.cache_clear()
    yield
    get_storage_backend.cache_clear()


@pytest.fixture(autouse=True)
def _mock_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(documents_api.process_document, "delay", MagicMock())


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


async def _company_user(db: AsyncSession, slug: str) -> tuple[Company, str]:
    company = Company(name=slug.title(), slug=slug)
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id,
        email=f"u@{slug}.com",
        hashed_password=hash_password("x"),
        first_name="T",
        last_name="U",
        role=UserRole.PROCESSOR,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return company, create_access_token(user.id)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_phase2_surfaces_are_tenant_isolated(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # Company B owns a file + a document + a need; Company A holds a token only.
    company_b, _token_b = await _company_user(db_session, "globex")
    _company_a, token_a = await _company_user(db_session, "acme")
    lf_b = await create_loan_file(db_session, company_id=company_b.id)
    need_b = await create_needs_item(
        db_session, loan_file_id=lf_b.id, title="Pay stubs", needs_type="pay_stub"
    )
    doc_b = Document(
        loan_file_id=lf_b.id,
        original_filename="b.pdf",
        mime_type="application/pdf",
        file_size_bytes=10,
        storage_path="b/orig.pdf",
        document_type="pay_stub",
        status=DocumentStatus.COMPLETED,
        upload_source=UploadSource.USER_UPLOAD,
    )
    db_session.add(doc_b)
    await db_session.flush()
    fid, did, nid = lf_b.display_id, doc_b.id, need_b.id
    pdf = ("file", ("x.pdf", b"%PDF-1.7\nx", "application/pdf"))
    a = _auth(token_a)

    # Every Phase-2 read/write of Company B's data, by Company A, must 404.
    cases: list[tuple[str, str, dict]] = [
        # Documents + LP-71/72 (list carries tier/standard_name/qualification).
        ("get", f"/api/v1/loan-files/{fid}/documents", {}),
        ("get", f"/api/v1/documents/{did}", {}),  # tier-aware detail + naming + qualification
        ("get", f"/api/v1/documents/{did}/versions", {}),
        ("get", f"/api/v1/documents/{did}/download", {}),
        ("delete", f"/api/v1/documents/{did}", {}),
        ("post", f"/api/v1/documents/{did}/replace", {"files": [pdf]}),
        ("post", f"/api/v1/documents/{did}/resolve-staleness", {"json": {"action": "waive"}}),
        # Needs list + disposition flow (LP-70).
        ("get", f"/api/v1/loan-files/{fid}/needs", {}),
        ("post", f"/api/v1/loan-files/{fid}/needs", {"json": {"title": "X"}}),
        ("post", f"/api/v1/loan-files/{fid}/needs/{nid}/confirm", {}),
        ("post", f"/api/v1/loan-files/{fid}/needs/{nid}/dismiss", {"json": {"reason": "no"}}),
        ("post", f"/api/v1/loan-files/{fid}/needs/{nid}/waive", {"json": {"reason": "no"}}),
        ("patch", f"/api/v1/loan-files/{fid}/needs/{nid}", {"json": {"title": "Y"}}),
        # Activity timeline (records Phase-2 events).
        ("get", f"/api/v1/loan-files/{fid}/activity", {}),
    ]

    for method, url, kwargs in cases:
        resp = await getattr(client, method)(url, headers=a, **kwargs)
        assert resp.status_code == 404, f"{method.upper()} {url} leaked (got {resp.status_code})"


async def test_unknown_ids_also_404(client: AsyncClient, db_session: AsyncSession) -> None:
    """A nonexistent id is indistinguishable from a cross-company one (both 404)."""
    _company, token = await _company_user(db_session, "acme")
    a = _auth(token)
    assert (await client.get(f"/api/v1/documents/{uuid4()}", headers=a)).status_code == 404
    assert (await client.get(f"/api/v1/documents/{uuid4()}/versions", headers=a)).status_code == 404

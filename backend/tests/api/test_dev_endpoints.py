"""Tests for the dev-only text-layer extraction endpoint (LP-40).

The endpoint is a dev tool, but it touches real documents, so the cruxes are the
same as any flat route: **tenant scoping** (a Company A user can't extract a
Company B document) and **auth**. Plus the LP-40-specific concerns: **production
gating** (the dev router is absent in production) and the **PDF-only** response.
No AI here — the extractor is deterministic — so no key is needed.
"""

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pymupdf
import pytest
import pytest_asyncio
from app.core.config import settings
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.main import app
from app.models import Company, User, UserRole
from app.services.documents import create_document
from app.services.loan_files import create_loan_file
from app.storage import get_storage_backend
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


def _make_pdf(text: str = "Employer ACME Corp gross pay 4200 net 3180 ytd 50400") -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    data: bytes = doc.tobytes()
    doc.close()
    return data


@pytest.fixture(autouse=True)
def _storage_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the storage backend at an isolated temp dir (never the real ./storage)."""
    monkeypatch.setattr(settings, "storage_local_path", str(tmp_path / "storage"))
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


async def _store_document(
    db: AsyncSession,
    *,
    company: Company,
    user: User,
    content: bytes,
    mime_type: str = "application/pdf",
    filename: str = "paystub.pdf",
) -> str:
    """Create a loan file + a stored document; return the document id (str)."""
    loan_file = await create_loan_file(db, company_id=company.id)
    document_id = uuid4()
    storage_path = await get_storage_backend().save(
        company_id=company.id,
        file_id=loan_file.id,
        document_id=document_id,
        filename=filename,
        content=content,
    )
    await create_document(
        db,
        loan_file=loan_file,
        document_id=document_id,
        filename=filename,
        mime_type=mime_type,
        size=len(content),
        storage_path=storage_path,
        uploaded_by_user_id=user.id,
    )
    return str(document_id)


def _url(document_id: str) -> str:
    return f"/api/v1/dev/documents/{document_id}/extract-text-layer"


# --------------------------------------------------------------------------- #
# Success + PDF-only
# --------------------------------------------------------------------------- #


async def test_extract_text_layer_returns_text(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company, user, token = await _make_user(db_session, slug="acme")
    doc_id = await _store_document(db_session, company=company, user=user, content=_make_pdf())

    resp = await client.post(_url(doc_id), headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["extraction_ok"] is True
    assert body["has_text"] is True
    assert body["page_count"] == 1
    assert "ACME Corp" in body["text"]  # text returned for inspection


async def test_non_pdf_document_returns_pdf_only(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company, user, token = await _make_user(db_session, slug="acme")
    doc_id = await _store_document(
        db_session,
        company=company,
        user=user,
        content=b"\x89PNG\r\n\x1a\n image bytes",
        mime_type="image/png",
        filename="scan.png",
    )
    resp = await client.post(_url(doc_id), headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["extraction_ok"] is False
    assert body["error_reason"] == "text-layer extraction supports PDF only"


# --------------------------------------------------------------------------- #
# Tenant scoping + auth
# --------------------------------------------------------------------------- #


async def test_cross_tenant_is_404(client: AsyncClient, db_session: AsyncSession) -> None:
    company_a, user_a, _a_token = await _make_user(db_session, slug="company-a")
    _company_b, _ub, b_token = await _make_user(db_session, slug="company-b")
    doc_id = await _store_document(db_session, company=company_a, user=user_a, content=_make_pdf())
    # Company B cannot extract Company A's document.
    resp = await client.post(_url(doc_id), headers=_auth(b_token))
    assert resp.status_code == 404


async def test_unauthenticated_is_401(client: AsyncClient, db_session: AsyncSession) -> None:
    company, user, _token = await _make_user(db_session, slug="acme")
    doc_id = await _store_document(db_session, company=company, user=user, content=_make_pdf())
    assert (await client.post(_url(doc_id))).status_code == 401


# --------------------------------------------------------------------------- #
# Production gating — the dev router is mounted only when not is_production
# --------------------------------------------------------------------------- #

_DEV_ROUTE = "/api/v1/dev/documents/{document_id}/extract-text-layer"


def _mount_like_main(target: FastAPI) -> None:
    """Apply main.py's exact dev-router mount condition to a fresh app."""
    if not settings.is_production:
        from app.api.dev import dev_router

        target.include_router(dev_router, prefix="/api/v1/dev")


def test_dev_router_present_outside_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "environment", "development")
    assert settings.is_production is False
    fresh = FastAPI()
    _mount_like_main(fresh)
    assert _DEV_ROUTE in {r.path for r in fresh.routes}


def test_dev_router_absent_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "environment", "production")
    assert settings.is_production is True
    fresh = FastAPI()
    _mount_like_main(fresh)
    # In production the dev router is never mounted → the route is absent.
    assert _DEV_ROUTE not in {r.path for r in fresh.routes}


async def test_dev_route_404s_in_production_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """A production-configured app returns 404 for the (unmounted) dev route."""
    monkeypatch.setattr(settings, "environment", "production")
    prod_app = FastAPI()
    _mount_like_main(prod_app)
    async with AsyncClient(transport=ASGITransport(app=prod_app), base_url="http://test") as c:
        resp = await c.post(_DEV_ROUTE.format(document_id=uuid4()))
    assert resp.status_code == 404

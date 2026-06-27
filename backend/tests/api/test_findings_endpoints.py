"""Endpoint tests for document findings (LP-66) — visibility + tenant isolation.

The crux: findings are VISIBLE (a loan file's findings are listed) but a Company A
user must never read Company B's findings (the loan file is company-scope-checked,
so a cross-company file id → ``404`` and its findings are unreachable).
"""

from collections.abc import AsyncIterator
from decimal import Decimal
from uuid import uuid4

import pytest_asyncio
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.main import app
from app.models import Company, User, UserRole
from app.models.document import Document, DocumentStatus
from app.models.document_finding import DocumentFindingType
from app.services.document_findings import create_document_finding
from app.services.loan_files import create_loan_file
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


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


async def _make_user(db: AsyncSession, *, slug: str) -> tuple[Company, str]:
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


async def _make_doc_with_finding(db: AsyncSession, company: Company):
    loan_file = await create_loan_file(db, company_id=company.id)
    doc = Document(
        id=uuid4(),
        loan_file_id=loan_file.id,
        original_filename="x.pdf",
        mime_type="application/pdf",
        file_size_bytes=10,
        storage_path=f"{company.id}/{loan_file.id}/x.pdf",
        status=DocumentStatus.COMPLETED,
        upload_source="user_upload",
    )
    db.add(doc)
    await db.flush()
    await create_document_finding(
        db,
        document=doc,
        finding_type=DocumentFindingType.OBLIGATION,
        description="child support obligation (monthly)",
        amount=Decimal("1200.00"),
        frequency="monthly",
        details={"payer": "John Doe"},
    )
    await db.commit()
    return loan_file


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _url(ident: str) -> str:
    return f"/api/v1/loan-files/{ident}/findings"


async def test_lists_a_loan_files_findings(client: AsyncClient, db_session: AsyncSession) -> None:
    company, token = await _make_user(db_session, slug="acme")
    loan_file = await _make_doc_with_finding(db_session, company)

    resp = await client.get(_url(loan_file.display_id), headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    finding = body[0]
    assert finding["finding_type"] == "obligation"
    assert finding["frequency"] == "monthly"
    assert finding["details"]["payer"] == "John Doe"
    assert finding["status"] == "open"


async def test_empty_when_no_findings(client: AsyncClient, db_session: AsyncSession) -> None:
    company, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    await db_session.commit()

    resp = await client.get(_url(loan_file.display_id), headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json() == []


async def test_cross_company_findings_are_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A Company B user cannot read Company A's findings (the file is 404 for them)."""
    company_a, _token_a = await _make_user(db_session, slug="acme")
    _company_b, token_b = await _make_user(db_session, slug="globex")
    loan_file_a = await _make_doc_with_finding(db_session, company_a)

    resp = await client.get(_url(loan_file_a.display_id), headers=_auth(token_b))
    assert resp.status_code == 404  # A's file (and its findings) is invisible to B


async def test_requires_auth(client: AsyncClient, db_session: AsyncSession) -> None:
    company, _token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    await db_session.commit()

    resp = await client.get(_url(loan_file.display_id))  # no auth header
    assert resp.status_code == 401

"""Error envelope + global handler (LP-46).

Every API error returns one shape — ``{"error": {"type", "message", "details"?}}``
— with a SAFE message (no stack trace, internal path, DB text, or PII). Covers:
an unhandled exception → safe 500; a 404; a 422 with field details; a 401.
"""

from collections.abc import AsyncIterator

from app.api import documents as documents_api
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.main import app
from app.models import Company, User
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration import factories

V1 = "/api/v1"

# Strings that must NEVER appear in a client-facing error (leak/PII guards).
_FORBIDDEN_FRAGMENTS = (
    "Traceback",
    'File "',
    "/app/",
    "sqlalchemy",
    "asyncpg",
    "psycopg",
    "SELECT ",
    "boom-internal",  # the secret detail our forced exception carries
)


def _assert_safe_envelope(body: dict, *, expected_type: str) -> None:
    assert set(body.keys()) == {"error"}
    error = body["error"]
    assert error["type"] == expected_type
    assert isinstance(error["message"], str) and error["message"]
    blob = str(body)
    for fragment in _FORBIDDEN_FRAGMENTS:
        assert fragment not in blob, f"leaked {fragment!r} in error body"


async def test_unhandled_exception_returns_safe_500(
    db: AsyncSession, company_a: Company, user_a: User, monkeypatch
) -> None:
    """A handler that raises an unexpected error → generic 500 envelope, no leak.

    Uses a transport with ``raise_app_exceptions=False`` so we can inspect the
    500 the global handler *sent* (httpx otherwise re-raises the propagated
    exception, which is what a real ASGI server logs — the response is still 500).
    """
    lf = await factories.make_loan_file(db, company=company_a)

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom-internal: secret db path /var/secret leaked?")

    # Force an unexpected (non-HTTP) failure inside the documents list handler.
    monkeypatch.setattr(documents_api, "list_documents", _boom)

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as raw:
            raw.headers["Authorization"] = f"Bearer {create_access_token(user_a.id)}"
            resp = await raw.get(f"{V1}/loan-files/{lf.id}/documents")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 500
    body = resp.json()
    _assert_safe_envelope(body, expected_type="internal_error")
    # The generic message, never the RuntimeError text.
    assert body["error"]["message"] == "An unexpected error occurred. Please try again."


async def test_not_found_uses_envelope(
    auth_client: AsyncClient, db: AsyncSession, company_b: Company
) -> None:
    other = await factories.make_loan_file(db, company=company_b)
    resp = await auth_client.get(f"{V1}/loan-files/{other.id}")
    assert resp.status_code == 404
    _assert_safe_envelope(resp.json(), expected_type="not_found")


async def test_validation_error_has_field_details(
    auth_client: AsyncClient, db: AsyncSession, company_a: Company, user_a: User
) -> None:
    lf = await factories.make_loan_file(db, company=company_a)
    doc = await factories.make_document(db, loan_file=lf, company=company_a, uploaded_by=user_a)
    # Empty document_type violates the override schema (min_length=1) → 422.
    resp = await auth_client.patch(f"{V1}/documents/{doc.id}", json={"document_type": ""})
    assert resp.status_code == 422
    body = resp.json()
    _assert_safe_envelope(body, expected_type="validation_error")
    details = body["error"]["details"]
    assert isinstance(details, list) and details
    assert any(d["field"] == "document_type" for d in details)
    assert all("field" in d and "message" in d for d in details)


async def test_unauthorized_uses_envelope(client: AsyncClient, db: AsyncSession) -> None:
    # No token → 401 in the envelope (the dependency raises HTTPException).
    resp = await client.get(f"{V1}/loan-files")
    assert resp.status_code == 401
    _assert_safe_envelope(resp.json(), expected_type="unauthorized")


async def test_login_failure_is_safe_envelope(client: AsyncClient, db: AsyncSession) -> None:
    resp = await client.post(
        f"{V1}/auth/login",
        json={"email": "nobody@nowhere.com", "password": "x"},  # pragma: allowlist secret
    )
    assert resp.status_code == 401
    body = resp.json()
    _assert_safe_envelope(body, expected_type="unauthorized")
    # Generic credential message — never reveals whether the email exists.
    assert body["error"]["message"] == "Invalid email or password"

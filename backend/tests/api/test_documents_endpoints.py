"""Endpoint tests for document upload/list/get/download/delete (LP-36).

The two security cruxes: (1) **flat-route tenant isolation** — a Company A user
must not get/download/delete a Company B document by id, nor upload to/list a
Company B file (``404`` each); (2) **upload validation** — size and type
(content-type + magic bytes) are enforced. Also: byte round-trip through the
auth'd download endpoint, ``storage_path`` never exposed, and soft-delete
preserving the stored bytes.
"""

from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID

import pytest
import pytest_asyncio
from app.api import documents as documents_api
from app.core.config import settings
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.main import app
from app.models import Company, User, UserRole
from app.models.document import Document, DocumentStatus
from app.services.loan_files import create_loan_file
from app.storage import get_storage_backend
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

# Minimal valid magic-byte headers.
PDF_BYTES = b"%PDF-1.7\n%minimal pay stub\n"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 32


@pytest.fixture(autouse=True)
def _storage_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the storage backend at an isolated temp dir (never the real ./storage)."""
    monkeypatch.setattr(settings, "storage_local_path", str(tmp_path / "storage"))
    get_storage_backend.cache_clear()
    yield
    get_storage_backend.cache_clear()


@pytest.fixture(autouse=True)
def _mock_enqueue(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Stub the LP-42 processing enqueue so upload tests never hit the real broker."""
    delay = MagicMock()
    monkeypatch.setattr(documents_api.process_document, "delay", delay)
    return delay


@pytest.fixture(autouse=True)
def _mock_reprocess(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Stub the LP-39c re-extraction enqueue (fired by the LP-44 type override)."""
    delay = MagicMock()
    monkeypatch.setattr(documents_api.reprocess_document, "delay", delay)
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


def _docs_url(ident: str) -> str:
    return f"/api/v1/loan-files/{ident}/documents"


def _pdf_part(name: str = "paystub.pdf", content: bytes = PDF_BYTES, ct: str = "application/pdf"):
    return ("files", (name, content, ct))


# --------------------------------------------------------------------------- #
# Upload — happy paths
# --------------------------------------------------------------------------- #


async def test_upload_valid_pdf_creates_pending_document(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)

    resp = await client.post(
        _docs_url(loan_file.display_id), headers=_auth(token), files=[_pdf_part()]
    )
    assert resp.status_code == 201
    body = resp.json()
    assert len(body) == 1
    doc = body[0]
    assert doc["status"] == "pending"
    assert doc["upload_source"] == "user_upload"
    assert doc["original_filename"] == "paystub.pdf"
    assert doc["mime_type"] == "application/pdf"
    assert doc["file_size_bytes"] == len(PDF_BYTES)
    # storage_path is internal — never exposed.
    assert "storage_path" not in doc

    # Bytes were actually stored: read them straight from the backend.
    storage = get_storage_backend()
    storage_path = f"{company.id}/{loan_file.id}/{doc['id']}.pdf"
    assert await storage.read(storage_path) == PDF_BYTES


@pytest.mark.parametrize(
    ("name", "content", "ct"),
    [
        ("scan.png", PNG_BYTES, "image/png"),
        ("photo.jpg", JPEG_BYTES, "image/jpeg"),
    ],
)
async def test_upload_accepts_png_and_jpeg(
    client: AsyncClient, db_session: AsyncSession, name: str, content: bytes, ct: str
) -> None:
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    resp = await client.post(
        _docs_url(loan_file.display_id), headers=_auth(token), files=[_pdf_part(name, content, ct)]
    )
    assert resp.status_code == 201
    assert resp.json()[0]["mime_type"] == ct


async def test_upload_multiple_files_in_one_request(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    resp = await client.post(
        _docs_url(loan_file.display_id),
        headers=_auth(token),
        files=[
            _pdf_part("a.pdf"),
            _pdf_part("b.png", PNG_BYTES, "image/png"),
            _pdf_part("c.jpg", JPEG_BYTES, "image/jpeg"),
        ],
    )
    assert resp.status_code == 201
    assert len(resp.json()) == 3


async def test_upload_enqueues_processing_per_document(
    client: AsyncClient, db_session: AsyncSession, _mock_enqueue: object
) -> None:
    """The upload enqueues LP-42 processing once per uploaded document (after commit)."""
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    resp = await client.post(
        _docs_url(loan_file.display_id),
        headers=_auth(token),
        files=[_pdf_part("a.pdf"), _pdf_part("b.png", PNG_BYTES, "image/png")],
    )
    assert resp.status_code == 201
    created_ids = {d["id"] for d in resp.json()}
    # delay() called once per document, with each document's id.
    assert _mock_enqueue.call_count == 2  # type: ignore[attr-defined]
    enqueued_ids = {call.args[0] for call in _mock_enqueue.call_args_list}  # type: ignore[attr-defined]
    assert enqueued_ids == created_ids


# --------------------------------------------------------------------------- #
# Upload — validation rejections
# --------------------------------------------------------------------------- #


async def test_upload_rejects_disallowed_type(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    resp = await client.post(
        _docs_url(loan_file.display_id),
        headers=_auth(token),
        files=[_pdf_part("notes.txt", b"just some text", "text/plain")],
    )
    assert resp.status_code == 415


async def test_upload_rejects_content_type_spoofing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    # Declares PDF but the bytes are PNG.
    resp = await client.post(
        _docs_url(loan_file.display_id),
        headers=_auth(token),
        files=[_pdf_part("fake.pdf", PNG_BYTES, "application/pdf")],
    )
    assert resp.status_code == 415


async def test_upload_rejects_oversize(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Lower the cap so the test stays small; patch both module globals.
    monkeypatch.setattr("app.api.documents.MAX_FILE_SIZE_BYTES", 1024)
    monkeypatch.setattr("app.services.documents.MAX_FILE_SIZE_BYTES", 1024)
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    big = b"%PDF" + b"\x00" * 4096
    resp = await client.post(
        _docs_url(loan_file.display_id),
        headers=_auth(token),
        files=[_pdf_part("big.pdf", big, "application/pdf")],
    )
    assert resp.status_code == 413


async def test_upload_invalid_file_rejects_whole_batch(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """One bad file in a batch rejects the request — nothing is persisted."""
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    resp = await client.post(
        _docs_url(loan_file.display_id),
        headers=_auth(token),
        files=[_pdf_part("good.pdf"), _pdf_part("bad.txt", b"text", "text/plain")],
    )
    assert resp.status_code == 415
    # The good file must not have been stored.
    listed = await client.get(_docs_url(loan_file.display_id), headers=_auth(token))
    assert listed.json() == []


# --------------------------------------------------------------------------- #
# List / get / download / delete
# --------------------------------------------------------------------------- #


async def _upload_one(client: AsyncClient, ident: str, token: str) -> dict:
    resp = await client.post(_docs_url(ident), headers=_auth(token), files=[_pdf_part()])
    assert resp.status_code == 201
    return resp.json()[0]


async def test_list_documents(client: AsyncClient, db_session: AsyncSession) -> None:
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    await _upload_one(client, loan_file.display_id, token)
    listed = await client.get(_docs_url(loan_file.display_id), headers=_auth(token))
    assert listed.status_code == 200
    assert len(listed.json()) == 1


async def test_get_document_detail_has_null_extraction(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_one(client, loan_file.display_id, token)
    resp = await client.get(f"/api/v1/documents/{doc['id']}", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == doc["id"]
    assert body["current_extraction"] is None
    assert "storage_path" not in body


async def test_download_returns_exact_bytes(client: AsyncClient, db_session: AsyncSession) -> None:
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_one(client, loan_file.display_id, token)
    resp = await client.get(f"/api/v1/documents/{doc['id']}/download", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.content == PDF_BYTES
    assert resp.headers["content-type"].startswith("application/pdf")
    assert "attachment" in resp.headers["content-disposition"]
    assert "paystub.pdf" in resp.headers["content-disposition"]


async def test_delete_soft_deletes_and_preserves_bytes(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_one(client, loan_file.display_id, token)
    storage_path = f"{company.id}/{loan_file.id}/{doc['id']}.pdf"

    resp = await client.delete(f"/api/v1/documents/{doc['id']}", headers=_auth(token))
    assert resp.status_code == 204
    # Subsequently 404 on GET.
    assert (
        await client.get(f"/api/v1/documents/{doc['id']}", headers=_auth(token))
    ).status_code == 404
    # But the stored bytes are preserved (audit).
    assert await get_storage_backend().read(storage_path) == PDF_BYTES


# --------------------------------------------------------------------------- #
# Manual type override (LP-44)
# --------------------------------------------------------------------------- #


def _override_url(doc_id: str) -> str:
    return f"/api/v1/documents/{doc_id}"


async def test_override_sets_type_category_and_marks_human_overridden(
    client: AsyncClient, db_session: AsyncSession, _mock_reprocess: MagicMock
) -> None:
    """PATCH sets the type, re-derives category, marks human-overridden, clears error."""
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_one(client, loan_file.display_id, token)

    resp = await client.patch(
        _override_url(doc["id"]), headers=_auth(token), json={"document_type": "bank_statement"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["document_type"] == "bank_statement"
    # Re-derived from the type→category map (assets for a bank statement).
    assert body["category"] == "assets"
    # Human-set type is authoritative — confidence pinned to 1.0.
    assert body["classification_confidence"] == 1.0
    # The existing LP-39c re-extraction was enqueued exactly once with this doc id.
    _mock_reprocess.assert_called_once_with(doc["id"])


async def test_override_enqueues_reprocess(
    client: AsyncClient, db_session: AsyncSession, _mock_reprocess: MagicMock
) -> None:
    """The override fires the LP-39c re-extraction task (fire-and-forget)."""
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_one(client, loan_file.display_id, token)

    resp = await client.patch(
        _override_url(doc["id"]), headers=_auth(token), json={"document_type": "w2"}
    )
    assert resp.status_code == 200
    _mock_reprocess.assert_called_once_with(doc["id"])


async def test_override_rejects_empty_type(
    client: AsyncClient, db_session: AsyncSession, _mock_reprocess: MagicMock
) -> None:
    """An empty/whitespace document_type is a 422 (min_length=1) and enqueues nothing."""
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_one(client, loan_file.display_id, token)

    resp = await client.patch(
        _override_url(doc["id"]), headers=_auth(token), json={"document_type": ""}
    )
    assert resp.status_code == 422
    _mock_reprocess.assert_not_called()


async def test_override_unauthenticated_is_401(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_one(client, loan_file.display_id, token)
    resp = await client.patch(_override_url(doc["id"]), json={"document_type": "w2"})
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# CRITICAL: cross-tenant isolation
# --------------------------------------------------------------------------- #


async def test_company_b_cannot_touch_company_a_document(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company_a, _ua, a_token = await _make_user(db_session, slug="company-a")
    _company_b, _ub, b_token = await _make_user(db_session, slug="company-b")
    a_file = await create_loan_file(db_session, company_id=company_a.id)
    doc = await _upload_one(client, a_file.display_id, a_token)
    doc_id = doc["id"]

    # B cannot get / download / delete / override A's document by id → 404 each.
    assert (
        await client.get(f"/api/v1/documents/{doc_id}", headers=_auth(b_token))
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/documents/{doc_id}/download", headers=_auth(b_token))
    ).status_code == 404
    assert (
        await client.patch(
            f"/api/v1/documents/{doc_id}", headers=_auth(b_token), json={"document_type": "w2"}
        )
    ).status_code == 404
    assert (
        await client.delete(f"/api/v1/documents/{doc_id}", headers=_auth(b_token))
    ).status_code == 404

    # And the document is untouched: A still soft-deletes nothing; it's readable.
    assert (
        await client.get(f"/api/v1/documents/{doc_id}", headers=_auth(a_token))
    ).status_code == 200


async def test_company_b_cannot_upload_to_or_list_company_a_file(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company_a, _ua, _a_token = await _make_user(db_session, slug="company-a")
    _company_b, _ub, b_token = await _make_user(db_session, slug="company-b")
    a_file = await create_loan_file(db_session, company_id=company_a.id)

    assert (
        await client.post(_docs_url(a_file.display_id), headers=_auth(b_token), files=[_pdf_part()])
    ).status_code == 404
    assert (
        await client.get(_docs_url(a_file.display_id), headers=_auth(b_token))
    ).status_code == 404


async def test_list_does_not_leak_other_company_documents(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company_a, _ua, a_token = await _make_user(db_session, slug="company-a")
    _company_b, _ub, b_token = await _make_user(db_session, slug="company-b")
    a_file = await create_loan_file(db_session, company_id=company_a.id)
    b_file = await create_loan_file(db_session, company_id=_company_b.id)
    await _upload_one(client, a_file.display_id, a_token)

    # B's own file lists none of A's documents.
    listed = await client.get(_docs_url(b_file.display_id), headers=_auth(b_token))
    assert listed.json() == []


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #


async def test_unauthenticated_is_401(client: AsyncClient, db_session: AsyncSession) -> None:
    company, _user, _token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    assert (await client.get(_docs_url(loan_file.display_id))).status_code == 401
    assert (
        await client.post(_docs_url(loan_file.display_id), files=[_pdf_part()])
    ).status_code == 401


# --------------------------------------------------------------------------- #
# LP-637 — reprocess a stored document from scratch, classification included
# --------------------------------------------------------------------------- #
@pytest.fixture
def _mock_full_reprocess(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Stub the FULL pipeline enqueue (classify + extract), distinct from the LP-39c one."""
    from app.tasks import document_processing

    delay = MagicMock()
    monkeypatch.setattr(document_processing.process_document, "delay", delay)
    return delay


def _reprocess_url(doc_id: str) -> str:
    return f"/api/v1/documents/{doc_id}/reprocess"


async def test_reprocess_enqueues_the_full_pipeline_not_the_re_extraction(
    client: AsyncClient,
    db_session: AsyncSession,
    _mock_reprocess: MagicMock,
    _mock_full_reprocess: MagicMock,
) -> None:
    """THE WHOLE POINT, and the one assertion that distinguishes this from what already existed.

    `reprocess_document` (the type-override path) SKIPS classification by design. A document that
    classified as `unknown` cannot be helped by it — nobody knows what type to supply. This must
    enqueue `process_document`, which classifies again.

    Both mocks are held so the test fails loudly if the wrong one fires, rather than passing because
    something was enqueued.
    """
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_one(client, loan_file.display_id, token)
    # Uploading enqueues the SAME task, so the mock must be cleared to isolate what reprocess does.
    _mock_full_reprocess.reset_mock()

    resp = await client.post(_reprocess_url(doc["id"]), headers=_auth(token), json={})

    assert resp.status_code == 200
    _mock_full_reprocess.assert_called_once_with(doc["id"])
    _mock_reprocess.assert_not_called()


async def test_reprocess_refuses_a_human_classified_document(
    client: AsyncClient,
    db_session: AsyncSession,
    _mock_reprocess: MagicMock,
    _mock_full_reprocess: MagicMock,
) -> None:
    """A person chose that type. Replacing it with the classifier's guess and saying nothing is a
    worse bug than the one being fixed, so the default is refuse."""
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_one(client, loan_file.display_id, token)
    # The override endpoint is what marks a type human-set.
    await client.patch(
        _override_url(doc["id"]), headers=_auth(token), json={"document_type": "bank_statement"}
    )
    _mock_full_reprocess.reset_mock()

    resp = await client.post(_reprocess_url(doc["id"]), headers=_auth(token), json={})

    assert resp.status_code == 409
    _mock_full_reprocess.assert_not_called()


async def test_force_reprocesses_a_human_classified_document(
    client: AsyncClient,
    db_session: AsyncSession,
    _mock_reprocess: MagicMock,
    _mock_full_reprocess: MagicMock,
) -> None:
    """The refusal is a guard, not a wall — a processor who means it can say so."""
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_one(client, loan_file.display_id, token)
    await client.patch(
        _override_url(doc["id"]), headers=_auth(token), json={"document_type": "bank_statement"}
    )
    _mock_full_reprocess.reset_mock()

    resp = await client.post(_reprocess_url(doc["id"]), headers=_auth(token), json={"force": True})

    assert resp.status_code == 200
    _mock_full_reprocess.assert_called_once_with(doc["id"])


async def test_reprocess_marks_the_verification_stale(
    client: AsyncClient,
    db_session: AsyncSession,
    _mock_reprocess: MagicMock,
    _mock_full_reprocess: MagicMock,
) -> None:
    """A re-classified document under findings computed from its OLD type is a false green. The
    override endpoint marks the run stale for this reason; so must this."""
    from unittest.mock import AsyncMock, patch

    from app.api import documents as documents_api

    marked = AsyncMock()
    with patch.object(documents_api, "mark_verification_stale", marked):
        company, _user, token = await _make_user(db_session, slug="acme")
        loan_file = await create_loan_file(db_session, company_id=company.id)
        doc = await _upload_one(client, loan_file.display_id, token)

        resp = await client.post(_reprocess_url(doc["id"]), headers=_auth(token), json={})

    assert resp.status_code == 200
    marked.assert_awaited_once()


async def test_reprocess_is_tenant_scoped(
    client: AsyncClient,
    db_session: AsyncSession,
    _mock_reprocess: MagicMock,
    _mock_full_reprocess: MagicMock,
) -> None:
    """Another company's document is a 404, not a 403 — the same shape every other document route
    uses, so this one cannot become the endpoint that confirms a document exists."""
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_one(client, loan_file.display_id, token)
    _other, _u2, other_token = await _make_user(db_session, slug="rival")
    _mock_full_reprocess.reset_mock()  # the upload above enqueued it once

    resp = await client.post(_reprocess_url(doc["id"]), headers=_auth(other_token), json={})

    assert resp.status_code == 404
    _mock_full_reprocess.assert_not_called()


async def test_reprocess_refuses_a_superseded_version(
    client: AsyncClient,
    db_session: AsyncSession,
    _mock_reprocess: MagicMock,
    _mock_full_reprocess: MagicMock,
) -> None:
    """A superseded version is kept for AUDIT and cannot affect an answer.

    `documents_section` selects `Document.is_current.is_(True)`, so no finding on the file reads a
    replaced version. Reprocessing one would re-classify a historical record, spend a full
    classify+extract on work that provably changes nothing, and — the part that reaches a person —
    mark the whole file's verification stale, showing "needs re-verification" for a document that is
    not part of the file's current state. The replace endpoint refuses the same thing already.
    """
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_one(client, loan_file.display_id, token)

    old = await db_session.get(Document, UUID(doc["id"]))
    assert old is not None
    old.is_current = False
    await db_session.commit()
    _mock_full_reprocess.reset_mock()

    resp = await client.post(_reprocess_url(doc["id"]), headers=_auth(token), json={})

    assert resp.status_code == 409
    assert "current version" in resp.json()["error"]["message"]
    _mock_full_reprocess.assert_not_called()


async def test_force_does_not_reach_a_superseded_version(
    client: AsyncClient,
    db_session: AsyncSession,
    _mock_reprocess: MagicMock,
    _mock_full_reprocess: MagicMock,
) -> None:
    """`force` exists to override a HUMAN's type decision, which is a judgement a processor is
    entitled to reverse. It is not a way to reach a version the file no longer uses — those are two
    unrelated refusals, and sharing one flag between them would make the escape hatch wider than
    the thing it was opened for."""
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_one(client, loan_file.display_id, token)

    old = await db_session.get(Document, UUID(doc["id"]))
    assert old is not None
    old.is_current = False
    await db_session.commit()
    _mock_full_reprocess.reset_mock()

    resp = await client.post(_reprocess_url(doc["id"]), headers=_auth(token), json={"force": True})

    assert resp.status_code == 409
    _mock_full_reprocess.assert_not_called()


async def test_reprocess_refuses_a_document_the_pipeline_is_already_running(
    client: AsyncClient,
    db_session: AsyncSession,
    _mock_reprocess: MagicMock,
    _mock_full_reprocess: MagicMock,
) -> None:
    """Two overlapping `_process_document` runs both write a current extraction, and
    `UNIQUE (document_id) WHERE is_current` admits one — the loser absorbs the IntegrityError into
    FAILED, so the document reads FAILED while carrying the winner's good extraction.

    Before this endpoint existed `process_document` was enqueued exactly once, at upload, so the
    race was not reachable. Feature 3 puts a button on it.

    This guard covers a reprocess landing on a VISIBLY RUNNING pipeline, which is the longer
    window. It does not stop a double-click — see
    `test_two_clicks_before_a_worker_starts_both_enqueue`, which pins that gap.
    """
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_one(client, loan_file.display_id, token)

    running = await db_session.get(Document, UUID(doc["id"]))
    assert running is not None
    running.status = DocumentStatus.EXTRACTING
    await db_session.commit()
    _mock_full_reprocess.reset_mock()

    resp = await client.post(_reprocess_url(doc["id"]), headers=_auth(token), json={})

    assert resp.status_code == 409
    assert "already being processed" in resp.json()["error"]["message"]
    _mock_full_reprocess.assert_not_called()


async def test_a_document_stranded_at_pending_can_still_be_reprocessed(
    client: AsyncClient,
    db_session: AsyncSession,
    _mock_reprocess: MagicMock,
    _mock_full_reprocess: MagicMock,
) -> None:
    """PENDING is deliberately not treated as in-flight, and this is why.

    Both enqueues in this file are fire-and-forget and never raise, so a broker failure leaves a
    document at PENDING with no task behind it — a state upload has been able to produce since
    LP-42. Reprocess is the only route out. Guarding PENDING as "already running" would make the
    stranded document permanently unreachable, which is a worse bug than the double-click it would
    have prevented.
    """
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_one(client, loan_file.display_id, token)

    stranded = await db_session.get(Document, UUID(doc["id"]))
    assert stranded is not None
    stranded.status = DocumentStatus.PENDING
    await db_session.commit()
    _mock_full_reprocess.reset_mock()

    resp = await client.post(_reprocess_url(doc["id"]), headers=_auth(token), json={})

    assert resp.status_code == 200
    _mock_full_reprocess.assert_called_once_with(doc["id"])


async def test_reprocess_returns_the_status_it_actually_leaves_the_document_in(
    client: AsyncClient,
    db_session: AsyncSession,
    _mock_reprocess: MagicMock,
    _mock_full_reprocess: MagicMock,
) -> None:
    """The response is the only thing the processor sees at the moment they click.

    Returning the document's OLD status meant reprocessing a COMPLETED document answered
    `completed` — nothing appeared to happen until a worker picked the task up, which is precisely
    what invites the second click the in-flight guard now refuses.
    """
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_one(client, loan_file.display_id, token)

    done = await db_session.get(Document, UUID(doc["id"]))
    assert done is not None
    done.status = DocumentStatus.COMPLETED
    await db_session.commit()
    _mock_full_reprocess.reset_mock()

    resp = await client.post(_reprocess_url(doc["id"]), headers=_auth(token), json={})

    assert resp.status_code == 200
    assert resp.json()["status"] == DocumentStatus.PENDING.value

    await db_session.refresh(done)
    assert done.status is DocumentStatus.PENDING, "the response and the row must not disagree"


async def test_reprocess_clears_the_previous_runs_error(
    client: AsyncClient,
    db_session: AsyncSession,
    _mock_reprocess: MagicMock,
    _mock_full_reprocess: MagicMock,
) -> None:
    """`_process_document` only ever WRITES `processing_error`; no path through it clears one.

    So a document that failed, was reprocessed and then succeeded reached COMPLETED still carrying
    the error string from the run that no longer exists. That is the common case for this endpoint
    rather than an edge — the documents it was built for are the ten sitting in NEEDS_REVIEW with
    an error on them. The override endpoint clears the column for the same reason.
    """
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_one(client, loan_file.display_id, token)

    stale = await db_session.get(Document, UUID(doc["id"]))
    assert stale is not None
    stale.status = DocumentStatus.NEEDS_REVIEW
    stale.processing_error = "extraction incomplete (connection) — re-runnable"
    await db_session.commit()
    _mock_full_reprocess.reset_mock()

    resp = await client.post(_reprocess_url(doc["id"]), headers=_auth(token), json={})

    assert resp.status_code == 200
    await db_session.refresh(stale)
    assert stale.processing_error is None, "the previous run's error outlived the run"


async def test_reprocess_refuses_a_tier_3_document_mid_analysis(
    client: AsyncClient,
    db_session: AsyncSession,
    _mock_reprocess: MagicMock,
    _mock_full_reprocess: MagicMock,
) -> None:
    """CLASSIFIED is the status a Tier 3 document holds for its whole free-extraction call.

    `_process_document` commits CLASSIFIED and only then runs `analyze_document`; EXTRACTING is set
    inside `_extract_branch`, i.e. Tier 1 only. So an in-flight guard listing CLASSIFYING and
    EXTRACTING alone leaves the LONGEST window open, on exactly the `unknown` / low-confidence
    cohort this feature was built for.
    """
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_one(client, loan_file.display_id, token)

    mid = await db_session.get(Document, UUID(doc["id"]))
    assert mid is not None
    mid.status = DocumentStatus.CLASSIFIED
    await db_session.commit()
    _mock_full_reprocess.reset_mock()

    resp = await client.post(_reprocess_url(doc["id"]), headers=_auth(token), json={})

    assert resp.status_code == 409
    _mock_full_reprocess.assert_not_called()


async def test_reprocess_accepts_a_request_with_no_body(
    client: AsyncClient,
    db_session: AsyncSession,
    _mock_reprocess: MagicMock,
    _mock_full_reprocess: MagicMock,
) -> None:
    """FastAPI makes a Pydantic body parameter REQUIRED even when every field on it has a default,
    so the natural call — the feature-3 button, posting nothing — was a 422. Every other test in
    this group passes `json={}` and would never have noticed."""
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_one(client, loan_file.display_id, token)
    _mock_full_reprocess.reset_mock()

    resp = await client.post(_reprocess_url(doc["id"]), headers=_auth(token))

    assert resp.status_code == 200
    _mock_full_reprocess.assert_called_once_with(doc["id"])


async def test_two_clicks_before_a_worker_starts_both_enqueue(
    client: AsyncClient,
    db_session: AsyncSession,
    _mock_reprocess: MagicMock,
    _mock_full_reprocess: MagicMock,
) -> None:
    """PINS THE GAP RATHER THAN CLAIMING IT IS CLOSED. No status guard can stop a double-click:
    the status only moves when a WORKER starts, so both clicks read the row as it was before
    either was picked up.

    An earlier draft of the in-flight guard's comment said it refused "the second click". It does
    not, and a comment saying otherwise is worse than no comment — closing this needs task-level
    deduplication or a lock, and the feature-3 action should disable on submit. This test exists so
    that stays visible instead of being assumed.
    """
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_one(client, loan_file.display_id, token)
    _mock_full_reprocess.reset_mock()

    first = await client.post(_reprocess_url(doc["id"]), headers=_auth(token), json={})
    second = await client.post(_reprocess_url(doc["id"]), headers=_auth(token), json={})

    assert first.status_code == 200
    assert second.status_code == 200, (
        "if this is now a 409 the gap has been closed — good; update the guard's comment, the "
        "ticket and this test rather than leaving three places claiming the opposite"
    )
    assert _mock_full_reprocess.call_count == 2


# --------------------------------------------------------------------------- #
# LP-637 feature 2 — bulk reprocess
# --------------------------------------------------------------------------- #
def _bulk_url(ident: str) -> str:
    return f"/api/v1/loan-files/{ident}/documents/reprocess"


async def _set(db_session: AsyncSession, doc_id: str, **fields) -> None:
    from uuid import UUID as _UUID

    from app.models.document import Document as _Doc

    document = await db_session.get(_Doc, _UUID(doc_id))
    assert document is not None
    for key, value in fields.items():
        setattr(document, key, value)
    await db_session.commit()


async def test_bulk_skips_rather_than_failing_the_batch(
    client: AsyncClient,
    db_session: AsyncSession,
    _mock_reprocess: MagicMock,
    _mock_full_reprocess: MagicMock,
) -> None:
    """THE DESIGN DIFFERENCE FROM THE PER-DOCUMENT ENDPOINT, and the reason it is a separate route.

    A single reprocess is a processor pointing at one document, so a 409 is the right answer. A bulk
    reprocess is a processor pointing at a FILE: failing all of it because one document is
    mid-pipeline would make the button useless exactly when a file is busy — which is when it is
    most likely to be pressed.
    """
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    wanted = await _upload_one(client, loan_file.display_id, token)
    busy = await _upload_one(client, loan_file.display_id, token)
    await _set(db_session, wanted["id"], document_type=None, status=DocumentStatus.NEEDS_REVIEW)
    await _set(db_session, busy["id"], document_type=None, status=DocumentStatus.CLASSIFIED)
    _mock_full_reprocess.reset_mock()

    resp = await client.post(_bulk_url(loan_file.display_id), headers=_auth(token), json={})

    assert resp.status_code == 200
    body = resp.json()
    assert body["queued"] == 1
    assert body["queued_document_ids"] == [wanted["id"]]
    assert body["skipped"] == {"already_processing": 1}
    _mock_full_reprocess.assert_called_once_with(wanted["id"])


async def test_bulk_default_leaves_healthy_documents_alone(
    client: AsyncClient,
    db_session: AsyncSession,
    _mock_reprocess: MagicMock,
    _mock_full_reprocess: MagicMock,
) -> None:
    """A 44-document file is 44 classifications and 44 re-extractions. Spending that to re-derive
    answers already correct is how a useful tool becomes one nobody is allowed to press."""
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    healthy = await _upload_one(client, loan_file.display_id, token)
    await _set(db_session, healthy["id"], document_type="w2", status=DocumentStatus.COMPLETED)
    _mock_full_reprocess.reset_mock()

    resp = await client.post(_bulk_url(loan_file.display_id), headers=_auth(token), json={})

    assert resp.json()["queued"] == 0
    assert resp.json()["skipped"] == {"already_classified": 1}
    _mock_full_reprocess.assert_not_called()


async def test_bulk_all_documents_widens_the_set(
    client: AsyncClient,
    db_session: AsyncSession,
    _mock_reprocess: MagicMock,
    _mock_full_reprocess: MagicMock,
) -> None:
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    healthy = await _upload_one(client, loan_file.display_id, token)
    await _set(db_session, healthy["id"], document_type="w2", status=DocumentStatus.COMPLETED)
    _mock_full_reprocess.reset_mock()

    resp = await client.post(
        _bulk_url(loan_file.display_id), headers=_auth(token), json={"all_documents": True}
    )

    assert resp.json()["queued"] == 1
    _mock_full_reprocess.assert_called_once_with(healthy["id"])


async def test_bulk_picks_up_the_unknown_cohort_this_exists_for(
    client: AsyncClient,
    db_session: AsyncSession,
    _mock_reprocess: MagicMock,
    _mock_full_reprocess: MagicMock,
) -> None:
    """LF-ZE9N's four `unknown` documents are COMPLETED with no flag — LP-636 defect 5. If the
    default set were "not completed" they would be the ones it missed, which would leave the
    feature unable to reach half the cohort that motivated it."""
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    unknown_doc = await _upload_one(client, loan_file.display_id, token)
    await _set(
        db_session, unknown_doc["id"], document_type="unknown", status=DocumentStatus.COMPLETED
    )
    _mock_full_reprocess.reset_mock()

    resp = await client.post(_bulk_url(loan_file.display_id), headers=_auth(token), json={})

    assert resp.json()["queued"] == 1
    _mock_full_reprocess.assert_called_once_with(unknown_doc["id"])


async def test_bulk_leaves_a_human_set_type_alone_unless_forced(
    client: AsyncClient,
    db_session: AsyncSession,
    _mock_reprocess: MagicMock,
    _mock_full_reprocess: MagicMock,
) -> None:
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_one(client, loan_file.display_id, token)
    await client.patch(
        _override_url(doc["id"]), headers=_auth(token), json={"document_type": "bank_statement"}
    )
    await _set(db_session, doc["id"], status=DocumentStatus.NEEDS_REVIEW)
    _mock_full_reprocess.reset_mock()

    skipped = await client.post(_bulk_url(loan_file.display_id), headers=_auth(token), json={})
    assert skipped.json()["skipped"] == {"type_set_by_a_person": 1}
    _mock_full_reprocess.assert_not_called()

    forced = await client.post(
        _bulk_url(loan_file.display_id), headers=_auth(token), json={"force": True}
    )
    assert forced.json()["queued"] == 1


async def test_bulk_accepts_no_body(
    client: AsyncClient,
    db_session: AsyncSession,
    _mock_reprocess: MagicMock,
    _mock_full_reprocess: MagicMock,
) -> None:
    """A body-less POST must not be a 422 — the feature-3 button sends none, and every test above
    passing `json={}` would never have noticed. The same defect was found on the per-document
    endpoint in review."""
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)

    resp = await client.post(_bulk_url(loan_file.display_id), headers=_auth(token))

    assert resp.status_code == 200


async def test_bulk_is_tenant_scoped(
    client: AsyncClient,
    db_session: AsyncSession,
    _mock_reprocess: MagicMock,
    _mock_full_reprocess: MagicMock,
) -> None:
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    await _upload_one(client, loan_file.display_id, token)
    _other, _u2, other_token = await _make_user(db_session, slug="rival")
    _mock_full_reprocess.reset_mock()

    resp = await client.post(_bulk_url(loan_file.display_id), headers=_auth(other_token), json={})

    assert resp.status_code == 404
    _mock_full_reprocess.assert_not_called()

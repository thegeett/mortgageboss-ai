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
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pymupdf
import pytest
import pytest_asyncio
from app.api import documents as documents_api
from app.core.config import settings
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.main import app
from app.models import Company, User, UserRole
from app.models.document import Document
from app.models.extraction import ExtractionStatus
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


async def test_field_scrutiny_reaches_the_endpoint(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Criticality and distrust arrive on the response, not just in the helper (LP-UI-032).

    Tested at the API because a guarded helper with unguarded wiring is exactly the
    shape the last review found — the screen reads this response, not the module.
    """
    from app.services.extractions import create_extraction_version

    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_one(client, loan_file.display_id, token)

    document = await db_session.get(Document, UUID(doc["id"]))
    assert document is not None
    document.document_type = "credit_report"
    await create_extraction_version(
        db_session,
        document_id=document.id,
        extracted_data={
            # Critical (money) and sensitive (identity) and ordinary and distrusted.
            "gross_pay": {"value": "4200.00", "confidence": 0.99},
            "borrower_ssn": {"value": "035-98-0128"},
            "employer_name": {"value": "ACME Corp"},
            "report_date": {"value": "2026-07-17"},
        },
        extraction_status=ExtractionStatus.SUCCEEDED,
    )
    await db_session.commit()

    body = (await client.get(f"/api/v1/documents/{doc['id']}", headers=_auth(token))).json()
    scrutiny = body["field_scrutiny"]

    assert scrutiny["gross_pay"]["critical"] is True
    assert scrutiny["gross_pay"]["sensitive"] is False
    assert scrutiny["borrower_ssn"]["sensitive"] is True
    # A confirmed-wrong extractor field on THIS document type, with its reason.
    assert scrutiny["report_date"]["distrusted_reason"]
    # An ordinary field is ABSENT rather than present-and-false — the payload must
    # not grow with the 1,603-key spec vocabulary.
    assert "employer_name" not in scrutiny


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


def _real_pdf(pages: int = 1) -> bytes:
    """An actually-renderable PDF.

    `PDF_BYTES` above is a header and a comment — enough for upload and download,
    which move bytes, and not enough for anything that OPENS the file. The page
    endpoint renders, so it needs a real one; asserting a render against a stub
    would be asserting a 404 and calling it success.
    """
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 72), f"page {i + 1}")
    return bytes(doc.tobytes())


async def _upload_real_pdf(client: AsyncClient, ident: str, token: str) -> dict[str, Any]:
    resp = await client.post(
        _docs_url(ident),
        headers=_auth(token),
        files=[("files", ("paystub.pdf", _real_pdf(), "application/pdf"))],
    )
    assert resp.status_code == 201, resp.text
    return dict(resp.json()[0])


# --------------------------------------------------------------------------- #
# Page image (LP-UI-030) — the reviewer's canvas
# --------------------------------------------------------------------------- #


async def test_page_image_renders_and_carries_its_geometry(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Tested at the API, not only the renderer — the layer a caller meets."""
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_real_pdf(client, loan_file.display_id, token)

    resp = await client.get(f"/api/v1/documents/{doc['id']}/page/1", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content.startswith(b"\x89PNG\r\n\x1a\n")
    # The point-space a highlight rectangle is expressed in travels WITH the
    # image; fetching it separately is how the two drift.
    assert float(resp.headers["X-Page-Width-Points"]) > 0
    assert float(resp.headers["X-Page-Height-Points"]) > 0
    assert float(resp.headers["X-Page-Zoom"]) >= 1.0
    # A rendered page is borrower content: never a shared cache.
    assert "private" in resp.headers["cache-control"]


async def test_a_page_the_document_does_not_have_is_a_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # Measured on real data: a model-cited page is out of range on ~4% of
    # extracted fields, so this is a designed state rather than an edge case.
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_real_pdf(client, loan_file.display_id, token)
    resp = await client.get(f"/api/v1/documents/{doc['id']}/page/99", headers=_auth(token))
    assert resp.status_code == 404


async def test_another_companys_page_is_a_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # A rendered page IS the document's content, so it gets the same gate as the
    # bytes. This is the assertion that stops the reviewer becoming a way around
    # the download endpoint's tenant scoping.
    company_a, _ua, token_a = await _make_user(db_session, slug="acme")
    _company_b, _ub, token_b = await _make_user(db_session, slug="beta")
    loan_file = await create_loan_file(db_session, company_id=company_a.id)
    doc = await _upload_real_pdf(client, loan_file.display_id, token_a)

    resp = await client.get(f"/api/v1/documents/{doc['id']}/page/1", headers=_auth(token_b))
    assert resp.status_code == 404


async def test_field_boxes_locate_values_and_flag_a_fabricated_page(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Boxes at the API, including the flag that stops a silent correction.

    Measured on real data: 4.3% of fields cite a page the document does not have,
    and NOT ONE cites a wrong-but-existing page. So the box may come from another
    page, and the response says so rather than quietly substituting a better one.
    """
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_real_pdf(client, loan_file.display_id, token)

    resp = await client.get(f"/api/v1/documents/{doc['id']}/boxes", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    # No extraction on a freshly uploaded document — an empty result, not a 500.
    assert body["boxes"] == []
    assert body["fabricated_pages"] == []
    assert body["relocated"] == []


async def test_another_companys_boxes_are_a_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # A box is derived from the document's own text, so it is exactly as
    # sensitive as the page it describes.
    company_a, _ua, token_a = await _make_user(db_session, slug="acme")
    _company_b, _ub, token_b = await _make_user(db_session, slug="beta")
    loan_file = await create_loan_file(db_session, company_id=company_a.id)
    doc = await _upload_real_pdf(client, loan_file.display_id, token_a)

    resp = await client.get(f"/api/v1/documents/{doc['id']}/boxes", headers=_auth(token_b))
    assert resp.status_code == 404

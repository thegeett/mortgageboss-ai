"""Endpoint tests for document upload/list/get/download/delete (LP-36).

The two security cruxes: (1) **flat-route tenant isolation** — a Company A user
must not get/download/delete a Company B document by id, nor upload to/list a
Company B file (``404`` each); (2) **upload validation** — size and type
(content-type + magic bytes) are enforced. Also: byte round-trip through the
auth'd download endpoint, ``storage_path`` never exposed, and soft-delete
preserving the stored bytes.
"""

from collections.abc import AsyncIterator
from datetime import timedelta
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
from app.models.activity_log import ActivityType
from app.models.base import utcnow
from app.models.document import (
    PIPELINE_PRESUMED_ABANDONED_AFTER_SECONDS,
    Document,
    DocumentStatus,
)
from app.models.extraction import ExtractionStatus
from app.services.loan_files import create_loan_file
from app.services.page_render import DEFAULT_ZOOM, MAX_RENDERED_EDGE
from app.storage import get_storage_backend
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
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


async def _reviewable(client: AsyncClient, db_session: AsyncSession, slug: str = "acme"):
    from app.services.extractions import create_extraction_version

    company, _user, token = await _make_user(db_session, slug=slug)
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_one(client, loan_file.display_id, token)
    document = await db_session.get(Document, UUID(doc["id"]))
    assert document is not None
    await create_extraction_version(
        db_session,
        document_id=document.id,
        extracted_data={"gross_pay": {"value": "4200.00"}, "net_pay": {"value": "3100.00"}},
        extraction_status=ExtractionStatus.SUCCEEDED,
    )
    await db_session.commit()
    return doc, token


async def test_a_field_can_be_accepted_and_withdrawn(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    doc, token = await _reviewable(client, db_session)
    url = f"/api/v1/documents/{doc['id']}/reviews"

    put = await client.put(
        url, json={"field_key": "gross_pay", "verdict": "accepted"}, headers=_auth(token)
    )
    assert put.status_code == 200, put.text
    assert put.json()["verdict"] == "accepted"

    listed = (await client.get(url, headers=_auth(token))).json()
    assert [r["field_key"] for r in listed] == ["gross_pay"]

    # The verdict also reaches the screen's own call, beside the scrutiny.
    detail = (await client.get(f"/api/v1/documents/{doc['id']}", headers=_auth(token))).json()
    assert detail["field_scrutiny"]["gross_pay"]["verdict"] == "accepted"

    gone = await client.delete(f"{url}/gross_pay", headers=_auth(token))
    assert gone.status_code == 204
    assert (await client.get(url, headers=_auth(token))).json() == []
    # Idempotent: withdrawing nothing is not an error.
    assert (await client.delete(f"{url}/gross_pay", headers=_auth(token))).status_code == 204


async def test_a_correction_shows_beside_the_model_value_not_instead_of_it(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    doc, token = await _reviewable(client, db_session)
    url = f"/api/v1/documents/{doc['id']}/reviews"
    body = {"field_key": "gross_pay", "verdict": "corrected", "corrected_value": "4250.00"}
    assert (await client.put(url, json=body, headers=_auth(token))).status_code == 200

    detail = (await client.get(f"/api/v1/documents/{doc['id']}", headers=_auth(token))).json()
    assert detail["field_scrutiny"]["gross_pay"]["corrected_value"] == "4250.00"
    # The extraction still says what the model read.
    assert detail["current_extraction"]["extracted_data"]["gross_pay"]["value"] == "4200.00"


async def test_a_rejection_without_a_reason_is_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    doc, token = await _reviewable(client, db_session)
    res = await client.put(
        f"/api/v1/documents/{doc['id']}/reviews",
        json={"field_key": "gross_pay", "verdict": "rejected"},
        headers=_auth(token),
    )
    assert res.status_code == 422


async def test_a_verdict_on_a_field_the_extraction_lacks_is_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # Storing it would put a row in the table that no screen can ever show.
    doc, token = await _reviewable(client, db_session)
    res = await client.put(
        f"/api/v1/documents/{doc['id']}/reviews",
        json={"field_key": "not_a_field", "verdict": "accepted"},
        headers=_auth(token),
    )
    assert res.status_code == 422


async def test_reviews_are_tenant_scoped(client: AsyncClient, db_session: AsyncSession) -> None:
    doc, _token = await _reviewable(client, db_session, slug="acme")
    _other_doc, other_token = await _reviewable(client, db_session, slug="rival")
    url = f"/api/v1/documents/{doc['id']}/reviews"
    for call in (
        client.get(url, headers=_auth(other_token)),
        client.put(
            url, json={"field_key": "gross_pay", "verdict": "accepted"}, headers=_auth(other_token)
        ),
        client.delete(f"{url}/gross_pay", headers=_auth(other_token)),
    ):
        assert (await call).status_code == 404


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


async def test_the_page_endpoint_reports_the_document_length(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The reviewer says "Page 1 of 3" and stops at the last page.

    The count rides with the page because the renderer already has the document
    open; a second endpoint would reopen the same file to answer a question this
    one already knows.
    """
    company, _user, token = await _make_user(db_session, slug="pagecount")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    resp = await client.post(
        _docs_url(loan_file.display_id),
        headers=_auth(token),
        files=[("files", ("three.pdf", _real_pdf(pages=3), "application/pdf"))],
    )
    assert resp.status_code == 201, resp.text
    doc = resp.json()[0]
    await db_session.commit()

    page = await client.get(f"/api/v1/documents/{doc['id']}/page/1", headers=_auth(token))
    assert page.status_code == 200
    assert page.headers["X-Page-Count"] == "3"

    # A page the document does not have is absent, not a lie about the length.
    beyond = await client.get(f"/api/v1/documents/{doc['id']}/page/4", headers=_auth(token))
    assert beyond.status_code == 404


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


def _real_png(width: int = 400, height: int = 300) -> bytes:
    """An actual image, the way a photographed document arrives."""
    doc = pymupdf.open()
    page = doc.new_page(width=width, height=height)
    page.insert_text((20, 40), "photographed pay stub")
    data: bytes = page.get_pixmap().tobytes("png")  # type: ignore[no-untyped-call]
    doc.close()
    return data


async def test_an_image_document_previews(client: AsyncClient, db_session: AsyncSession) -> None:
    """Uploads accept image/png; this endpoint used to refuse it (LP-704).

    AT THE ENDPOINT, because that is where the refusal was — a service-level test
    would have passed against the old code, which rendered images perfectly well
    and was never asked to. The processor's symptom was a document that uploaded
    happily and then showed "No page image for this document" for ever, which
    reads as "still loading", not as "cannot show this".
    """
    company, _user, token = await _make_user(db_session, slug="imgpreview")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    resp = await client.post(
        _docs_url(loan_file.display_id),
        headers=_auth(token),
        files=[("files", ("paystub.png", _real_png(), "image/png"))],
    )
    assert resp.status_code == 201, resp.text
    doc = resp.json()[0]
    assert doc["mime_type"] == "image/png"
    await db_session.commit()

    page = await client.get(f"/api/v1/documents/{doc['id']}/page/1", headers=_auth(token))
    assert page.status_code == 200, page.text
    assert page.content.startswith(b"\x89PNG\r\n\x1a\n")
    # One page, so the reviewer offers no Next that renders nothing.
    assert page.headers["X-Page-Count"] == "1"
    assert float(page.headers["X-Page-Width-Points"]) > 0

    beyond = await client.get(f"/api/v1/documents/{doc['id']}/page/2", headers=_auth(token))
    assert beyond.status_code == 404


async def test_a_page_larger_than_the_budget_is_scaled_down(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A 56-by-69-inch survey shipped 69.3 MB in 4.9 s at the default zoom.

    MEASURED on a stored document, not reasoned. `MAX_ZOOM` never applied — 2.0
    is already under it — because it caps a MULTIPLIER and the page it multiplies
    is unbounded. The response has to say the zoom it actually used, or every box
    the client places is off by the reduction.
    """
    company, _user, token = await _make_user(db_session, slug="bigpage")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = pymupdf.open()
    doc.new_page(width=4047, height=4998)
    huge = bytes(doc.tobytes())
    doc.close()
    resp = await client.post(
        _docs_url(loan_file.display_id),
        headers=_auth(token),
        files=[("files", ("survey.pdf", huge, "application/pdf"))],
    )
    assert resp.status_code == 201, resp.text
    document = resp.json()[0]
    await db_session.commit()

    page = await client.get(f"/api/v1/documents/{document['id']}/page/1", headers=_auth(token))
    assert page.status_code == 200
    applied = float(page.headers["X-Page-Zoom"])
    assert applied < DEFAULT_ZOOM
    # The point space is the PAGE's, unchanged — only the pixels were reduced.
    assert float(page.headers["X-Page-Width-Points"]) == 4047.0
    assert max(4047.0, 4998.0) * applied <= MAX_RENDERED_EDGE + 1


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


# --------------------------------------------------------------------------- #
# LP-637 feature 2 review
# --------------------------------------------------------------------------- #
async def test_a_second_bulk_press_does_not_requeue_the_first_presss_work(
    client: AsyncClient,
    db_session: AsyncSession,
    _mock_reprocess: MagicMock,
    _mock_full_reprocess: MagicMock,
) -> None:
    """`_would_benefit` claimed to prevent this and could not.

    Nothing in it looks at status except to INCLUDE NEEDS_REVIEW and FAILED, and an `unknown`
    document is still `unknown` while it sits at PENDING — so the cohort the feature exists for
    stayed eligible after being queued. A processor who sees nothing change for a minute (serial
    worker, 600s soft limit) and presses again sent every document twice, and two overlapping
    pipelines end with one absorbing an IntegrityError into FAILED while the other's extraction is
    the current one.
    """
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_one(client, loan_file.display_id, token)
    await _set(db_session, doc["id"], document_type="unknown", status=DocumentStatus.COMPLETED)
    _mock_full_reprocess.reset_mock()

    first = await client.post(_bulk_url(loan_file.display_id), headers=_auth(token), json={})
    second = await client.post(_bulk_url(loan_file.display_id), headers=_auth(token), json={})

    assert first.json()["queued"] == 1
    assert second.json()["queued"] == 0, "the second press re-queued the first press's work"
    assert second.json()["skipped"] == {"already_queued": 1}
    assert _mock_full_reprocess.call_count == 1


async def test_all_documents_still_reaches_a_stranded_pending_document(
    client: AsyncClient,
    db_session: AsyncSession,
    _mock_reprocess: MagicMock,
    _mock_full_reprocess: MagicMock,
) -> None:
    """The escape hatch that keeps the PENDING skip from becoming the trap it replaced.

    A document stranded at PENDING by a lost enqueue must stay reachable in bulk. `all_documents`
    is where a processor says "I mean everything", so that is what overrides it — the same flag,
    with the same meaning, rather than a second one.
    """
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_one(client, loan_file.display_id, token)
    await _set(db_session, doc["id"], document_type="w2", status=DocumentStatus.PENDING)
    _mock_full_reprocess.reset_mock()

    resp = await client.post(
        _bulk_url(loan_file.display_id), headers=_auth(token), json={"all_documents": True}
    )

    assert resp.json()["queued"] == 1
    _mock_full_reprocess.assert_called_once_with(doc["id"])


async def test_a_refused_enqueue_puts_the_document_back(
    client: AsyncClient,
    db_session: AsyncSession,
    _mock_reprocess: MagicMock,
    _mock_full_reprocess: MagicMock,
) -> None:
    """The silent one. Both endpoints write PENDING and clear `processing_error` BEFORE a
    fire-and-forget enqueue, so with the broker down a FAILED document became a PENDING one with a
    type and no error: it reads as healthy, shows nothing wrong, and — being typed and not flagged
    — falls outside `_would_benefit`, so the DEFAULT bulk path would skip it as `already_classified`
    for good. At batch scale that is a whole file's diagnostics, gone without a sound.
    """
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_one(client, loan_file.display_id, token)
    await _set(
        db_session,
        doc["id"],
        document_type="w2",
        status=DocumentStatus.FAILED,
        processing_error="extraction failed — fell back to Tier 3 free extraction",
    )
    _mock_full_reprocess.side_effect = RuntimeError("broker down")

    resp = await client.post(_bulk_url(loan_file.display_id), headers=_auth(token), json={})

    assert resp.json()["queued"] == 0
    assert resp.json()["skipped"] == {"enqueue_failed": 1}
    restored = await db_session.get(Document, UUID(doc["id"]))
    assert restored is not None
    await db_session.refresh(restored)
    assert restored.status is DocumentStatus.FAILED, "a lost enqueue cost the document its status"
    assert restored.processing_error == "extraction failed — fell back to Tier 3 free extraction", (
        "the reason it failed was thrown away by an enqueue that never happened"
    )


async def test_a_refused_enqueue_puts_back_a_single_document_too(
    client: AsyncClient,
    db_session: AsyncSession,
    _mock_reprocess: MagicMock,
    _mock_full_reprocess: MagicMock,
) -> None:
    """The per-document endpoint has the same shape, so it needs the same rollback — fixing only
    the path the review happened to look at would leave the identical defect one function away.

    It answers 503 rather than 200, which this test originally pinned the other way. The rollback
    is what changed the premise: nothing durable happens to the document, so a 200 is a claim that
    it is being reprocessed when it is not — and the drawer says "Classifying and extracting in the
    background…" on the strength of that response. Bulk can report this per document as a skip; a
    single reprocess has no partial result, so the status code is the only place the truth fits.
    """
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_one(client, loan_file.display_id, token)
    await _set(
        db_session,
        doc["id"],
        status=DocumentStatus.FAILED,
        processing_error="processing error",
    )
    _mock_full_reprocess.side_effect = RuntimeError("broker down")

    resp = await client.post(_reprocess_url(doc["id"]), headers=_auth(token), json={})

    assert resp.status_code == 503, "a 200 here tells the processor work started that did not"
    assert "Nothing was changed" in resp.json()["error"]["message"]
    restored = await db_session.get(Document, UUID(doc["id"]))
    assert restored is not None
    await db_session.refresh(restored)
    assert restored.status is DocumentStatus.FAILED
    assert restored.processing_error == "processing error"


async def test_bulk_skips_a_superseded_version(
    client: AsyncClient,
    db_session: AsyncSession,
    _mock_reprocess: MagicMock,
    _mock_full_reprocess: MagicMock,
) -> None:
    """The filter that had no test, despite the batch being claimed as mutation-checked.

    `list_documents` applies only `only_active` — `deleted_at IS NULL` — not `is_current`, so
    superseded rows really are in the loop and the branch is load-bearing. Delete it and the suite
    stayed green while superseded versions got re-classified and the whole file's verification was
    marked stale, which both the per-document endpoint and replace refuse outright.
    """
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_one(client, loan_file.display_id, token)
    await _set(
        db_session,
        doc["id"],
        is_current=False,
        document_type="unknown",
        status=DocumentStatus.COMPLETED,
    )
    _mock_full_reprocess.reset_mock()

    resp = await client.post(
        _bulk_url(loan_file.display_id), headers=_auth(token), json={"all_documents": True}
    )

    assert resp.json()["queued"] == 0
    assert resp.json()["skipped"] == {"superseded_version": 1}
    _mock_full_reprocess.assert_not_called()


async def test_a_one_document_batch_is_not_logged_as_plural(
    client: AsyncClient,
    db_session: AsyncSession,
    _mock_reprocess: MagicMock,
    _mock_full_reprocess: MagicMock,
) -> None:
    """ "1 documents sent for reprocessing" lands in the feed a processor reads, and a one-document
    batch is the common case on a small file. The upload handler in the same file pluralizes."""
    from app.models.activity_log import ActivityLog

    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_one(client, loan_file.display_id, token)
    await _set(db_session, doc["id"], document_type="unknown", status=DocumentStatus.COMPLETED)

    await client.post(_bulk_url(loan_file.display_id), headers=_auth(token), json={})

    entries = (
        await db_session.scalars(
            select(ActivityLog).where(
                ActivityLog.loan_file_id == loan_file.id,
                ActivityLog.activity_type == ActivityType.DOCUMENT_REPROCESSED,
            )
        )
    ).all()
    assert len(entries) == 1
    assert entries[0].summary == "1 document sent for reprocessing"


async def test_bulk_refuses_a_batch_larger_than_the_cap(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    _mock_reprocess: MagicMock,
    _mock_full_reprocess: MagicMock,
) -> None:
    """A foot-gun guard on the widened path, not a capacity limit.

    `all_documents` enqueues one task per document, each with a 600s soft limit, onto a worker that
    runs them serially — one press can hold the document worker for hours and put every other
    file's uploads behind it. The bounded DEFAULT was argued for in the schema; nothing bounded the
    escape hatch, and feature 3 is about to put a button on it.

    The cap is patched down rather than uploading 101 files, so this tests the guard and not the
    fixture.
    """
    monkeypatch.setattr(documents_api, "_MAX_BULK_REPROCESS", 1)
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    for _ in range(2):
        doc = await _upload_one(client, loan_file.display_id, token)
        await _set(db_session, doc["id"], document_type="unknown", status=DocumentStatus.COMPLETED)
    _mock_full_reprocess.reset_mock()

    resp = await client.post(_bulk_url(loan_file.display_id), headers=_auth(token), json={})

    assert resp.status_code == 400
    assert "2 documents selected" in resp.json()["error"]["message"]
    _mock_full_reprocess.assert_not_called()


async def test_reprocess_accepts_a_document_abandoned_mid_pipeline(
    client: AsyncClient,
    db_session: AsyncSession,
    _mock_reprocess: MagicMock,
    _mock_full_reprocess: MagicMock,
) -> None:
    """The API half of the same fix, and the half that decides whether it matters.

    Reclaiming inside the pipeline is useless on its own: a stuck document is only re-enqueued
    because a processor asks, and on status alone this endpoint refused. So a worker killed
    mid-run — an OOM, a deploy, or LP-630's nightly 22:00 shutdown of staging — left a document
    with no route back through the product at all.
    """
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_one(client, loan_file.display_id, token)
    abandoned = await db_session.get(Document, UUID(doc["id"]))
    assert abandoned is not None
    abandoned.status = DocumentStatus.CLASSIFYING
    await db_session.commit()

    # Still refused while a worker could plausibly be behind it.
    live = await client.post(_reprocess_url(doc["id"]), headers=_auth(token), json={})
    assert live.status_code == 409, "a live run must still be protected"

    abandoned.updated_at = utcnow() - timedelta(
        seconds=PIPELINE_PRESUMED_ABANDONED_AFTER_SECONDS + 60
    )
    await db_session.commit()
    _mock_full_reprocess.reset_mock()

    resp = await client.post(_reprocess_url(doc["id"]), headers=_auth(token), json={})

    assert resp.status_code == 200, "an abandoned document was unreachable through the product"
    _mock_full_reprocess.assert_called_once_with(doc["id"])


async def test_bulk_picks_up_a_document_abandoned_mid_pipeline(
    client: AsyncClient,
    db_session: AsyncSession,
    _mock_reprocess: MagicMock,
    _mock_full_reprocess: MagicMock,
) -> None:
    """Bulk skipped it as `already_processing` for the same reason, which is the shape that hides
    it — a skip reported as "someone is on it" when nobody is."""
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_one(client, loan_file.display_id, token)
    abandoned = await db_session.get(Document, UUID(doc["id"]))
    assert abandoned is not None
    abandoned.status = DocumentStatus.CLASSIFYING
    abandoned.document_type = "unknown"
    abandoned.updated_at = utcnow() - timedelta(
        seconds=PIPELINE_PRESUMED_ABANDONED_AFTER_SECONDS + 60
    )
    await db_session.commit()
    _mock_full_reprocess.reset_mock()

    resp = await client.post(_bulk_url(loan_file.display_id), headers=_auth(token), json={})

    assert resp.json()["queued"] == 1, f"still skipped: {resp.json()['skipped']}"
    _mock_full_reprocess.assert_called_once_with(doc["id"])


async def test_the_type_override_refuses_a_document_mid_pipeline(
    client: AsyncClient,
    db_session: AsyncSession,
    _mock_reprocess: MagicMock,
    _mock_full_reprocess: MagicMock,
) -> None:
    """The claim is only exclusive against itself unless every path that writes an extraction
    respects it. This endpoint enqueues `reprocess_document`, which now takes the claim in its own
    task — so an override during a live pipeline would be dropped by that claim SILENTLY, and the
    processor would watch their correction do nothing. Refusing says so."""
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_one(client, loan_file.display_id, token)
    running = await db_session.get(Document, UUID(doc["id"]))
    assert running is not None
    running.status = DocumentStatus.CLASSIFIED
    await db_session.commit()
    _mock_reprocess.reset_mock()

    resp = await client.patch(
        f"/api/v1/documents/{doc['id']}",
        headers=_auth(token),
        json={"document_type": "w2"},
    )

    assert resp.status_code == 409
    _mock_reprocess.assert_not_called()


async def test_bulk_reports_an_abandoned_document_honestly(
    client: AsyncClient,
    db_session: AsyncSession,
    _mock_reprocess: MagicMock,
    _mock_full_reprocess: MagicMock,
) -> None:
    """An abandoned document WITH a type fell past the in-flight skip into `_would_benefit`, which
    saw a typed, unflagged document and reported `already_classified` — the default bulk press
    could still not recover it, and described a stranded document as one the classifier was happy
    with."""
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_one(client, loan_file.display_id, token)
    abandoned = await db_session.get(Document, UUID(doc["id"]))
    assert abandoned is not None
    abandoned.status = DocumentStatus.EXTRACTING
    abandoned.document_type = "w2"  # a real type: `_would_benefit` would otherwise say no
    abandoned.updated_at = utcnow() - timedelta(
        seconds=PIPELINE_PRESUMED_ABANDONED_AFTER_SECONDS + 60
    )
    await db_session.commit()
    _mock_full_reprocess.reset_mock()

    resp = await client.post(_bulk_url(loan_file.display_id), headers=_auth(token), json={})

    assert resp.json()["queued"] == 1, f"still unreachable: {resp.json()['skipped']}"
    _mock_full_reprocess.assert_called_once_with(doc["id"])


async def test_bulk_reports_an_unreadable_file_as_such_not_as_already_identified(
    client: AsyncClient,
    db_session: AsyncSession,
    _mock_reprocess: MagicMock,
    _mock_full_reprocess: MagicMock,
) -> None:
    """The skip has to name what happened.

    Folded into `_would_benefit`, a size-refused document came back under `already_classified`,
    which the UI renders "already identified" — said about a document the processor is looking at
    with no type at all. It also buried the one instruction the pipeline had actually produced:
    split the file, or rescan it lower.
    """
    from app.tasks.document_processing import PAYLOAD_TOO_LARGE_MESSAGE

    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_one(client, loan_file.display_id, token)
    too_big = await db_session.get(Document, UUID(doc["id"]))
    assert too_big is not None
    too_big.status = DocumentStatus.NEEDS_REVIEW
    too_big.processing_error = PAYLOAD_TOO_LARGE_MESSAGE
    await db_session.commit()
    _mock_full_reprocess.reset_mock()

    resp = await client.post(_bulk_url(loan_file.display_id), headers=_auth(token), json={})

    assert resp.json()["queued"] == 0
    assert resp.json()["skipped"] == {"too_large_to_read": 1}
    _mock_full_reprocess.assert_not_called()


async def test_the_reason_a_document_failed_reaches_the_response(
    client: AsyncClient,
    db_session: AsyncSession,
    _mock_reprocess: MagicMock,
    _mock_full_reprocess: MagicMock,
) -> None:
    """THE PREMISE OF WRITING IT AT ALL, and it was false.

    The pipeline writes `processing_error` because "that column is the only place a processor
    looks" — but no response schema carried it and nothing in the frontend referenced it. Two
    carefully-worded failure voices were dead text, and LF-ZE9N's oversized document would still
    have read "Processing / uncategorized" with no explanation after the fix that was written for
    exactly that complaint.
    """
    from app.tasks.document_processing import PAYLOAD_TOO_LARGE_MESSAGE

    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_one(client, loan_file.display_id, token)
    failed = await db_session.get(Document, UUID(doc["id"]))
    assert failed is not None
    failed.status = DocumentStatus.NEEDS_REVIEW
    failed.processing_error = PAYLOAD_TOO_LARGE_MESSAGE
    await db_session.commit()

    listed = await client.get(
        f"/api/v1/loan-files/{loan_file.display_id}/documents", headers=_auth(token)
    )
    assert listed.status_code == 200
    assert listed.json()[0]["processing_error"] == PAYLOAD_TOO_LARGE_MESSAGE

    detail = await client.get(f"/api/v1/documents/{doc['id']}", headers=_auth(token))
    assert detail.status_code == 200
    assert detail.json()["processing_error"] == PAYLOAD_TOO_LARGE_MESSAGE


# --------------------------------------------------------------------------- #
# LP-638 — the type-correction control offers the catalog, and only the catalog
# --------------------------------------------------------------------------- #
async def test_the_type_list_is_the_whole_catalog(client: AsyncClient, db_session) -> None:
    """THE REPORTED PROBLEM. The control offered eight hardcoded options written when the catalog
    had three types. It now has 164, so a processor could not correct a document to
    `closing_disclosure` at all — which is exactly what LF-ZE9N needed and could not do."""
    from app.documents.catalog import CATALOG

    _company, _user, token = await _make_user(db_session, slug="acme")

    resp = await client.get("/api/v1/documents/types/catalog", headers=_auth(token))

    assert resp.status_code == 200
    values = {option["value"] for option in resp.json()}
    assert values == set(CATALOG), "the list and the catalog have drifted"
    for needed in ("closing_disclosure", "purchase_agreement", "mortgage_statement"):
        assert needed in values


async def test_every_offered_type_is_one_the_override_accepts(
    client: AsyncClient, db_session
) -> None:
    """The two halves must agree. A picker offering a type the PATCH rejects would be the same
    defect wearing the other face — and both now read the same CATALOG, so this is a guard against
    someone giving one of them its own list again."""
    from app.documents.catalog import CATALOG

    _company, _user, token = await _make_user(db_session, slug="acme")
    resp = await client.get("/api/v1/documents/types/catalog", headers=_auth(token))

    for option in resp.json():
        assert option["value"] in CATALOG
        assert option["label"], f"{option['value']} has no label to show"


async def test_the_override_refuses_a_type_the_catalog_does_not_know(
    client: AsyncClient, db_session, _mock_reprocess: MagicMock
) -> None:
    """THE HOLE THAT CAUSED THE ORIGINAL DAMAGE. The old dropdown offered `tax_return_1040` and
    `other`, neither a catalog type, and this endpoint accepted them. The document got no tier, no
    category and no extractor — and since satisfaction matches `needs_type == document_type`
    exactly, a document corrected to `tax_return_1040` could never satisfy a `tax_return` need.
    Correcting the type made the file quietly worse."""
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_one(client, loan_file.display_id, token)

    resp = await client.patch(
        _override_url(doc["id"]), headers=_auth(token), json={"document_type": "tax_return_1040"}
    )

    assert resp.status_code == 422
    _mock_reprocess.assert_not_called()


async def test_a_real_catalog_type_still_applies(
    client: AsyncClient, db_session, _mock_reprocess: MagicMock
) -> None:
    """The positive control. A validation that rejected everything would pass the test above."""
    company, _user, token = await _make_user(db_session, slug="acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    doc = await _upload_one(client, loan_file.display_id, token)

    resp = await client.patch(
        _override_url(doc["id"]),
        headers=_auth(token),
        json={"document_type": "closing_disclosure"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["document_type"] == "closing_disclosure"
    # Tier and category are re-derived from the catalog, which is what the invalid types could not do.
    assert body["category"] == "disclosures"

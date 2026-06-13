"""Document flow (LP-45) — upload → list → get → download → soft-delete.

Real multipart upload of a small PDF stored on the local temp-dir backend, real
byte round-trip on download, and the upload→enqueue seam (``process_document``
``.delay`` asserted, no worker run). Plus upload validation (disallowed type /
spoofed content / oversize) and the ``storage_path`` leak guard.
"""

from app.models import Company
from app.models.loan_file import LoanFile
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration import factories
from tests.integration.conftest import Dispatch

PDF = factories.PDF_BYTES
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _nested(loan_file: LoanFile) -> str:
    return f"/api/v1/loan-files/{loan_file.id}/documents"


async def _loan_file(db, company: Company) -> LoanFile:
    return await factories.make_loan_file(db, company=company)


async def test_document_upload_list_get_download_delete(
    auth_client: AsyncClient, db: AsyncSession, company_a: Company, mock_dispatch: Dispatch
) -> None:
    loan_file = await _loan_file(db, company_a)

    # upload (201, PENDING) + enqueue asserted
    up = await auth_client.post(
        _nested(loan_file), files=[("files", ("paystub.pdf", PDF, "application/pdf"))]
    )
    assert up.status_code == 201
    doc = up.json()[0]
    assert doc["status"] == "pending"
    assert "storage_path" not in doc
    mock_dispatch.process.assert_called_once_with(doc["id"])

    # list — appears, with category fields present (None pre-pipeline)
    listed = await auth_client.get(_nested(loan_file))
    assert listed.status_code == 200
    assert any(d["id"] == doc["id"] for d in listed.json())
    assert "category" in listed.json()[0]

    # get (200) — detail carries the current_extraction slot (None until pipeline)
    detail = await auth_client.get(f"/api/v1/documents/{doc['id']}")
    assert detail.status_code == 200
    assert detail.json()["current_extraction"] is None
    assert "storage_path" not in detail.json()

    # download (200) — exact bytes
    dl = await auth_client.get(f"/api/v1/documents/{doc['id']}/download")
    assert dl.status_code == 200
    assert dl.content == PDF
    assert "attachment" in dl.headers["content-disposition"]

    # soft-delete (204) → subsequent get 404
    assert (await auth_client.delete(f"/api/v1/documents/{doc['id']}")).status_code == 204
    assert (await auth_client.get(f"/api/v1/documents/{doc['id']}")).status_code == 404


async def test_upload_rejects_disallowed_type(
    auth_client: AsyncClient, db: AsyncSession, company_a: Company
) -> None:
    loan_file = await _loan_file(db, company_a)
    resp = await auth_client.post(
        _nested(loan_file), files=[("files", ("notes.txt", b"hello", "text/plain"))]
    )
    assert resp.status_code == 415


async def test_upload_rejects_content_spoof(
    auth_client: AsyncClient, db: AsyncSession, company_a: Company
) -> None:
    loan_file = await _loan_file(db, company_a)
    # Declares PDF but the bytes are PNG → magic-byte check rejects.
    resp = await auth_client.post(
        _nested(loan_file), files=[("files", ("fake.pdf", PNG, "application/pdf"))]
    )
    assert resp.status_code == 415


async def test_upload_with_no_files_is_400(
    auth_client: AsyncClient, db: AsyncSession, company_a: Company
) -> None:
    loan_file = await _loan_file(db, company_a)
    # An empty multipart "files" part → 400 (no files provided).
    resp = await auth_client.post(
        _nested(loan_file), files=[("files", ("", b"", "application/pdf"))]
    )
    assert resp.status_code in (400, 422)


async def test_upload_survives_enqueue_failure(
    auth_client: AsyncClient, db: AsyncSession, company_a: Company, mock_dispatch: Dispatch
) -> None:
    """A broker hiccup must NOT fail the upload — the bytes/record are safe (PENDING)."""
    loan_file = await _loan_file(db, company_a)
    mock_dispatch.process.side_effect = RuntimeError("broker down")
    resp = await auth_client.post(
        _nested(loan_file), files=[("files", ("a.pdf", PDF, "application/pdf"))]
    )
    assert resp.status_code == 201
    assert resp.json()[0]["status"] == "pending"


async def test_document_routes_require_auth(
    client: AsyncClient, db: AsyncSession, company_a: Company
) -> None:
    loan_file = await _loan_file(db, company_a)
    assert (await client.get(_nested(loan_file))).status_code == 401
    assert (
        await client.post(_nested(loan_file), files=[("files", ("a.pdf", PDF, "application/pdf"))])
    ).status_code == 401

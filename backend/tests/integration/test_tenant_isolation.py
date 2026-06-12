"""SYSTEMATIC tenant isolation (LP-45) — the security-critical pass.

A Company A actor (``auth_client``) must get **404** (never the data, never 403)
for **every** company-scoped resource owned by Company B, and Company A's lists
must not leak Company B's rows. Possessing a valid id grants nothing without
entitlement (ADR-036); cross-company resolution returns 404 to avoid even
confirming existence (anti-enumeration).

ENUMERATED company-scoped routes (each asserted 404 cross-company below):

  Loan files (flat):
    - GET    /loan-files/{id}
    - PATCH  /loan-files/{id}
    - DELETE /loan-files/{id}
    - GET    /loan-files            (list must NOT include B's files)
  Nested under a loan file (gated by ScopedLoanFile → 404 on a B file):
    - GET    /loan-files/{id}/borrowers
    - POST   /loan-files/{id}/borrowers
    - GET    /loan-files/{id}/property
    - POST   /loan-files/{id}/property
    - GET    /loan-files/{id}/needs
    - GET    /loan-files/{id}/activity
    - GET    /loan-files/{id}/documents
    - POST   /loan-files/{id}/documents
  Documents (flat, gated by get_document_for_company → 404):
    - GET    /documents/{id}
    - PATCH  /documents/{id}            (type override)
    - GET    /documents/{id}/download
    - DELETE /documents/{id}
  Dev (non-prod, tenant-scoped):
    - POST   /dev/documents/{id}/extract-text-layer
  Company-scoped list (no id; leak check):
    - GET    /lenders                  (must NOT include B's lenders)

The auth boundary (401 no-token) is covered per-flow in the other modules and
re-asserted compactly at the end here.
"""

from app.models import Company, User
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration import factories

V1 = "/api/v1"


# --------------------------------------------------------------------------- #
# Loan files (flat)
# --------------------------------------------------------------------------- #


async def test_cannot_get_other_company_loan_file(
    auth_client: AsyncClient, db: AsyncSession, company_b: Company
) -> None:
    other = await factories.make_loan_file(db, company=company_b)
    assert (await auth_client.get(f"{V1}/loan-files/{other.id}")).status_code == 404


async def test_cannot_patch_other_company_loan_file(
    auth_client: AsyncClient, db: AsyncSession, company_b: Company
) -> None:
    other = await factories.make_loan_file(db, company=company_b)
    resp = await auth_client.patch(
        f"{V1}/loan-files/{other.id}", json={"loan_officer_name": "Hacker"}
    )
    assert resp.status_code == 404


async def test_cannot_delete_other_company_loan_file(
    auth_client: AsyncClient, db: AsyncSession, company_b: Company
) -> None:
    other = await factories.make_loan_file(db, company=company_b)
    assert (await auth_client.delete(f"{V1}/loan-files/{other.id}")).status_code == 404


async def test_list_loan_files_does_not_leak_other_company(
    auth_client: AsyncClient, db: AsyncSession, company_a: Company, company_b: Company
) -> None:
    mine = await factories.make_loan_file(db, company=company_a)
    theirs = await factories.make_loan_file(db, company=company_b)
    resp = await auth_client.get(f"{V1}/loan-files")
    ids = {item["id"] for item in resp.json()["items"]}
    assert str(mine.id) in ids
    assert str(theirs.id) not in ids


# --------------------------------------------------------------------------- #
# Nested under a loan file (the file gate is the tenant boundary)
# --------------------------------------------------------------------------- #


async def test_cannot_read_other_company_borrowers(
    auth_client: AsyncClient, db: AsyncSession, company_b: Company
) -> None:
    other = await factories.make_loan_file(db, company=company_b)
    await factories.make_borrower(db, loan_file=other)
    assert (await auth_client.get(f"{V1}/loan-files/{other.id}/borrowers")).status_code == 404


async def test_cannot_add_borrower_to_other_company_file(
    auth_client: AsyncClient, db: AsyncSession, company_b: Company
) -> None:
    other = await factories.make_loan_file(db, company=company_b)
    resp = await auth_client.post(
        f"{V1}/loan-files/{other.id}/borrowers",
        json={"first_name": "X", "last_name": "Y"},
    )
    assert resp.status_code == 404


async def test_cannot_read_other_company_property(
    auth_client: AsyncClient, db: AsyncSession, company_b: Company
) -> None:
    other = await factories.make_loan_file(db, company=company_b)
    await factories.make_property(db, loan_file=other)
    assert (await auth_client.get(f"{V1}/loan-files/{other.id}/property")).status_code == 404


async def test_cannot_create_property_on_other_company_file(
    auth_client: AsyncClient, db: AsyncSession, company_b: Company
) -> None:
    other = await factories.make_loan_file(db, company=company_b)
    resp = await auth_client.post(f"{V1}/loan-files/{other.id}/property", json={"city": "Nope"})
    assert resp.status_code == 404


async def test_cannot_read_other_company_needs(
    auth_client: AsyncClient, db: AsyncSession, company_b: Company
) -> None:
    other = await factories.make_loan_file(db, company=company_b)
    await factories.make_needs_item(db, loan_file=other)
    assert (await auth_client.get(f"{V1}/loan-files/{other.id}/needs")).status_code == 404


async def test_cannot_read_other_company_activity(
    auth_client: AsyncClient, db: AsyncSession, company_b: Company
) -> None:
    other = await factories.make_loan_file(db, company=company_b)
    assert (await auth_client.get(f"{V1}/loan-files/{other.id}/activity")).status_code == 404


async def test_cannot_list_other_company_documents(
    auth_client: AsyncClient, db: AsyncSession, company_b: Company
) -> None:
    other = await factories.make_loan_file(db, company=company_b)
    assert (await auth_client.get(f"{V1}/loan-files/{other.id}/documents")).status_code == 404


async def test_cannot_upload_to_other_company_file(
    auth_client: AsyncClient, db: AsyncSession, company_b: Company
) -> None:
    other = await factories.make_loan_file(db, company=company_b)
    resp = await auth_client.post(
        f"{V1}/loan-files/{other.id}/documents",
        files=[("files", ("a.pdf", factories.PDF_BYTES, "application/pdf"))],
    )
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# Documents (flat) — get_document_for_company joins document→loan_file→company
# --------------------------------------------------------------------------- #


async def _other_document(db: AsyncSession, company_b: Company, user_b: User):
    lf = await factories.make_loan_file(db, company=company_b)
    return await factories.make_document(db, loan_file=lf, company=company_b, uploaded_by=user_b)


async def test_cannot_get_other_company_document(
    auth_client: AsyncClient, db: AsyncSession, company_b: Company, user_b: User
) -> None:
    doc = await _other_document(db, company_b, user_b)
    assert (await auth_client.get(f"{V1}/documents/{doc.id}")).status_code == 404


async def test_cannot_override_other_company_document(
    auth_client: AsyncClient, db: AsyncSession, company_b: Company, user_b: User
) -> None:
    doc = await _other_document(db, company_b, user_b)
    resp = await auth_client.patch(f"{V1}/documents/{doc.id}", json={"document_type": "w2"})
    assert resp.status_code == 404


async def test_cannot_download_other_company_document(
    auth_client: AsyncClient, db: AsyncSession, company_b: Company, user_b: User
) -> None:
    doc = await _other_document(db, company_b, user_b)
    assert (await auth_client.get(f"{V1}/documents/{doc.id}/download")).status_code == 404


async def test_cannot_delete_other_company_document(
    auth_client: AsyncClient, db: AsyncSession, company_b: Company, user_b: User
) -> None:
    doc = await _other_document(db, company_b, user_b)
    assert (await auth_client.delete(f"{V1}/documents/{doc.id}")).status_code == 404


async def test_cannot_dev_extract_other_company_document(
    auth_client: AsyncClient, db: AsyncSession, company_b: Company, user_b: User
) -> None:
    doc = await _other_document(db, company_b, user_b)
    resp = await auth_client.post(f"{V1}/dev/documents/{doc.id}/extract-text-layer")
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# Company-scoped list (no id) — leak check
# --------------------------------------------------------------------------- #


async def test_lenders_list_does_not_leak_other_company(
    auth_client: AsyncClient, db: AsyncSession, company_a: Company, company_b: Company
) -> None:
    await factories.make_lender(db, company=company_a, name="Mine Bank")
    await factories.make_lender(db, company=company_b, name="Theirs Bank")
    resp = await auth_client.get(f"{V1}/lenders")
    names = {lender["name"] for lender in resp.json()}
    assert "Mine Bank" in names
    assert "Theirs Bank" not in names


# --------------------------------------------------------------------------- #
# Auth boundary (compact re-assertion: every protected family rejects no-token)
# --------------------------------------------------------------------------- #


async def test_protected_routes_reject_missing_token(
    client: AsyncClient, db: AsyncSession, company_a: Company
) -> None:
    lf = await factories.make_loan_file(db, company=company_a)
    doc = await factories.make_document(db, loan_file=lf, company=company_a)
    no_auth = [
        ("get", f"{V1}/loan-files"),
        ("get", f"{V1}/loan-files/{lf.id}"),
        ("get", f"{V1}/loan-files/{lf.id}/borrowers"),
        ("get", f"{V1}/loan-files/{lf.id}/property"),
        ("get", f"{V1}/loan-files/{lf.id}/needs"),
        ("get", f"{V1}/loan-files/{lf.id}/activity"),
        ("get", f"{V1}/loan-files/{lf.id}/documents"),
        ("get", f"{V1}/documents/{doc.id}"),
        ("get", f"{V1}/documents/{doc.id}/download"),
        ("get", f"{V1}/lenders"),
    ]
    for method, url in no_auth:
        resp = await getattr(client, method)(url)
        assert resp.status_code == 401, f"{method.upper()} {url} should be 401"

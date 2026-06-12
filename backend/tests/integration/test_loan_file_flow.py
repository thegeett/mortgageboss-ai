"""Loan-file lifecycle (LP-45) — create → list → get → update → soft-delete.

Drives the full CRUD path through real HTTP/DB/auth/services, asserting each
stage persists and the final delete removes the file from both list and get.
``inbox_token`` must never appear in any response.
"""

from app.models import Company
from httpx import AsyncClient

LF = "/api/v1/loan-files"


async def test_loan_file_lifecycle(auth_client: AsyncClient) -> None:
    # create (201)
    created = await auth_client.post(
        LF, json={"loan_purpose": "purchase", "loan_officer_name": "Pat Officer"}
    )
    assert created.status_code == 201
    file_id = created.json()["id"]
    assert "inbox_token" not in created.json()

    # list — the new file appears
    listed = await auth_client.get(LF)
    assert listed.status_code == 200
    page = listed.json()
    assert any(item["id"] == file_id for item in page["items"])
    assert all("inbox_token" not in item for item in page["items"])

    # get (200)
    got = await auth_client.get(f"{LF}/{file_id}")
    assert got.status_code == 200
    assert got.json()["id"] == file_id

    # update (200) — change persists
    updated = await auth_client.patch(f"{LF}/{file_id}", json={"loan_officer_name": "New Name"})
    assert updated.status_code == 200
    assert updated.json()["loan_officer_name"] == "New Name"
    refetched = await auth_client.get(f"{LF}/{file_id}")
    assert refetched.json()["loan_officer_name"] == "New Name"

    # soft-delete (204) → gone from list + 404 on get
    deleted = await auth_client.delete(f"{LF}/{file_id}")
    assert deleted.status_code == 204
    assert (await auth_client.get(f"{LF}/{file_id}")).status_code == 404
    after = await auth_client.get(LF)
    assert all(item["id"] != file_id for item in after.json()["items"])


async def test_get_unknown_loan_file_is_404(auth_client: AsyncClient) -> None:
    # A well-formed but non-existent UUID → 404 (not 500).
    missing = "00000000-0000-0000-0000-000000000000"
    assert (await auth_client.get(f"{LF}/{missing}")).status_code == 404


async def test_loan_file_routes_require_auth(client: AsyncClient, company_a: Company) -> None:
    assert (await client.get(LF)).status_code == 401
    assert (await client.post(LF, json={})).status_code == 401

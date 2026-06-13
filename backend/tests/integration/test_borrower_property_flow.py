"""Borrower & property CRUD flows (LP-45) — real mutations through the stack.

These exercise the create/update/delete handlers for the two nested intake
resources end-to-end (the per-resource unit tests cover the service layer; this
covers the HTTP→service→DB seam, including SSN masking on write and the
single-property 409 conflict).
"""

from app.models import Company
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration import factories

V1 = "/api/v1"


async def test_borrower_crud_flow(
    auth_client: AsyncClient, db: AsyncSession, company_a: Company
) -> None:
    lf = await factories.make_loan_file(db, company=company_a)
    base = f"{V1}/loan-files/{lf.id}/borrowers"

    # create (201) — SSN accepted raw, returned masked
    created = await auth_client.post(
        base, json={"first_name": "Dana", "last_name": "Buyer", "ssn": "111-22-3333"}
    )
    assert created.status_code == 201
    borrower_id = created.json()["id"]
    assert "ssn" not in created.json()
    assert created.json()["masked_ssn"].endswith("3333")

    # get (200)
    got = await auth_client.get(f"{base}/{borrower_id}")
    assert got.status_code == 200
    assert got.json()["first_name"] == "Dana"

    # update (200) — change persists
    updated = await auth_client.patch(f"{base}/{borrower_id}", json={"last_name": "Owner"})
    assert updated.status_code == 200
    assert updated.json()["last_name"] == "Owner"

    # delete (204) → gone
    assert (await auth_client.delete(f"{base}/{borrower_id}")).status_code == 204
    assert (await auth_client.get(f"{base}/{borrower_id}")).status_code == 404


async def test_unknown_borrower_is_404(
    auth_client: AsyncClient, db: AsyncSession, company_a: Company
) -> None:
    lf = await factories.make_loan_file(db, company=company_a)
    missing = "00000000-0000-0000-0000-000000000000"
    base = f"{V1}/loan-files/{lf.id}/borrowers/{missing}"
    # get / patch / delete on a borrower that isn't under this file → 404.
    assert (await auth_client.get(base)).status_code == 404
    assert (await auth_client.patch(base, json={"last_name": "X"})).status_code == 404
    assert (await auth_client.delete(base)).status_code == 404


async def test_property_crud_flow_and_singleton_conflict(
    auth_client: AsyncClient, db: AsyncSession, company_a: Company
) -> None:
    lf = await factories.make_loan_file(db, company=company_a)
    base = f"{V1}/loan-files/{lf.id}/property"

    # no property yet → 404
    assert (await auth_client.get(base)).status_code == 404

    # create (201)
    created = await auth_client.post(base, json={"city": "Austin", "state": "TX"})
    assert created.status_code == 201
    assert created.json()["city"] == "Austin"

    # a second create → 409 (singleton)
    assert (await auth_client.post(base, json={"city": "Dallas"})).status_code == 409

    # update (200)
    updated = await auth_client.patch(base, json={"city": "Houston"})
    assert updated.status_code == 200
    assert updated.json()["city"] == "Houston"

    # delete (204) → gone
    assert (await auth_client.delete(base)).status_code == 204
    assert (await auth_client.get(base)).status_code == 404

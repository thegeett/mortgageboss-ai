"""Edit-imported-data tests (LP-56) — the editability safety net.

Imports the real fixture (LP-54), then exercises the stated-financials CRUD +
the MISMO core-field edits (via the reused Epic 4 PATCH endpoints): update / add
/ remove rows, edit core fields, the SSN replace, audit, tenant isolation, and
validation.
"""

from pathlib import Path

import pytest
from app.models import Company
from httpx import AsyncClient

V1 = "/api/v1"
FIXTURE = Path(__file__).parent.parent / "fixtures" / "mismo" / "MISMO16940192.xml"


@pytest.fixture
def raw_bytes() -> bytes:
    return FIXTURE.read_bytes()


async def _import(auth_client: AsyncClient, raw: bytes) -> str:
    """Import the fixture; return the created file's id."""
    resp = await auth_client.post(
        f"{V1}/loan-files/import-mismo", files={"file": ("m.xml", raw, "application/xml")}
    )
    assert resp.status_code == 201
    return resp.json()["loan_file"]["id"]


async def _financials(auth_client: AsyncClient, file_id: str) -> dict:
    resp = await auth_client.get(f"{V1}/loan-files/{file_id}/stated-financials")
    assert resp.status_code == 200
    return resp.json()


# --------------------------------------------------------------------------- #
# Stated-financials CRUD
# --------------------------------------------------------------------------- #


async def test_update_stated_liability(auth_client: AsyncClient, raw_bytes: bytes) -> None:
    file_id = await _import(auth_client, raw_bytes)
    liab = (await _financials(auth_client, file_id))["liabilities"][0]
    resp = await auth_client.patch(
        f"{V1}/stated-liabilities/{liab['id']}", json={"monthly_payment": "123.45"}
    )
    assert resp.status_code == 200
    assert resp.json()["monthly_payment"] == "123.45"
    # Persists in the read.
    after = (await _financials(auth_client, file_id))["liabilities"]
    assert any(x["id"] == liab["id"] and x["monthly_payment"] == "123.45" for x in after)


async def test_add_and_remove_stated_liability(auth_client: AsyncClient, raw_bytes: bytes) -> None:
    file_id = await _import(auth_client, raw_bytes)
    before = len((await _financials(auth_client, file_id))["liabilities"])

    add = await auth_client.post(
        f"{V1}/loan-files/{file_id}/stated-liabilities",
        json={"liability_type": "HELOC", "monthly_payment": "250.00", "unpaid_balance": "9000.00"},
    )
    assert add.status_code == 201
    new_id = add.json()["id"]
    assert len((await _financials(auth_client, file_id))["liabilities"]) == before + 1

    rm = await auth_client.delete(f"{V1}/stated-liabilities/{new_id}")
    assert rm.status_code == 204
    after = (await _financials(auth_client, file_id))["liabilities"]
    assert len(after) == before
    assert all(x["id"] != new_id for x in after)  # soft-deleted → absent from the read


async def test_add_stated_income_to_borrower(auth_client: AsyncClient, raw_bytes: bytes) -> None:
    file_id = await _import(auth_client, raw_bytes)
    borrower_id = (await _financials(auth_client, file_id))["borrowers"][0]["id"]
    resp = await auth_client.post(
        f"{V1}/loan-files/{file_id}/borrowers/{borrower_id}/stated-income",
        json={"monthly_amount": "1500.00", "income_type": "Bonus", "employment_income": True},
    )
    assert resp.status_code == 201
    assert resp.json()["income_type"] == "Bonus"
    income = (await _financials(auth_client, file_id))["borrowers"][0]["income_items"]
    assert any(i["monthly_amount"] == "1500.00" for i in income)


async def test_update_stated_asset_and_employer(auth_client: AsyncClient, raw_bytes: bytes) -> None:
    file_id = await _import(auth_client, raw_bytes)
    fin = await _financials(auth_client, file_id)
    asset_id = fin["assets"][0]["id"]
    employer = fin["borrowers"][0]["employers"][0]
    assert (
        await auth_client.patch(f"{V1}/stated-assets/{asset_id}", json={"value": "70000.00"})
    ).json()["value"] == "70000.00"
    assert (
        await auth_client.patch(
            f"{V1}/stated-employers/{employer['id']}", json={"employer_name": "New Employer LLC"}
        )
    ).json()["employer_name"] == "New Employer LLC"


# --------------------------------------------------------------------------- #
# MISMO core-field edits (reused Epic 4 PATCH; extended schemas)
# --------------------------------------------------------------------------- #


async def test_edit_mismo_core_fields(auth_client: AsyncClient, raw_bytes: bytes) -> None:
    file_id = await _import(auth_client, raw_bytes)
    # Loan term (a parse-warned-style core field) via the reused loan-file PATCH.
    lf = await auth_client.patch(f"{V1}/loan-files/{file_id}", json={"note_rate_percent": "7.1250"})
    assert lf.status_code == 200
    # Property MISMO field via the reused property PATCH.
    prop = await auth_client.patch(
        f"{V1}/loan-files/{file_id}/property", json={"valuation_amount": "1400000.00"}
    )
    assert prop.status_code == 200
    fin = await _financials(auth_client, file_id)
    assert fin["loan_terms"]["note_rate_percent"] == "7.1250"
    assert fin["property_extras"]["valuation_amount"] == "1400000.00"


async def test_ssn_replace_reencrypts_and_masks(auth_client: AsyncClient, raw_bytes: bytes) -> None:
    file_id = await _import(auth_client, raw_bytes)
    borrower_id = (await _financials(auth_client, file_id))["borrowers"][0]["id"]
    resp = await auth_client.patch(
        f"{V1}/loan-files/{file_id}/borrowers/{borrower_id}",
        json={"ssn": "900445566"},  # pragma: allowlist secret  (synthetic)
    )
    assert resp.status_code == 200
    assert "900445566" not in resp.text  # raw SSN never echoed
    assert resp.json()["masked_ssn"].endswith("5566")


# --------------------------------------------------------------------------- #
# Audit
# --------------------------------------------------------------------------- #


async def test_edit_is_audited(auth_client: AsyncClient, raw_bytes: bytes) -> None:
    file_id = await _import(auth_client, raw_bytes)
    liab_id = (await _financials(auth_client, file_id))["liabilities"][0]["id"]
    await auth_client.patch(f"{V1}/stated-liabilities/{liab_id}", json={"holder_name": "Edited"})
    activity = await auth_client.get(f"{V1}/loan-files/{file_id}/activity")
    summaries = [e["summary"] for e in activity.json()]
    assert any("stated liability" in s.lower() for s in summaries)


# --------------------------------------------------------------------------- #
# Tenant isolation + validation + auth
# --------------------------------------------------------------------------- #


async def test_tenant_isolation(
    auth_client: AsyncClient, client: AsyncClient, db, company_a: Company, raw_bytes: bytes
) -> None:
    from tests.integration import factories

    file_id = await _import(auth_client, raw_bytes)
    liab_id = (await _financials(auth_client, file_id))["liabilities"][0]["id"]

    other = await factories.make_company(db, slug="other-edit")
    other_user = await factories.make_user(db, company=other, email="x@other-edit.com")
    client.headers["Authorization"] = f"Bearer {factories.token_for(other_user)}"
    # Company B cannot edit / delete / add to company A's stated financials → 404.
    assert (
        await client.patch(f"{V1}/stated-liabilities/{liab_id}", json={"holder_name": "X"})
    ).status_code == 404
    assert (await client.delete(f"{V1}/stated-liabilities/{liab_id}")).status_code == 404
    assert (
        await client.post(
            f"{V1}/loan-files/{file_id}/stated-liabilities", json={"liability_type": "X"}
        )
    ).status_code == 404


async def test_invalid_amount_is_422(auth_client: AsyncClient, raw_bytes: bytes) -> None:
    file_id = await _import(auth_client, raw_bytes)
    liab_id = (await _financials(auth_client, file_id))["liabilities"][0]["id"]
    resp = await auth_client.patch(
        f"{V1}/stated-liabilities/{liab_id}", json={"monthly_payment": "not-a-number"}
    )
    assert resp.status_code == 422


async def test_unauthenticated_is_401(client: AsyncClient) -> None:
    resp = await client.patch(
        f"{V1}/stated-liabilities/00000000-0000-0000-0000-000000000000",
        json={"holder_name": "X"},
    )
    assert resp.status_code == 401

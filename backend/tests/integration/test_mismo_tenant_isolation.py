"""Tenant-isolation pass across EVERY new MISMO endpoint (LP-57) — security-critical.

The MISMO endpoints (upload LP-54, stated-financials read LP-55, the edit CRUD +
reused core-field PATCH LP-56) all handle sensitive financial data + PII. This is
the systematic enumeration: company A imports a file; company B is then denied on
**each** endpoint with a **404** (not 403 — anti-enumeration: B must not learn the
resource exists). SSN stays masked and no raw PII appears in any response.

Enumerated new/extended MISMO endpoints (each asserted 404 cross-company below):

  Read (LP-55):
    GET    /loan-files/{id}/stated-financials
  Stated-financials CRUD (LP-56):
    POST   /loan-files/{id}/stated-liabilities      PATCH/DELETE /stated-liabilities/{id}
    POST   /loan-files/{id}/stated-assets           PATCH/DELETE /stated-assets/{id}
    POST   /loan-files/{id}/borrowers/{bid}/stated-income     PATCH/DELETE /stated-income-items/{id}
    POST   /loan-files/{id}/borrowers/{bid}/stated-employers  PATCH/DELETE /stated-employers/{id}
  Core-field edits used by MISMO data (reused Epic-4 PATCH, extended LP-56):
    PATCH  /loan-files/{id}                 (note rate, terms, …)
    PATCH  /loan-files/{id}/property        (valuation, attachment, …)
    PATCH  /loan-files/{id}/borrowers/{bid} (DOB, citizenship, SSN replace, …)

The upload itself (POST /loan-files/import-mismo) creates a file for the caller's
OWN company — its scoping (the created file is unreachable by another tenant) is
asserted by ``test_upload_creates_file_scoped_to_caller``.
"""

from pathlib import Path

import pytest
from app.models import User
from httpx import AsyncClient
from tests.integration import factories

V1 = "/api/v1"
IMPORT_URL = f"{V1}/loan-files/import-mismo"
FIXTURE = Path(__file__).parent.parent / "fixtures" / "mismo" / "MISMO16940192.xml"


@pytest.fixture
def raw_bytes() -> bytes:
    return FIXTURE.read_bytes()


@pytest.fixture
async def imported(auth_client: AsyncClient, raw_bytes: bytes) -> dict[str, str]:
    """Company A imports the fixture; return the ids B will be denied access to."""
    resp = await auth_client.post(
        IMPORT_URL, files={"file": ("m.xml", raw_bytes, "application/xml")}
    )
    assert resp.status_code == 201
    file_id = resp.json()["loan_file"]["id"]
    fin = (await auth_client.get(f"{V1}/loan-files/{file_id}/stated-financials")).json()
    borrower = fin["borrowers"][0]
    return {
        "file_id": file_id,
        "borrower_id": borrower["id"],
        "liability_id": fin["liabilities"][0]["id"],
        "asset_id": fin["assets"][0]["id"],
        "income_id": borrower["income_items"][0]["id"],
        "employer_id": borrower["employers"][0]["id"],
    }


def _as_company_b(client: AsyncClient, user_b: User) -> AsyncClient:
    """Re-point the shared client at company B's token (A imported first)."""
    client.headers["Authorization"] = f"Bearer {factories.token_for(user_b)}"
    return client


# --------------------------------------------------------------------------- #
# Read (LP-55)
# --------------------------------------------------------------------------- #


async def test_stated_financials_read_cross_company_404(
    auth_client: AsyncClient, imported: dict[str, str], user_b: User
) -> None:
    b = _as_company_b(auth_client, user_b)
    resp = await b.get(f"{V1}/loan-files/{imported['file_id']}/stated-financials")
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# Stated liabilities (LP-56)
# --------------------------------------------------------------------------- #


async def test_liability_edits_cross_company_404(
    auth_client: AsyncClient, imported: dict[str, str], user_b: User
) -> None:
    b = _as_company_b(auth_client, user_b)
    fid, lid = imported["file_id"], imported["liability_id"]
    assert (
        await b.post(f"{V1}/loan-files/{fid}/stated-liabilities", json={"liability_type": "X"})
    ).status_code == 404
    assert (
        await b.patch(f"{V1}/stated-liabilities/{lid}", json={"holder_name": "X"})
    ).status_code == 404
    assert (await b.delete(f"{V1}/stated-liabilities/{lid}")).status_code == 404


# --------------------------------------------------------------------------- #
# Stated assets (LP-56)
# --------------------------------------------------------------------------- #


async def test_asset_edits_cross_company_404(
    auth_client: AsyncClient, imported: dict[str, str], user_b: User
) -> None:
    b = _as_company_b(auth_client, user_b)
    fid, aid = imported["file_id"], imported["asset_id"]
    assert (
        await b.post(f"{V1}/loan-files/{fid}/stated-assets", json={"asset_type": "X"})
    ).status_code == 404
    assert (await b.patch(f"{V1}/stated-assets/{aid}", json={"value": "1.00"})).status_code == 404
    assert (await b.delete(f"{V1}/stated-assets/{aid}")).status_code == 404


# --------------------------------------------------------------------------- #
# Stated income (LP-56, borrower-level)
# --------------------------------------------------------------------------- #


async def test_income_edits_cross_company_404(
    auth_client: AsyncClient, imported: dict[str, str], user_b: User
) -> None:
    b = _as_company_b(auth_client, user_b)
    fid, bid, iid = imported["file_id"], imported["borrower_id"], imported["income_id"]
    assert (
        await b.post(
            f"{V1}/loan-files/{fid}/borrowers/{bid}/stated-income",
            json={"monthly_amount": "1.00"},
        )
    ).status_code == 404
    assert (
        await b.patch(f"{V1}/stated-income-items/{iid}", json={"income_type": "X"})
    ).status_code == 404
    assert (await b.delete(f"{V1}/stated-income-items/{iid}")).status_code == 404


# --------------------------------------------------------------------------- #
# Stated employers (LP-56, borrower-level)
# --------------------------------------------------------------------------- #


async def test_employer_edits_cross_company_404(
    auth_client: AsyncClient, imported: dict[str, str], user_b: User
) -> None:
    b = _as_company_b(auth_client, user_b)
    fid, bid, eid = imported["file_id"], imported["borrower_id"], imported["employer_id"]
    assert (
        await b.post(
            f"{V1}/loan-files/{fid}/borrowers/{bid}/stated-employers",
            json={"employer_name": "X"},
        )
    ).status_code == 404
    assert (
        await b.patch(f"{V1}/stated-employers/{eid}", json={"employer_name": "X"})
    ).status_code == 404
    assert (await b.delete(f"{V1}/stated-employers/{eid}")).status_code == 404


# --------------------------------------------------------------------------- #
# Core-field edits used by MISMO data (reused Epic-4 PATCH, extended LP-56)
# --------------------------------------------------------------------------- #


async def test_core_field_edits_cross_company_404(
    auth_client: AsyncClient, imported: dict[str, str], user_b: User
) -> None:
    b = _as_company_b(auth_client, user_b)
    fid, bid = imported["file_id"], imported["borrower_id"]
    # Loan terms (note rate).
    assert (
        await b.patch(f"{V1}/loan-files/{fid}", json={"note_rate_percent": "9.99"})
    ).status_code == 404
    # Property MISMO field (valuation).
    assert (
        await b.patch(f"{V1}/loan-files/{fid}/property", json={"valuation_amount": "1.00"})
    ).status_code == 404
    # Borrower MISMO field + the SSN replace path.
    assert (
        await b.patch(f"{V1}/loan-files/{fid}/borrowers/{bid}", json={"citizenship": "USCitizen"})
    ).status_code == 404
    assert (
        await b.patch(
            f"{V1}/loan-files/{fid}/borrowers/{bid}",
            json={"ssn": "900557788"},  # pragma: allowlist secret  (synthetic)
        )
    ).status_code == 404


# --------------------------------------------------------------------------- #
# Upload scoping + PII / SSN-masking across responses
# --------------------------------------------------------------------------- #


async def test_upload_creates_file_scoped_to_caller(
    auth_client: AsyncClient, imported: dict[str, str], user_b: User
) -> None:
    # B cannot even GET the file A imported.
    b = _as_company_b(auth_client, user_b)
    assert (await b.get(f"{V1}/loan-files/{imported['file_id']}")).status_code == 404


async def test_no_raw_ssn_in_read_or_edit_responses(
    auth_client: AsyncClient, raw_bytes: bytes
) -> None:
    resp = await auth_client.post(
        IMPORT_URL, files={"file": ("m.xml", raw_bytes, "application/xml")}
    )
    file_id = resp.json()["loan_file"]["id"]
    assert "900112233" not in resp.text  # raw synthetic SSN never echoed on import

    read = await auth_client.get(f"{V1}/loan-files/{file_id}/stated-financials")
    borrower = read.json()["borrowers"][0]
    assert "900112233" not in read.text
    assert borrower["masked_ssn"] is not None and borrower["masked_ssn"].endswith("2233")
    assert "ssn" not in borrower  # no raw ssn key, only masked_ssn

    # An SSN replace echoes only the mask, never the raw value.
    patched = await auth_client.patch(
        f"{V1}/loan-files/{file_id}/borrowers/{borrower['id']}",
        json={"ssn": "900998877"},  # pragma: allowlist secret  (synthetic)
    )
    assert patched.status_code == 200
    assert "900998877" not in patched.text
    assert patched.json()["masked_ssn"].endswith("8877")

"""Integration tests for the MISMO upload endpoint (LP-54).

Real stack (httpx + DB + auth + storage temp dir), against the real fixture: the
POST runs parse → create **inline** and returns the created file + parse
warnings. Covers XML + HTML-wrapped, partial-parse (201 + warnings), graceful
safe errors (malformed / not-MISMO → 400; floor → 422), boundary validation
(no file / oversized), auth, tenant scoping, SSN masked, and no-PII logging.
"""

from pathlib import Path

import pytest
import structlog
from app.models import Company
from httpx import AsyncClient
from lxml import etree

IMPORT_URL = "/api/v1/loan-files/import-mismo"
FIXTURE = Path(__file__).parent.parent / "fixtures" / "mismo" / "MISMO16940192.xml"
NS = {"m": "http://www.mismo.org/residential/2009/schemas"}


@pytest.fixture
def raw_bytes() -> bytes:
    return FIXTURE.read_bytes()


def _upload(raw: bytes, name: str = "MISMO16940192.xml", ct: str = "application/xml"):
    return {"file": (name, raw, ct)}


# --------------------------------------------------------------------------- #
# Happy path — real fixture, inline create
# --------------------------------------------------------------------------- #


async def test_import_real_fixture_creates_file(auth_client: AsyncClient, raw_bytes: bytes) -> None:
    resp = await auth_client.post(IMPORT_URL, files=_upload(raw_bytes))
    assert resp.status_code == 201
    body = resp.json()
    assert body["warnings"] == []  # the real file is complete
    lf = body["loan_file"]
    assert lf["loan_amount"] == "1104000.00"
    assert lf["loan_program"] == "conventional" and lf["loan_purpose"] == "purchase"
    # Borrower present, SSN masked (never raw).
    borrower = lf["borrowers"][0]
    assert borrower["first_name"] == "Mahesh" and borrower["last_name"] == "Chhotala"
    assert "ssn" not in borrower
    assert borrower["masked_ssn"].endswith("2233")  # the synthetic redacted SSN, masked

    # INLINE: the file exists immediately — reachable via the normal scoped GET.
    got = await auth_client.get(f"/api/v1/loan-files/{lf['id']}")
    assert got.status_code == 200
    assert got.json()["id"] == lf["id"]


async def test_response_does_not_leak_raw_ssn(auth_client: AsyncClient, raw_bytes: bytes) -> None:
    resp = await auth_client.post(IMPORT_URL, files=_upload(raw_bytes))
    assert resp.status_code == 201
    assert "900112233" not in resp.text  # the raw (synthetic) SSN is never in the response
    assert "inbox_token" not in resp.text


async def test_html_wrapped_is_accepted(auth_client: AsyncClient, raw_bytes: bytes) -> None:
    wrapped = b"<html><body><pre>" + raw_bytes + b"</pre></body></html>"
    resp = await auth_client.post(
        IMPORT_URL, files=_upload(wrapped, name="export.html", ct="text/html")
    )
    assert resp.status_code == 201
    assert resp.json()["loan_file"]["loan_amount"] == "1104000.00"


# --------------------------------------------------------------------------- #
# Partial parse — 201 + warnings (success with warnings)
# --------------------------------------------------------------------------- #


async def test_partial_parse_returns_warnings(auth_client: AsyncClient, raw_bytes: bytes) -> None:
    # Strip the property value so the parser records a warning.
    root = etree.fromstring(raw_bytes)
    el = root.find(".//m:SUBJECT_PROPERTY//m:PropertyEstimatedValueAmount", NS)
    assert el is not None
    el.getparent().remove(el)
    partial = etree.tostring(root)

    resp = await auth_client.post(IMPORT_URL, files=_upload(partial))
    assert resp.status_code == 201  # still created (import-directly)
    body = resp.json()
    assert any("estimated value" in w for w in body["warnings"])
    assert body["loan_file"]["id"]  # the file was created despite the missing field


# --------------------------------------------------------------------------- #
# Graceful, SAFE errors (LP-46 envelope)
# --------------------------------------------------------------------------- #


async def test_malformed_is_safe_400(auth_client: AsyncClient) -> None:
    resp = await auth_client.post(IMPORT_URL, files=_upload(b"this is not xml <<<>>>"))
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["type"] == "bad_request"
    assert "MISMO" in body["error"]["message"]
    assert "Traceback" not in resp.text and "lxml" not in resp.text  # no internals leaked


async def test_valid_xml_not_mismo_is_safe_400(auth_client: AsyncClient) -> None:
    resp = await auth_client.post(IMPORT_URL, files=_upload(b"<?xml version='1.0'?><foo/>"))
    assert resp.status_code == 400
    assert resp.json()["error"]["type"] == "bad_request"


async def test_floor_no_borrower_no_loan_is_422(auth_client: AsyncClient) -> None:
    # A MISMO MESSAGE with an empty DEAL — parses, but has no borrower and no loan.
    empty = (
        b'<?xml version="1.0"?>'
        b'<MESSAGE xmlns="http://www.mismo.org/residential/2009/schemas">'
        b"<DEAL_SETS><DEAL_SET><DEALS><DEAL></DEAL></DEALS></DEAL_SET></DEAL_SETS></MESSAGE>"
    )
    resp = await auth_client.post(IMPORT_URL, files=_upload(empty))
    assert resp.status_code == 422
    assert "missing" in resp.json()["error"]["message"].lower()


# --------------------------------------------------------------------------- #
# Boundary validation + auth
# --------------------------------------------------------------------------- #


async def test_empty_file_is_422(auth_client: AsyncClient) -> None:
    resp = await auth_client.post(IMPORT_URL, files=_upload(b""))
    assert resp.status_code == 422


async def test_oversized_is_413(auth_client: AsyncClient) -> None:
    too_big = b"x" * (10 * 1024 * 1024 + 1)
    resp = await auth_client.post(IMPORT_URL, files=_upload(too_big))
    assert resp.status_code == 413


async def test_missing_file_field_is_422(auth_client: AsyncClient) -> None:
    resp = await auth_client.post(IMPORT_URL)  # no multipart file
    assert resp.status_code == 422


async def test_unauthenticated_is_401(client: AsyncClient, raw_bytes: bytes) -> None:
    resp = await client.post(IMPORT_URL, files=_upload(raw_bytes))
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# Tenant scoping + privacy
# --------------------------------------------------------------------------- #


async def test_created_file_scoped_to_user_company(
    auth_client: AsyncClient, client: AsyncClient, db, company_a: Company, raw_bytes: bytes
) -> None:
    from tests.integration import factories

    resp = await auth_client.post(IMPORT_URL, files=_upload(raw_bytes))
    file_id = resp.json()["loan_file"]["id"]

    # A second company's user cannot reach the imported file → 404.
    other = await factories.make_company(db, slug="other-co")
    other_user = await factories.make_user(db, company=other, email="x@other-co.com")
    client.headers["Authorization"] = f"Bearer {factories.token_for(other_user)}"
    assert (await client.get(f"/api/v1/loan-files/{file_id}")).status_code == 404


async def test_no_pii_logged(auth_client: AsyncClient, raw_bytes: bytes) -> None:
    with structlog.testing.capture_logs() as logs:
        resp = await auth_client.post(IMPORT_URL, files=_upload(raw_bytes))
    assert resp.status_code == 201
    blob = repr(logs)
    assert "900112233" not in blob  # SSN
    assert "Mahesh" not in blob and "Chhotala" not in blob  # names
    assert "1104000" not in blob  # amounts
    assert any(e.get("event") == "mismo_import_endpoint" for e in logs)  # metadata present

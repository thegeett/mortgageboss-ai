"""Full-flow MISMO integration tests (LP-57) — the whole journey, real stack.

Exercises the complete MISMO feature end-to-end through real HTTP + DB + parsing
+ storage (LP-45 fixtures): upload (LP-54) → parse (LP-51) → create + store
(LP-52/53) → read (LP-55) → edit (LP-56), in one continuous journey. Plus the
HTML-wrapped path, the graceful-error path (malformed → LP-46 envelope, not 500),
and the parser-hardening variants (FHA, multi-borrower) importing correctly.

Complements ``test_mismo_import.py`` (endpoint-focused unit-of-API cases) by
asserting the *chained* journey and the synthetic-variant imports.
"""

from pathlib import Path

import pytest
from httpx import AsyncClient
from tests.mismo import synthetic

IMPORT_URL = "/api/v1/loan-files/import-mismo"
FIXTURE = Path(__file__).parent.parent / "fixtures" / "mismo" / "MISMO16940192.xml"


@pytest.fixture
def raw_bytes() -> bytes:
    return FIXTURE.read_bytes()


def _upload(raw: bytes, name: str = "m.xml", ct: str = "application/xml") -> dict:
    return {"file": (name, raw, ct)}


async def _import(client: AsyncClient, raw: bytes, **kw: str) -> dict:
    resp = await client.post(IMPORT_URL, files=_upload(raw, **kw))
    assert resp.status_code == 201, resp.text
    return resp.json()


# --------------------------------------------------------------------------- #
# The full journey: upload → parse → create → store → read → edit
# --------------------------------------------------------------------------- #


async def test_full_journey_upload_to_edit(auth_client: AsyncClient, raw_bytes: bytes) -> None:
    # 1) UPLOAD → a populated file is created inline (parse + create in one call).
    body = await _import(auth_client, raw_bytes)
    assert body["warnings"] == []
    lf = body["loan_file"]
    file_id = lf["id"]
    assert lf["loan_amount"] == "1104000.00"
    assert lf["loan_program"] == "conventional" and lf["loan_purpose"] == "purchase"
    assert lf["borrowers"][0]["last_name"] == "Chhotala"

    # 2) STORED + READABLE — the stated financials are persisted and read back (LP-55).
    fin = (await auth_client.get(f"/api/v1/loan-files/{file_id}/stated-financials")).json()
    borrower = fin["borrowers"][0]
    assert borrower["full_name"] == "Mahesh Chhotala"
    assert len(borrower["income_items"]) == 2
    assert len(borrower["employers"]) == 3
    assert len(fin["liabilities"]) == 10 and len(fin["assets"]) == 9
    assert fin["loan_terms"]["note_rate_percent"] == "6.8750"

    liab_id = fin["liabilities"][0]["id"]
    liab_count = len(fin["liabilities"])

    # 3a) EDIT — update a stated value (LP-56) → persists.
    r = await auth_client.patch(
        f"/api/v1/stated-liabilities/{liab_id}", json={"monthly_payment": "1500.00"}
    )
    assert r.status_code == 200 and r.json()["monthly_payment"] == "1500.00"

    # 3b) ADD a stated row → the read reflects it.
    add = await auth_client.post(
        f"/api/v1/loan-files/{file_id}/stated-liabilities",
        json={"liability_type": "Revolving", "monthly_payment": "75.00"},
    )
    assert add.status_code == 201
    new_id = add.json()["id"]

    # 3c) REMOVE a stated row (soft delete) → gone from the read.
    assert (await auth_client.delete(f"/api/v1/stated-liabilities/{new_id}")).status_code == 204

    # 3d) EDIT a core field via the reused Epic-4 PATCH (LP-56 extended schema).
    r = await auth_client.patch(
        f"/api/v1/loan-files/{file_id}", json={"note_rate_percent": "7.2500"}
    )
    assert r.status_code == 200

    # The read reflects every edit (value changed; net rows back to the original;
    # core field updated).
    fin2 = (await auth_client.get(f"/api/v1/loan-files/{file_id}/stated-financials")).json()
    assert any(
        x["id"] == liab_id and x["monthly_payment"] == "1500.00" for x in fin2["liabilities"]
    )
    assert len(fin2["liabilities"]) == liab_count
    assert all(x["id"] != new_id for x in fin2["liabilities"])
    assert fin2["loan_terms"]["note_rate_percent"] == "7.2500"

    # 4) An activity was logged for the edits + the import (audit trail).
    activity = (await auth_client.get(f"/api/v1/loan-files/{file_id}/activity")).json()
    summaries = [a["summary"] for a in activity]
    assert any("MISMO" in s for s in summaries)  # the import itself
    assert any("stated liability" in s.lower() for s in summaries)  # an edit


# --------------------------------------------------------------------------- #
# HTML-wrapped upload → same journey result
# --------------------------------------------------------------------------- #


async def test_html_wrapped_full_result(auth_client: AsyncClient, raw_bytes: bytes) -> None:
    body = await _import(
        auth_client, synthetic.html_wrapped(raw_bytes), name="export.html", ct="text/html"
    )
    file_id = body["loan_file"]["id"]
    fin = (await auth_client.get(f"/api/v1/loan-files/{file_id}/stated-financials")).json()
    assert fin["borrowers"][0]["full_name"] == "Mahesh Chhotala"
    assert fin["mismo_import"]["source_format"] == "html"
    assert len(fin["liabilities"]) == 10


# --------------------------------------------------------------------------- #
# Graceful error — malformed / non-MISMO → LP-46 envelope, never a 500
# --------------------------------------------------------------------------- #


async def test_malformed_upload_is_graceful(auth_client: AsyncClient) -> None:
    resp = await auth_client.post(IMPORT_URL, files=_upload(b"not xml <<<"))
    assert resp.status_code == 400  # not 500
    body = resp.json()
    assert body["error"]["type"] == "bad_request"
    assert "Traceback" not in resp.text and "lxml" not in resp.text  # no internals leaked


async def test_valid_xml_not_mismo_is_graceful(auth_client: AsyncClient) -> None:
    resp = await auth_client.post(IMPORT_URL, files=_upload(b"<?xml version='1.0'?><foo/>"))
    assert resp.status_code == 400
    assert resp.json()["error"]["type"] == "bad_request"


# --------------------------------------------------------------------------- #
# Parser-hardening variants import correctly (FHA + multi-borrower) — real stack
# --------------------------------------------------------------------------- #


async def test_fha_variant_imports(auth_client: AsyncClient, raw_bytes: bytes) -> None:
    body = await _import(auth_client, synthetic.fha_variant(raw_bytes))
    assert body["loan_file"]["loan_program"] == "fha"


async def test_multi_borrower_variant_imports(auth_client: AsyncClient, raw_bytes: bytes) -> None:
    body = await _import(auth_client, synthetic.multi_borrower_variant(raw_bytes))
    file_id = body["loan_file"]["id"]
    fin = (await auth_client.get(f"/api/v1/loan-files/{file_id}/stated-financials")).json()
    assert len(fin["borrowers"]) == 2
    names = {b["full_name"] for b in fin["borrowers"]}
    assert names == {"Mahesh Chhotala", "Asha Patel"}
    # Each borrower kept their own income (no cross-attribution through the import).
    by_name = {b["full_name"]: b for b in fin["borrowers"]}
    assert {i["monthly_amount"] for i in by_name["Asha Patel"]["income_items"]} == {"3333.00"}
    assert {i["monthly_amount"] for i in by_name["Mahesh Chhotala"]["income_items"]} == {
        "7000.00",
        "9400.00",
    }


async def test_zero_income_variant_imports_with_warning(
    auth_client: AsyncClient, raw_bytes: bytes
) -> None:
    body = await _import(auth_client, synthetic.zero_income_variant(raw_bytes))
    # Still created (import-directly), with the non-blocking needed-now warning.
    assert any("no income" in w.lower() for w in body["warnings"])
    file_id = body["loan_file"]["id"]
    fin = (await auth_client.get(f"/api/v1/loan-files/{file_id}/stated-financials")).json()
    assert fin["borrowers"][0]["income_items"] == []

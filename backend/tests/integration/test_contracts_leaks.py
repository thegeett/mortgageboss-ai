"""Contract + leak checks (LP-45).

Sensitive fields must NEVER appear in any response: ``storage_path`` (documents),
``inbox_token`` (loan files), raw ``ssn`` (borrowers — ``masked_ssn`` only), and
a full (unmasked) account number (bank-statement extraction — only
``account_number_masked``). Key responses also validate against their Pydantic
response models, and create/get/delete status codes are confirmed.
"""

from app.models import Company, User
from app.models.document import DocumentStatus
from app.schemas.document import DocumentDetailResponse
from app.schemas.loan_file import LoanFileDetail
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration import factories

V1 = "/api/v1"


async def test_loan_file_detail_hides_inbox_token_and_validates_schema(
    auth_client: AsyncClient, db: AsyncSession, company_a: Company
) -> None:
    lf = await factories.make_loan_file(db, company=company_a)
    resp = await auth_client.get(f"{V1}/loan-files/{lf.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert "inbox_token" not in body
    # Validates against the declared response contract.
    LoanFileDetail.model_validate(body)


async def test_borrower_view_masks_ssn(
    auth_client: AsyncClient, db: AsyncSession, company_a: Company
) -> None:
    lf = await factories.make_loan_file(db, company=company_a)
    await factories.make_borrower(db, loan_file=lf, ssn="987-65-4321")
    resp = await auth_client.get(f"{V1}/loan-files/{lf.id}/borrowers")
    body = resp.json()[0]
    assert "ssn" not in body  # raw/encrypted SSN never serialized
    assert body["masked_ssn"].endswith("4321")
    assert "4321" in body["masked_ssn"] and body["masked_ssn"].startswith("*")


async def test_document_detail_hides_storage_path_and_masks_account_number(
    auth_client: AsyncClient, db: AsyncSession, company_a: Company, user_a: User
) -> None:
    lf = await factories.make_loan_file(db, company=company_a)
    doc = await factories.make_document(
        db,
        loan_file=lf,
        company=company_a,
        document_type="bank_statement",
        status=DocumentStatus.COMPLETED,
        uploaded_by=user_a,
    )
    await factories.make_extraction(
        db,
        document=doc,
        data={
            "account_number_masked": {"value": "****6789", "source": None},
            "ending_balance": {"value": "5230.18", "source": None},
        },
    )
    resp = await auth_client.get(f"{V1}/documents/{doc.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert "storage_path" not in body
    # The extraction carries only the masked account number, never a raw one.
    data = body["current_extraction"]["extracted_data"]
    assert "account_number_masked" in data
    assert "account_number" not in data
    # Schema-validates.
    DocumentDetailResponse.model_validate(body)


async def test_status_codes_create_get_delete(
    auth_client: AsyncClient, db: AsyncSession, company_a: Company
) -> None:
    # 201 on create, 200 on get, 204 on delete, 404 after.
    created = await auth_client.post(f"{V1}/loan-files", json={})
    assert created.status_code == 201
    file_id = created.json()["id"]
    assert (await auth_client.get(f"{V1}/loan-files/{file_id}")).status_code == 200
    assert (await auth_client.delete(f"{V1}/loan-files/{file_id}")).status_code == 204
    assert (await auth_client.get(f"{V1}/loan-files/{file_id}")).status_code == 404


async def test_validation_error_is_422(
    auth_client: AsyncClient, db: AsyncSession, company_a: Company, user_a: User
) -> None:
    lf = await factories.make_loan_file(db, company=company_a)
    doc = await factories.make_document(db, loan_file=lf, company=company_a, uploaded_by=user_a)
    # Empty document_type violates the override schema (min_length=1) → 422.
    resp = await auth_client.patch(f"{V1}/documents/{doc.id}", json={"document_type": ""})
    assert resp.status_code == 422

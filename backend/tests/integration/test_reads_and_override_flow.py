"""Sub-reads + override flow (LP-45).

The loan-file sub-reads (needs, activity, borrowers, property) and the company
lender list return real, scoped data through the live stack. The override flow
(PATCH /documents/{id}) sets the type, enqueues re-extraction (``.delay``
asserted), and writes a ``DOCUMENT_TYPE_OVERRIDDEN`` activity that the activity
sub-read then surfaces.
"""

from app.models import Company, User
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration import factories
from tests.integration.conftest import Dispatch


async def test_needs_subread_returns_scoped_items(
    auth_client: AsyncClient, db: AsyncSession, company_a: Company
) -> None:
    lf = await factories.make_loan_file(db, company=company_a)
    await factories.make_needs_item(db, loan_file=lf, title="Most recent pay stub")
    resp = await auth_client.get(f"/api/v1/loan-files/{lf.id}/needs")
    assert resp.status_code == 200
    titles = [i["title"] for i in resp.json()]
    assert "Most recent pay stub" in titles


async def test_activity_subread_returns_scoped_events(
    auth_client: AsyncClient, db: AsyncSession, company_a: Company
) -> None:
    # A file created via the API gets a FILE_CREATED activity (LP-30).
    created = await auth_client.post("/api/v1/loan-files", json={})
    file_id = created.json()["id"]
    resp = await auth_client.get(f"/api/v1/loan-files/{file_id}/activity")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


async def test_borrowers_and_property_subreads(
    auth_client: AsyncClient, db: AsyncSession, company_a: Company
) -> None:
    lf = await factories.make_loan_file(db, company=company_a)
    await factories.make_borrower(db, loan_file=lf)
    await factories.make_property(db, loan_file=lf)

    borrowers = await auth_client.get(f"/api/v1/loan-files/{lf.id}/borrowers")
    assert borrowers.status_code == 200
    assert len(borrowers.json()) == 1
    # SSN is masked, never raw, in the borrower view.
    assert "ssn" not in borrowers.json()[0]
    assert borrowers.json()[0]["masked_ssn"].endswith("6789")

    prop = await auth_client.get(f"/api/v1/loan-files/{lf.id}/property")
    assert prop.status_code == 200
    assert prop.json()["city"] == "Springfield"


async def test_lenders_list_is_company_scoped(
    auth_client: AsyncClient, db: AsyncSession, company_a: Company
) -> None:
    await factories.make_lender(db, company=company_a, name="Acme Bank")
    resp = await auth_client.get("/api/v1/lenders")
    assert resp.status_code == 200
    assert any(lender["name"] == "Acme Bank" for lender in resp.json())


async def test_override_flow_updates_type_enqueues_and_audits(
    auth_client: AsyncClient,
    db: AsyncSession,
    company_a: Company,
    user_a: User,
    mock_dispatch: Dispatch,
) -> None:
    lf = await factories.make_loan_file(db, company=company_a)
    from app.models.document import DocumentStatus

    doc = await factories.make_document(
        db,
        loan_file=lf,
        company=company_a,
        document_type="pay_stub",
        status=DocumentStatus.NEEDS_REVIEW,
        uploaded_by=user_a,
    )

    resp = await auth_client.patch(
        f"/api/v1/documents/{doc.id}", json={"document_type": "bank_statement"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["document_type"] == "bank_statement"
    assert body["category"] == "assets"  # re-derived
    assert body["classification_confidence"] == 1.0  # human-overridden
    # Re-extraction enqueued exactly once (no worker run).
    mock_dispatch.reprocess.assert_called_once_with(str(doc.id))

    # The override is audited and visible via the activity sub-read.
    activity = await auth_client.get(f"/api/v1/loan-files/{lf.id}/activity")
    assert any(e["activity_type"] == "document_type_overridden" for e in activity.json())


async def test_override_survives_enqueue_failure(
    auth_client: AsyncClient,
    db: AsyncSession,
    company_a: Company,
    user_a: User,
    mock_dispatch: Dispatch,
) -> None:
    """A broker hiccup must NOT lose the override — the type change is committed first."""
    lf = await factories.make_loan_file(db, company=company_a)
    doc = await factories.make_document(
        db, loan_file=lf, company=company_a, document_type="pay_stub", uploaded_by=user_a
    )
    mock_dispatch.reprocess.side_effect = RuntimeError("broker down")
    resp = await auth_client.patch(f"/api/v1/documents/{doc.id}", json={"document_type": "w2"})
    assert resp.status_code == 200
    assert resp.json()["document_type"] == "w2"

"""Validation aid API (LP-89) — admin-gated, tenant-scoped, honest grounded_starter default.

Real-stack: a company admin sees the inventory of every grounded-starter rule + calculator
methodology (defaulting to grounded_starter — nothing validated); records a verdict per item
(validated / corrected / add-new); the verdict persists + flips the item's validation_status;
a non-admin processor is forbidden (403); verdicts are company-scoped (another company's admin
sees their own grounded_starter inventory, not the first company's verdicts).
"""

from app.models import Company
from app.models.user import UserRole
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration import factories

INV = "/api/v1/admin/validation/inventory"
VERDICTS = "/api/v1/admin/validation/verdicts"


async def _admin(
    client: AsyncClient, db: AsyncSession, company: Company, email: str
) -> AsyncClient:
    admin = await factories.make_user(db, company=company, email=email, role=UserRole.ADMIN)
    client.headers["Authorization"] = f"Bearer {factories.token_for(admin)}"
    return client


async def test_inventory_lists_every_starter_item_defaulting_grounded(
    client: AsyncClient, db: AsyncSession, company_a: Company
) -> None:
    admin = await _admin(client, db, company_a, "admin@a.com")
    await db.commit()
    res = await admin.get(INV)
    assert res.status_code == 200
    body = res.json()
    # The full grounded-starter inventory (rules + calculator methodologies).
    assert body["total"] > 100
    # HONEST: nothing is validated until the session records it — all grounded_starter.
    assert body["grounded_starter"] == body["total"]
    assert body["validated"] == 0
    # Each item carries the citation + value + the starter marker.
    dti = next(i for i in body["items"] if i["item_id"] == "conv.dti.back_end_max_manual")
    assert dti["citation"] and dti["value"] and dti["starter"] is True
    assert dti["validation_status"] == "grounded_starter"
    # The calculator methodologies are in the inventory too.
    assert any(i["item_id"] == "calc.pmi_rate" for i in body["items"])


async def test_record_a_corrected_verdict_flips_the_status(
    client: AsyncClient, db: AsyncSession, company_a: Company
) -> None:
    admin = await _admin(client, db, company_a, "admin@a.com")
    await db.commit()
    # Priya says the manual DTI ceiling should be 43, not 45.
    post = await admin.post(
        VERDICTS,
        json={
            "item_id": "conv.dti.back_end_max_manual",
            "kind": "corrected",
            "corrected_value": "43",
            "note": "Priya: our manual ceiling is 43% without strong factors",
        },
    )
    assert post.status_code == 200
    assert post.json()["corrected_value"] == "43"

    inv = (await admin.get(INV)).json()
    item = next(i for i in inv["items"] if i["item_id"] == "conv.dti.back_end_max_manual")
    assert item["validation_status"] == "corrected"
    assert item["verdict"]["corrected_value"] == "43"
    assert inv["corrected"] == 1
    assert inv["grounded_starter"] == inv["total"] - 1

    # Re-recording the same item updates (upsert, not duplicate).
    await admin.post(
        VERDICTS, json={"item_id": "conv.dti.back_end_max_manual", "kind": "validated"}
    )
    inv2 = (await admin.get(INV)).json()
    item2 = next(i for i in inv2["items"] if i["item_id"] == "conv.dti.back_end_max_manual")
    assert item2["validation_status"] == "validated"
    assert inv2["validated"] == 1 and inv2["corrected"] == 0


async def test_add_new_proposal_is_captured(
    client: AsyncClient, db: AsyncSession, company_a: Company
) -> None:
    admin = await _admin(client, db, company_a, "admin@a.com")
    await db.commit()
    res = await admin.post(
        VERDICTS,
        json={
            "kind": "add_new",
            "title": "Gift of equity disclosure",
            "note": "Priya: we always need a gift-of-equity letter on family sales",
        },
    )
    assert res.status_code == 200
    inv = (await admin.get(INV)).json()
    assert any(a["title"] == "Gift of equity disclosure" for a in inv["additions"])


async def test_processor_is_forbidden(
    auth_client: AsyncClient, db: AsyncSession, company_a: Company
) -> None:
    await db.commit()
    res = await auth_client.get(INV)  # auth_client is the PROCESSOR
    assert res.status_code == 403


async def test_verdicts_are_company_scoped(
    client: AsyncClient, db: AsyncSession, company_a: Company, company_b: Company
) -> None:
    admin_a = await _admin(client, db, company_a, "admin@a.com")
    await db.commit()
    await admin_a.post(
        VERDICTS, json={"item_id": "conv.dti.back_end_max_manual", "kind": "validated"}
    )

    # Company B's admin sees their OWN (all grounded_starter) inventory, not A's verdict.
    admin_b = await _admin(client, db, company_b, "admin@b.com")
    await db.commit()
    inv_b = (await admin_b.get(INV)).json()
    assert inv_b["validated"] == 0
    item = next(i for i in inv_b["items"] if i["item_id"] == "conv.dti.back_end_max_manual")
    assert item["validation_status"] == "grounded_starter"

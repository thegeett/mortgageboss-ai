"""Overlay admin API (LP-87) — admin-gated, tenant-scoped, reason-required, audited, legible.

Real-stack: a company admin can VIEW + EDIT a lender's overlay (each override's effective
threshold made legible); a non-admin processor is forbidden (403); a cross-company lender is
404; a change without a reason is rejected (422); and an unknown rule_id is rejected. The
edit's from→to values are recorded in the overlay's audit trail (LP-80.5 posture).
"""

from decimal import Decimal

from app.models import Company
from app.models.user import UserRole
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration import factories


async def _admin_client(client: AsyncClient, db: AsyncSession, company: Company) -> AsyncClient:
    admin = await factories.make_user(db, company=company, email="admin@a.com", role=UserRole.ADMIN)
    client.headers["Authorization"] = f"Bearer {factories.token_for(admin)}"
    return client


async def test_admin_views_edits_and_audits_an_overlay(
    client: AsyncClient, db: AsyncSession, company_a: Company
) -> None:
    lender = await factories.make_lender(db, company=company_a, name="UWM")
    await db.commit()
    admin = await _admin_client(client, db, company_a)
    await db.commit()

    # Edit: tighten the Conventional back-end DTI cap to 45%, with a required reason.
    put = await admin.put(
        f"/api/v1/admin/lenders/{lender.id}/overlay",
        json={
            "overrides": [
                {"rule_id": "conv.dti.back_end_max", "value": "45", "reason": "UWM overlay"}
            ],
            "reason": "Tighten the Conventional DTI cap to 45%",
        },
    )
    assert put.status_code == 200, put.text
    body = put.json()
    override = next(o for o in body["overrides"] if o["rule_id"] == "conv.dti.back_end_max")
    # Effect-legible: the investor base (50) → the lender effective (45).
    assert Decimal(override["effective_value"]) == Decimal("45")
    assert Decimal(override["base_value"]) == Decimal("50")
    # Audited: one entry, the from→to change recorded.
    assert len(body["audit"]) == 1
    assert body["audit"][0]["reason"] == "Tighten the Conventional DTI cap to 45%"
    assert body["audit"][0]["changes"][0]["to"] == "45"

    # And the GET reflects the persisted overlay.
    got = await admin.get(f"/api/v1/admin/lenders/{lender.id}/overlay")
    assert got.status_code == 200
    assert Decimal(got.json()["overrides"][0]["effective_value"]) == Decimal("45")


async def test_processor_is_forbidden(
    auth_client: AsyncClient, db: AsyncSession, company_a: Company
) -> None:
    lender = await factories.make_lender(db, company=company_a, name="UWM")
    await db.commit()
    # auth_client is the PROCESSOR (user_a) — admin-only surface → 403.
    res = await auth_client.get(f"/api/v1/admin/lenders/{lender.id}/overlay")
    assert res.status_code == 403


async def test_cross_company_lender_is_404(
    client: AsyncClient, db: AsyncSession, company_a: Company, company_b: Company
) -> None:
    other_lender = await factories.make_lender(db, company=company_b, name="OtherBank")
    await db.commit()
    admin = await _admin_client(client, db, company_a)
    await db.commit()
    res = await admin.get(f"/api/v1/admin/lenders/{other_lender.id}/overlay")
    assert res.status_code == 404  # company A's admin cannot reach company B's lender


async def test_reason_is_required(
    client: AsyncClient, db: AsyncSession, company_a: Company
) -> None:
    lender = await factories.make_lender(db, company=company_a, name="UWM")
    await db.commit()
    admin = await _admin_client(client, db, company_a)
    await db.commit()
    res = await admin.put(
        f"/api/v1/admin/lenders/{lender.id}/overlay",
        json={"overrides": [], "reason": ""},  # empty reason → rejected
    )
    assert res.status_code == 422


async def test_unknown_rule_id_is_rejected(
    client: AsyncClient, db: AsyncSession, company_a: Company
) -> None:
    lender = await factories.make_lender(db, company=company_a, name="UWM")
    await db.commit()
    admin = await _admin_client(client, db, company_a)
    await db.commit()
    res = await admin.put(
        f"/api/v1/admin/lenders/{lender.id}/overlay",
        json={
            "overrides": [{"rule_id": "conv.not.a.rule", "value": "1", "reason": "x"}],
            "reason": "bad",
        },
    )
    assert res.status_code == 422

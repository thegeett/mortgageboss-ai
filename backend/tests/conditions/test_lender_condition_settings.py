"""LP-925 (S3-11): the lender's condition settings — entered once, used on every file.

The file's lender is UWM (`canonical_lender_key = uwm`), so its defaults are decision 1's: the lender
orders the final inspection, the upload cutoff is 8:00 PM Eastern, the upload asks for a note. The
mortgagee clause is filled from the approval letter until an admin saves one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from app.models.lender import Lender
from app.models.lender_condition_code import LenderCodeStatus, LenderConditionCode
from app.models.loan_file import LoanFile
from app.services.condition_plan import lender_condition_settings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.test_condition_reading import _file_with_round

CLAUSE = (
    "United Wholesale Mortgage ISAOA, ATIMA PO BOX 202175 FLORENCE, SC 29502 Phone: (800) 981-8898"
)


async def _clients(
    db: AsyncSession, loan_file: LoanFile
) -> tuple[Any, dict[str, str], dict[str, str]]:
    """One client, and an admin's and a processor's headers in the file's company."""
    from app.core.database import get_db
    from app.core.jwt import create_access_token
    from app.core.security import hash_password
    from app.main import app
    from app.models import User, UserRole
    from httpx import ASGITransport, AsyncClient

    tokens: dict[str, str] = {}
    for role in (UserRole.ADMIN, UserRole.PROCESSOR):
        user = User(
            company_id=loan_file.company_id,
            email=f"{role.value}-{uuid4().hex[:6]}@example.com",
            hashed_password=hash_password("irrelevant"),
            first_name="Test",
            last_name=role.value,
            role=role,
            is_active=True,
        )
        db.add(user)
        await db.flush()
        tokens[role.value] = create_access_token(user.id)

    async def _db() -> Any:
        yield db

    app.dependency_overrides[get_db] = _db
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    return (
        client,
        {"Authorization": f"Bearer {tokens['admin']}"},
        {"Authorization": f"Bearer {tokens['processor']}"},
    )


@pytest.fixture(autouse=True)
def _drop_db_override() -> Any:
    from app.core.database import get_db
    from app.main import app

    yield
    app.dependency_overrides.pop(get_db, None)


async def _unmapped(db: AsyncSession, lender: Lender) -> None:
    now = datetime.now(UTC)
    for code, label in (
        ("7812", "Provide signed and dated letter of explanation for the credit inquiry"),
        ("6521", "Provide most recent paystub covering 30 days with year-to-date earnings."),
    ):
        db.add(
            LenderConditionCode(
                lender_id=lender.id,
                code=code,
                label=label,
                status=LenderCodeStatus.OBSERVED_UNMAPPED,
                times_seen=1,
                first_seen_at=now,
                last_seen_at=now,
            )
        )
    await db.flush()


async def test_the_settings_are_s3_11_and_save_for_every_file(db_session: AsyncSession) -> None:
    loan_file, _ = await _file_with_round(db_session)
    lender = await db_session.get(Lender, loan_file.lender_id)
    assert lender is not None
    client, admin, processor = await _clients(db_session, loan_file)
    url = f"/api/v1/lenders/{lender.id}/condition-settings"
    async with client:
        shown = (await client.get(url, headers=processor)).json()
        assert shown == {
            "mortgagee_clause": CLAUSE,
            "clause_from_letter": True,
            "upload_cutoff": "20:00",
            "upload_cutoff_tz": "America/New_York",
            "upload_fields": ["note"],
            "lender_orders_final_inspection": True,
            "lender_verifies_business_existence": False,
            "lender_orders_title_insurance_payoffs": False,
            "new_files_lender_processing": False,
        }
        body = {
            **shown,
            "upload_fields": ["note", "name_of_source", "date_verified"],
            "lender_verifies_business_existence": True,
        }
        body.pop("clause_from_letter")
        # Only an admin may save.
        assert (await client.put(url, json=body, headers=processor)).status_code == 403
        saved = await client.put(url, json=body, headers=admin)
        assert saved.status_code == 200, saved.text
        assert saved.json()["clause_from_letter"] is False
        refused = await client.put(
            url, json={**body, "upload_fields": ["date_verified"]}, headers=admin
        )
        assert refused.status_code == 422
    # What the plan, drafts and package read is what she saved.
    await db_session.refresh(lender)
    settings = lender_condition_settings(lender)
    assert settings.upload_fields == ("note", "name_of_source", "date_verified")
    assert settings.lender_verifies_business_existence is True  # LP-945
    assert lender.mortgagee_clause == CLAUSE


async def test_codes_to_review_are_mapped_by_an_admin(db_session: AsyncSession) -> None:
    loan_file, _ = await _file_with_round(db_session)
    lender = await db_session.get(Lender, loan_file.lender_id)
    assert lender is not None
    await _unmapped(db_session, lender)
    client, admin, processor = await _clients(db_session, loan_file)
    base = f"/api/v1/lenders/{lender.id}"
    async with client:
        listed = (await client.get(f"{base}/codes-to-review", headers=processor)).json()
        assert {r["code"] for r in listed} == {"7812", "6521"}
        assert all(r["canonical_type_id"] is None for r in listed)
        types = (await client.get("/api/v1/lenders/library-types", headers=processor)).json()
        cr05 = next(t for t in types if t["id"] == "CR-05")
        assert cr05["label"].startswith("CR-05 ")
        assert (
            await client.put(
                f"{base}/codes/7812", json={"canonical_type_id": "CR-05"}, headers=processor
            )
        ).status_code == 403
        mapped = await client.put(
            f"{base}/codes/7812", json={"canonical_type_id": "CR-05"}, headers=admin
        )
        assert mapped.status_code == 200, mapped.text
        assert {r["code"]: r["canonical_type_id"] for r in mapped.json()} == {
            "7812": "CR-05",
            "6521": None,
        }
        bad = await client.put(
            f"{base}/codes/6521", json={"canonical_type_id": "ZZ-99"}, headers=admin
        )
        assert bad.status_code == 422
        seeded = await client.put(
            f"{base}/codes/6637", json={"canonical_type_id": "AS-04"}, headers=admin
        )
        assert seeded.status_code == 422  # a shipped code is not one waiting for review
    row = (
        await db_session.execute(
            select(LenderConditionCode).where(
                LenderConditionCode.lender_id == lender.id, LenderConditionCode.code == "7812"
            )
        )
    ).scalar_one()
    assert (row.status, row.canonical_type_id) == (LenderCodeStatus.MAPPED, "CR-05")


async def test_another_companys_lender_is_not_found(db_session: AsyncSession) -> None:
    loan_file, _ = await _file_with_round(db_session)
    other_file, _ = await _file_with_round(db_session)
    client, admin, _ = await _clients(db_session, other_file)
    async with client:
        response = await client.get(
            f"/api/v1/lenders/{loan_file.lender_id}/condition-settings", headers=admin
        )
        assert response.status_code == 404

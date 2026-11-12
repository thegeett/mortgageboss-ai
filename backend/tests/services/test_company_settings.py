"""`update_company_settings` re-reads the row before writing (LP-MB-Admin-02 review, finding 4).

The company is loaded at the start of the request and the whole JSON column is written back, so a
stale copy would overwrite whatever another writer stored meanwhile.
"""

from uuid import uuid4

from app.api.dependencies import get_current_actor
from app.models import Company, UserRole
from app.schemas.company import CompanySettingsUpdate
from app.services.company_settings import update_company_settings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.user_factory import make_user


async def test_a_key_written_after_the_request_loaded_the_company_survives(
    db_session: AsyncSession,
) -> None:
    company = Company(name="Acme", slug=f"acme-{uuid4().hex[:8]}", settings={})
    db_session.add(company)
    await db_session.flush()
    admin = make_user(
        company_id=company.id,
        email=f"a-{uuid4().hex[:8]}@acme.com",
        hashed_password="x",  # pragma: allowlist secret
        first_name="A",
        last_name="D",
        roles=[UserRole.ADMIN],
    )
    db_session.add(admin)
    await db_session.flush()
    await db_session.refresh(admin, attribute_names=["company"])
    actor = get_current_actor(admin)
    # Another writer, after this request loaded the company: the session's copy is now stale.
    await db_session.execute(
        text('UPDATE companies SET settings = \'{"other_feature": "x"}\' WHERE id = :id'),
        {"id": company.id},
    )

    await update_company_settings(
        db_session, actor, CompanySettingsUpdate(processors_can_create_loans=False)
    )

    stored = await db_session.scalar(
        text("SELECT settings FROM companies WHERE id = :id"), {"id": company.id}
    )
    assert stored["other_feature"] == "x"
    assert stored["processors_can_create_loans"] is False

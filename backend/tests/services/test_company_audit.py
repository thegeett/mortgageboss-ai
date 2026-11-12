"""`log_company_action` (LP-MB-Admin-01): one row, flushed, never committed."""

from uuid import uuid4

import pytest
from app.models import Company, UserRole
from app.services.activity_log import field_changes
from app.services.company_audit import AuditAction, log_company_action
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.user_factory import make_user


async def test_writes_one_flushed_row_and_does_not_commit(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    company = Company(name="Acme", slug=f"acme-{uuid4().hex[:8]}")
    db_session.add(company)
    await db_session.flush()
    admin = make_user(
        company_id=company.id,
        email=f"admin-{uuid4().hex[:8]}@acme.com",
        hashed_password="x",  # pragma: allowlist secret
        first_name="Ada",
        last_name="Admin",
        roles=[UserRole.ADMIN],
    )
    db_session.add(admin)
    await db_session.flush()

    commits: list[None] = []

    async def _commit() -> None:
        commits.append(None)

    monkeypatch.setattr(db_session, "commit", _commit)
    changes = field_changes({"owner_user_id": None}, {"owner_user_id": admin.id})

    entry = await log_company_action(
        db_session,
        company_id=company.id,
        actor_user_id=admin.id,
        action=AuditAction.OWNER_TRANSFERRED,
        target_type="company",
        target_id=company.id,
        summary="Owner transferred",
        detail={"changes": changes},
    )

    assert commits == []
    # Flushed: the row is in the database inside this transaction, read with SQL, not the session.
    rows = (
        await db_session.execute(
            text(
                "SELECT id, actor_user_id, action, target_type, target_id, detail "
                "FROM company_audit_log WHERE company_id = :id"
            ),
            {"id": company.id},
        )
    ).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.id == entry.id
    assert (row.actor_user_id, row.action, row.target_type, row.target_id) == (
        admin.id,
        "owner_transferred",
        "company",
        company.id,
    )
    assert row.detail == {
        "changes": [{"field": "owner_user_id", "from": None, "to": str(admin.id)}]
    }

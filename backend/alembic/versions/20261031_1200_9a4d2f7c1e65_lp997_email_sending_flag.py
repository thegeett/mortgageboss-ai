"""LP-997 — `company_mail_domains.sending_enabled`: real email from the app, per company.

Off by default, so every existing company keeps "Mark as sent" until it is switched on with
`app.scripts.set_email_sending`. The readonly view exposes it: it is a setting, not an identifier.

Revision ID: 9a4d2f7c1e65
Revises: 4b7e2c9d1a63
Create Date: 2026-10-31 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9a4d2f7c1e65"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "4b7e2c9d1a63"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GRANT = """
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
            EXECUTE 'GRANT SELECT ON readonly.company_mail_domains TO mbai_readonly';
        END IF;
    END
    $$;
    """


def upgrade() -> None:
    op.add_column(
        "company_mail_domains",
        sa.Column("sending_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute("DROP VIEW IF EXISTS readonly.company_mail_domains")
    op.execute(
        """
        CREATE VIEW readonly.company_mail_domains AS
        SELECT id, company_id, domain, status, sending_enabled, created_at, updated_at
        FROM public.company_mail_domains
        """
    )
    op.execute(_GRANT)


def downgrade() -> None:
    # LP-991's view, restored before the column it would otherwise lose goes.
    op.execute("DROP VIEW IF EXISTS readonly.company_mail_domains")
    op.execute(
        """
        CREATE VIEW readonly.company_mail_domains AS
        SELECT id, company_id, domain, status, created_at, updated_at
        FROM public.company_mail_domains
        """
    )
    op.execute(_GRANT)
    op.drop_column("company_mail_domains", "sending_enabled")

"""LP-991 — a company's own mail domain.

`company_mail_domains`: one row per company, one company per domain. A loan file's address is
`lf-<display_id>@<domain>` while the row is `active`; with no active row the file has no address.
Step 3 adds onboarding states and the zone, nameserver and SES identity columns to this same table.

The readonly view exposes every column. A domain names a company's mail subdomain, not a person, and
LP-998 needs to read it back after linking the staging company.

Hand-written, like every migration against this schema.

Revision ID: 6e1f6b5aa190
Revises: 169e48fff378
Create Date: 2026-10-26 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "6e1f6b5aa190"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "169e48fff378"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUSES = ("active", "inactive")

_VIEW = """
    CREATE VIEW readonly.company_mail_domains AS
    SELECT id, company_id, domain, status, created_at, updated_at
    FROM public.company_mail_domains
    """

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
    op.create_table(
        "company_mail_domains",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("domain", sa.String(length=256), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_company_mail_domains_company_id_companies",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_company_mail_domains"),
        sa.UniqueConstraint("company_id", name="uq_company_mail_domains_company_id"),
        sa.UniqueConstraint("domain", name="uq_company_mail_domains_domain"),
    )
    joined = ", ".join(f"'{value}'" for value in _STATUSES)
    op.execute(
        "ALTER TABLE company_mail_domains ADD CONSTRAINT ck_company_mail_domains_maildomainstatus "
        f"CHECK (status IN ({joined}))"
    )

    op.execute("DROP VIEW IF EXISTS readonly.company_mail_domains")
    op.execute(_VIEW)
    op.execute(_GRANT)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS readonly.company_mail_domains")
    op.drop_table("company_mail_domains")

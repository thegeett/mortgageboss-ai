"""LP-1005 — `company_mail_domains` onboarding states, `zone_id` and `nameservers`.

The status CHECK gains `pending_ns`, `verifying` and `problem` (`problem` is set from LP-1006);
`active` and `inactive` stay. Two nullable columns hold the Route 53 zone `set_up_mail_domain` creates
and its nameservers. Existing rows (domains linked by hand) are untouched: no zone, same status.

The readonly view exposes both columns: they are DNS settings, not identifiers of a person.

Downgrade: a row still mid-setup (`pending_ns`, `verifying`, `problem`) becomes `inactive`, the
state that gives no address, before the old CHECK comes back. Its zone in AWS is untouched.

Revision ID: 5c8e1a7d3b92
Revises: 9a4d2f7c1e65
Create Date: 2026-11-01 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "5c8e1a7d3b92"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "9a4d2f7c1e65"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "ck_company_mail_domains_maildomainstatus"
_NEW_STATUSES = ("pending_ns", "verifying", "active", "problem", "inactive")
_OLD_STATUSES = ("active", "inactive")

_GRANT = """
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
            EXECUTE 'GRANT SELECT ON readonly.company_mail_domains TO mbai_readonly';
        END IF;
    END
    $$;
    """


def _check(statuses: tuple[str, ...]) -> None:
    joined = ", ".join(f"'{value}'" for value in statuses)
    op.execute(f"ALTER TABLE company_mail_domains DROP CONSTRAINT IF EXISTS {_CHECK}")
    op.execute(
        f"ALTER TABLE company_mail_domains ADD CONSTRAINT {_CHECK} CHECK (status IN ({joined}))"
    )


def upgrade() -> None:
    _check(_NEW_STATUSES)
    op.add_column("company_mail_domains", sa.Column("zone_id", sa.Text(), nullable=True))
    op.add_column(
        "company_mail_domains",
        sa.Column("nameservers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.execute("DROP VIEW IF EXISTS readonly.company_mail_domains")
    op.execute(
        """
        CREATE VIEW readonly.company_mail_domains AS
        SELECT id, company_id, domain, status, sending_enabled, zone_id, nameservers,
               created_at, updated_at
        FROM public.company_mail_domains
        """
    )
    op.execute(_GRANT)


def downgrade() -> None:
    # LP-997's view, restored before the columns it would otherwise lose go.
    op.execute("DROP VIEW IF EXISTS readonly.company_mail_domains")
    op.execute(
        """
        CREATE VIEW readonly.company_mail_domains AS
        SELECT id, company_id, domain, status, sending_enabled, created_at, updated_at
        FROM public.company_mail_domains
        """
    )
    op.execute(_GRANT)
    op.drop_column("company_mail_domains", "nameservers")
    op.drop_column("company_mail_domains", "zone_id")
    op.execute(
        "UPDATE company_mail_domains SET status = 'inactive' "
        "WHERE status IN ('pending_ns', 'verifying', 'problem')"
    )
    _check(_OLD_STATUSES)

"""LP-808 — Route B: a company's own mail, forwarded to an address we minted.

`co-<token>@<inbox domain>` is the company analogue of `lf-<token>@`, and a bearer credential in
exactly the same sense (ADR-397): an admin types it into a routing rule, so it is stored in the
CLEAR — a token nobody can read back is useless in a console. The consequence is the same too:
anyone who can send to it gets their mail into this company's triage queue.

THE READONLY VIEW DROPS `token`, `source_address` AND `encrypted_refresh_token`. The token is the
capability, and `loan_files.inbox_token` is already excluded on identical reasoning. `source_address`
is a real mailbox at a customer's domain. The refresh token is unused by forwarding and is a secret
the moment Route C fills it — excluded now rather than when it first holds something.

FOUR COLUMNS ARE UNUSED BY FORWARDING. `cursor`, `watch_expires_at`, `encrypted_refresh_token` and
`last_error_code` belong to Route C. The plan asks for them now so a Gmail or Graph integration is a
service, not a migration against a table with live rows.

Hand-written, like every migration against this schema.

Revision ID: b7e4d219af53
Revises: a3c81f7b64e2
Create Date: 2026-09-08 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7e4d219af53"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "a3c81f7b64e2"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS = ("token_address", "forwarded_alias", "gmail_api", "graph")
_STATUSES = ("connected", "degraded", "needs_reauthorization", "revoked")
_VERIFICATIONS = ("not_verified", "awaiting_first_message", "verified")

#: `inbound_messages.routing_signal` now records rungs 3-5 as well. It is a free String, not a CHECK,
#: so nothing needs altering — noted here because the values change and a reader of this migration
#: would otherwise wonder where they were added.
_NEW_SIGNALS = ("footer_tag", "participant", "subject_reference")

_CONNECTIONS_VIEW = """
    CREATE VIEW readonly.mailbox_connections AS
    SELECT id, company_id, kind, provider, status, verification,
           last_success_at, last_error_code, consecutive_failures,
           (source_address IS NOT NULL) AS has_source_address,
           created_at, updated_at, deleted_at
    FROM public.mailbox_connections
    """

_GRANT = """
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
            EXECUTE 'GRANT SELECT ON readonly.mailbox_connections TO mbai_readonly';
        END IF;
    END
    $$;
    """


def _check(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def upgrade() -> None:
    op.create_table(
        "mailbox_connections",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "company_id",
            sa.UUID(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(64), nullable=False, server_default="forwarded_alias"),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("source_address", sa.String(128), nullable=True),
        sa.Column("provider", sa.String(64), nullable=True),
        sa.Column("status", sa.String(64), nullable=False, server_default="connected"),
        sa.Column("verification", sa.String(64), nullable=False, server_default="not_verified"),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(64), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cursor", sa.Text(), nullable=True),
        sa.Column("watch_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        # VARCHAR + CHECK rather than native enums (ADR-037): adding a value is one migration that
        # recreates the constraint from its own complete tuple, not an ALTER TYPE.
        sa.CheckConstraint(_check("kind", _KINDS), name="ck_mailbox_connections_kind"),
        sa.CheckConstraint(_check("status", _STATUSES), name="ck_mailbox_connections_status"),
        sa.CheckConstraint(
            _check("verification", _VERIFICATIONS), name="ck_mailbox_connections_verification"
        ),
    )
    op.create_index("uq_mailbox_connections_token", "mailbox_connections", ["token"], unique=True)
    op.create_index("ix_mailbox_connections_company_id", "mailbox_connections", ["company_id"])
    # FUNCTIONAL. The resolver compares `lower(token)` — a relay may rewrite the local part — and
    # that cannot use the plain unique index above. This is LP-805's review finding applied before
    # it becomes one: a sequential scan on the path an attacker probes for free.
    op.execute(
        "CREATE INDEX ix_mailbox_connections_token_lower ON mailbox_connections (lower(token))"
    )

    op.execute(_CONNECTIONS_VIEW)
    op.execute(_GRANT)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS readonly.mailbox_connections")
    op.execute("DROP INDEX IF EXISTS ix_mailbox_connections_token_lower")
    op.drop_index("ix_mailbox_connections_company_id", table_name="mailbox_connections")
    op.drop_index("uq_mailbox_connections_token", table_name="mailbox_connections")
    op.drop_table("mailbox_connections")

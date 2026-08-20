"""lp586 snapshot ai findings

Revision ID: 09f2bd5089a4
Revises: 197304ef8f4c
Create Date: 2026-08-19 20:58:13.247690

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "09f2bd5089a4"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "197304ef8f4c"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "snapshot_findings",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("loan_file_id", sa.UUID(), nullable=False),
        # Content identity: the SAME observation on a later run hashes to the same key, which is what
        # carries a processor's disposition across re-runs.
        sa.Column("finding_key", sa.String(length=64), nullable=False),
        # Which snapshot it was last seen in — provenance, not identity.
        sa.Column("snapshot_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("sources", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("disposition", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("disposition_note", sa.Text(), nullable=True),
        sa.Column("disposition_by_user_id", sa.UUID(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["loan_file_id"], ["loan_files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["disposition_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("loan_file_id", "finding_key", name="uq_snapshot_findings_key"),
    )
    op.create_index("ix_snapshot_findings_loan_file", "snapshot_findings", ["loan_file_id"])
    # Exposed through the read-only schema like every other table (the C7 drift guard requires a
    # decision either way). Free text is scrubbed; the hashes and the disposition carry no identifier.
    op.execute(
        """
        CREATE VIEW readonly.snapshot_findings AS
        SELECT id, loan_file_id, finding_key, snapshot_fingerprint, kind,
               readonly.scrub(title) AS title,
               readonly.scrub(detail) AS detail,
               readonly.scrub_jsonb(sources) AS sources,
               disposition,
               readonly.scrub(disposition_note) AS disposition_note,
               disposition_by_user_id, first_seen_at, last_seen_at
        FROM public.snapshot_findings
        """
    )
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
                EXECUTE 'GRANT SELECT ON readonly.snapshot_findings TO mbai_readonly';
            END IF;
        END
        $$;
    """)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS readonly.snapshot_findings")
    op.drop_index("ix_snapshot_findings_loan_file", table_name="snapshot_findings")
    op.drop_table("snapshot_findings")

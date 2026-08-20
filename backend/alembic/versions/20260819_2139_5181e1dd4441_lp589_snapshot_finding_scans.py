"""lp589 snapshot finding scans

Revision ID: 5181e1dd4441
Revises: 09f2bd5089a4
Create Date: 2026-08-19 21:39:57.153872

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5181e1dd4441"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "09f2bd5089a4"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # LP-589 — the cache marker. Zero findings is a real answer, and without somewhere to record
    # "we asked about this snapshot" it could not be cached: a file with no findings has no row to
    # carry a fingerprint, so it re-asked on every run forever.
    op.create_table(
        "snapshot_finding_scans",
        sa.Column("loan_file_id", sa.UUID(), primary_key=True),
        sa.Column("snapshot_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["loan_file_id"], ["loan_files.id"], ondelete="CASCADE"),
    )
    op.execute(
        """
        CREATE VIEW readonly.snapshot_finding_scans AS
        SELECT loan_file_id, snapshot_fingerprint, scanned_at
        FROM public.snapshot_finding_scans
        """
    )
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
                EXECUTE 'GRANT SELECT ON readonly.snapshot_finding_scans TO mbai_readonly';
            END IF;
        END
        $$;
    """)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS readonly.snapshot_finding_scans")
    op.drop_table("snapshot_finding_scans")

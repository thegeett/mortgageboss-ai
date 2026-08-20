"""lp592 run cross check count

Revision ID: 7ae995bd4674
Revises: 6494d7e39250
Create Date: 2026-08-20 09:15:08.314301

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7ae995bd4674"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "6494d7e39250"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # LP-592 — server_default so the 29 existing runs read 0 rather than NULL; the column is
    # NOT NULL and back-filling a real number is impossible (snapshot findings are keyed by loan
    # file and carry no run, which is the whole reason this column exists).
    op.add_column(
        "verifications",
        sa.Column("cross_check_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW readonly.verifications AS
        SELECT id, loan_file_id, status, trigger, started_at, completed_at,
               red_count, yellow_count, green_count,
               total_tokens_used, total_cost_estimate, error_detail, input_fingerprint,
               created_at, updated_at, deleted_at,
               cross_check_count
        FROM public.verifications
        """
    )


def downgrade() -> None:
    # The view SELECTs the column, so it must go first: CREATE OR REPLACE cannot drop a column.
    op.execute("DROP VIEW IF EXISTS readonly.verifications CASCADE")
    op.drop_column("verifications", "cross_check_count")
    op.execute(
        """
        CREATE VIEW readonly.verifications AS
        SELECT id, loan_file_id, status, trigger, started_at, completed_at,
               red_count, yellow_count, green_count,
               total_tokens_used, total_cost_estimate, error_detail, input_fingerprint,
               created_at, updated_at, deleted_at
        FROM public.verifications
        """
    )
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
                EXECUTE 'GRANT SELECT ON readonly.verifications TO mbai_readonly';
            END IF;
        END
        $$;
    """)

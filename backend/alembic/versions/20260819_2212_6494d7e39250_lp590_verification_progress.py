"""lp590 verification progress

Revision ID: 6494d7e39250
Revises: 5181e1dd4441
Create Date: 2026-08-19 22:12:18.915353

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6494d7e39250"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "5181e1dd4441"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # LP-590 — its OWN table, not a column on `verifications`. The run is one transaction that
    # commits at the end, so progress must be written from a separate session — and the run takes
    # SELECT ... FOR UPDATE on its own row to decide completion, so a second session writing there
    # would contend with the completion lock at exactly the wrong moment.
    op.create_table(
        "verification_progress",
        sa.Column("verification_id", sa.UUID(), primary_key=True),
        sa.Column("phase", sa.String(length=32), nullable=False),
        sa.Column("phase_index", sa.Integer(), nullable=False),
        sa.Column("phase_total", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["verification_id"], ["verifications.id"], ondelete="CASCADE"),
    )
    op.execute(
        """
        CREATE VIEW readonly.verification_progress AS
        SELECT verification_id, phase, phase_index, phase_total, updated_at
        FROM public.verification_progress
        """
    )
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
                EXECUTE 'GRANT SELECT ON readonly.verification_progress TO mbai_readonly';
            END IF;
        END
        $$;
    """)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS readonly.verification_progress")
    op.drop_table("verification_progress")

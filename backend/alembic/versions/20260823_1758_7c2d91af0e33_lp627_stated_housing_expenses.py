"""LP-627 — the 1003's proposed housing-expense breakdown.

MISMO states HOUSING_EXPENSES under the LOAN: the proposed P&I, homeowners insurance and real-estate
tax. Every leaf fell to `catch_all`, which the snapshot does not read — so LF-ABRS's DTI reported
"Property taxes / unknown — missing or unusable input (fail-closed, never assumed $0)" while the
application stated RealEstateTax at $541.67 a month. That file's ratio sits at 44.8% against a 45%
limit.

STATED, NOT VERIFIED. The fail-closed housing gate is right to refuse an application figure as
verification; this feeds `_unverified_housing_inputs`, which offers the processor what the file states
without letting it satisfy the gate.

Revision ID: 7c2d91af0e33
Revises: 4b9efbbde5ef
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7c2d91af0e33"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "4b9efbbde5ef"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stated_housing_expenses",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "loan_file_id",
            sa.UUID(),
            sa.ForeignKey("loan_files.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expense_type", sa.String(length=64), nullable=True),
        sa.Column("timing", sa.String(length=32), nullable=True),
        sa.Column("payment_amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_stated_housing_expenses_loan_file",
        "stated_housing_expenses",
        ["loan_file_id"],
    )
    # Readable on staging, or the fact stays as unreachable as it was in catch_all — which is the
    # defect this whole line of work is about. A type, a timing and an amount: nothing to scrub.
    op.execute(
        """
        CREATE VIEW readonly.stated_housing_expenses AS
        SELECT id, loan_file_id, expense_type, timing, payment_amount,
               created_at, updated_at, deleted_at
        FROM public.stated_housing_expenses
        """
    )
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
                EXECUTE 'GRANT SELECT ON readonly.stated_housing_expenses TO mbai_readonly';
            END IF;
        END
        $$;
    """)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS readonly.stated_housing_expenses")
    op.drop_index("ix_stated_housing_expenses_loan_file", table_name="stated_housing_expenses")
    op.drop_table("stated_housing_expenses")

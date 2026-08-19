"""lp568 stated liability payoff at closing

Revision ID: 197304ef8f4c
Revises: cf4ee72bd605
Create Date: 2026-08-19 13:41:25.015322

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "197304ef8f4c"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "cf4ee72bd605"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # LP-568 — both nullable with no server default: NULL means "not established", which is
    # exactly what every existing row is. A default of false would assert "retained" for the
    # whole table on a fact nobody has checked.
    op.add_column(
        "stated_liabilities",
        sa.Column("paid_off_at_closing", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "stated_liabilities",
        sa.Column("payoff_source", sa.String(length=64), nullable=True),
    )

    # Re-expose the readonly view with the two new columns. A boolean and a short provenance
    # slug carry no identifier, and they are exactly what someone diagnosing a DTI needs to see —
    # "is this excluded, and who said so". CREATE OR REPLACE can append columns at the END of the
    # select list, so the existing column order is preserved and no dependent object drops.
    op.execute(
        """
        CREATE OR REPLACE VIEW readonly.stated_liabilities AS
        SELECT id, loan_file_id, liability_type, monthly_payment, unpaid_balance,
               readonly.scrub(holder_name) AS holder_name,
               created_at, updated_at, deleted_at,
               paid_off_at_closing, payoff_source
        FROM public.stated_liabilities
        """
    )


def downgrade() -> None:
    # Drop the view first: the columns below cannot be dropped while it depends on them.
    op.execute(
        """
        CREATE OR REPLACE VIEW readonly.stated_liabilities AS
        SELECT id, loan_file_id, liability_type, monthly_payment, unpaid_balance,
               readonly.scrub(holder_name) AS holder_name,
               created_at, updated_at, deleted_at
        FROM public.stated_liabilities
        """
    )
    op.drop_column("stated_liabilities", "payoff_source")
    op.drop_column("stated_liabilities", "paid_off_at_closing")

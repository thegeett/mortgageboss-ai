"""LP-627 — the application's answer to "is this payment already a PITIA?"

MISMO states `LiabilityPaymentIncludesTaxesInsuranceIndicator` on every LIABILITY_DETAIL, beside four
fields the parser already read. It fell to `catch_all`, which the snapshot does not read.

DT-6 compares a mortgage statement's billed payment against the application's stated payment. Whether
the two are the same KIND of figure decides whether that comparison means anything: a P&I-only stated
payment and a servicer's PITIA differ by the escrow and are not a discrepancy. The rule had only the
statement's side.

Tri-state and nullable: None means the export did not state it, which is not the same as False.

Revision ID: 4b9efbbde5ef
Revises: 4a1298968c99
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4b9efbbde5ef"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "4a1298968c99"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "stated_liabilities",
        sa.Column("payment_includes_taxes_insurance", sa.Boolean(), nullable=True),
    )
    # The read-only view must carry it, or staging cannot see what was imported — the defect this
    # whole line of work is about. A boolean describing a payment: no identifier, nothing to scrub.
    op.execute("DROP VIEW IF EXISTS readonly.stated_liabilities")
    op.execute(
        """
        CREATE VIEW readonly.stated_liabilities AS
        SELECT id, loan_file_id, liability_type, monthly_payment, unpaid_balance,
               readonly.scrub(holder_name) AS holder_name,
               created_at, updated_at, deleted_at,
               paid_off_at_closing, payoff_source, payment_includes_taxes_insurance
        FROM public.stated_liabilities
        """
    )
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
                EXECUTE 'GRANT SELECT ON readonly.stated_liabilities TO mbai_readonly';
            END IF;
        END
        $$;
    """)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS readonly.stated_liabilities")
    op.drop_column("stated_liabilities", "payment_includes_taxes_insurance")
    op.execute(
        """
        CREATE VIEW readonly.stated_liabilities AS
        SELECT id, loan_file_id, liability_type, monthly_payment, unpaid_balance,
               readonly.scrub(holder_name) AS holder_name,
               created_at, updated_at, deleted_at,
               paid_off_at_closing, payoff_source
        FROM public.stated_liabilities
        """
    )
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
                EXECUTE 'GRANT SELECT ON readonly.stated_liabilities TO mbai_readonly';
            END IF;
        END
        $$;
    """)

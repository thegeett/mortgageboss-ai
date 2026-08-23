"""LP-627 — five loan/property facts the MISMO states and catch_all swallowed.

Each has a consumer that is currently abstaining, or deriving what the export says outright:

  * TotalMortgagedPropertiesCount        — LP-597 DERIVES this from the REO schedule to size reserves
  * CurrentRateSetDate                   — CL-1 is waiting on a rate lock; the export dates one
  * SellerPaidClosingCostsAmount         — an interested-party contribution (FR-3)
  * SpecialBorrowerSellerRelationshipIndicator is NOT here: it is a per-BORROWER declaration in
    the ULAD extension, and LP-627 fixes the declaration loop to reach it rather than inventing a
    loan-level column for a borrower-level fact.
  * PropertyMixedUsageIndicator          — PR-3, where eligibility is programme-specific

All nullable and tri-state. None is "the export did not state it", which is never the same as 0 or
False — reading an absent indicator as False would assert a fact the file does not contain.

Revision ID: 9d3e4c17b520
Revises: 7c2d91af0e33
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9d3e4c17b520"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "7c2d91af0e33"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LOAN_COLUMNS = (
    ("total_mortgaged_properties", sa.Integer()),
    ("rate_set_date", sa.Date()),
    ("seller_paid_closing_costs", sa.Numeric(precision=14, scale=2)),
)


def upgrade() -> None:
    for name, type_ in _LOAN_COLUMNS:
        op.add_column("loan_files", sa.Column(name, type_, nullable=True))
    op.add_column("properties", sa.Column("mixed_usage", sa.Boolean(), nullable=True))

    # The read-only views must carry them, or the fact stays as unreachable on staging as it was in
    # catch_all — the defect this line of work is about. Statuses, dates, counts and amounts: nothing
    # to scrub.
    op.execute("DROP VIEW IF EXISTS readonly.loan_files")
    op.execute(
        """
        CREATE VIEW readonly.loan_files AS
        SELECT id, display_id, company_id, lender_id,
               loan_program, loan_purpose, loan_amount, status,
               note_amount, note_rate_percent, lien_priority, amortization_type,
               amortization_months, application_received_date, ai_needs_status,
               refinance_type, verification_stale, aggression_level_override,
               submitted_aggression_level,
               total_mortgaged_properties, rate_set_date, seller_paid_closing_costs,
               created_at, updated_at, deleted_at
        FROM public.loan_files
        """
    )
    op.execute("DROP VIEW IF EXISTS readonly.properties")
    op.execute(
        """
        CREATE VIEW readonly.properties AS
        SELECT id, loan_file_id, city, state, property_type, occupancy_type,
               attachment_type, construction_method, financed_unit_count,
               in_project, is_pud, mixed_usage,
               estimated_value, purchase_price, valuation_amount,
               created_at, updated_at, deleted_at
        FROM public.properties
        """
    )
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
                EXECUTE 'GRANT SELECT ON readonly.loan_files TO mbai_readonly';
                EXECUTE 'GRANT SELECT ON readonly.properties TO mbai_readonly';
            END IF;
        END
        $$;
    """)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS readonly.loan_files")
    op.execute("DROP VIEW IF EXISTS readonly.properties")
    op.drop_column("properties", "mixed_usage")
    for name, _type in _LOAN_COLUMNS:
        op.drop_column("loan_files", name)
    op.execute(
        """
        CREATE VIEW readonly.loan_files AS
        SELECT id, display_id, company_id, lender_id,
               loan_program, loan_purpose, loan_amount, status,
               note_amount, note_rate_percent, lien_priority, amortization_type,
               amortization_months, application_received_date, ai_needs_status,
               refinance_type, verification_stale, aggression_level_override,
               submitted_aggression_level,
               created_at, updated_at, deleted_at
        FROM public.loan_files
        """
    )
    op.execute(
        """
        CREATE VIEW readonly.properties AS
        SELECT id, loan_file_id, city, state, property_type, occupancy_type,
               attachment_type, construction_method, financed_unit_count,
               in_project, is_pud,
               estimated_value, purchase_price, valuation_amount,
               created_at, updated_at, deleted_at
        FROM public.properties
        """
    )

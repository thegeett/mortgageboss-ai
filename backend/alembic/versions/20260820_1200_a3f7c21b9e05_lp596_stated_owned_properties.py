"""lp596 stated owned properties

Revision ID: a3f7c21b9e05
Revises: 7ae995bd4674
Create Date: 2026-08-20 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3f7c21b9e05"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "7ae995bd4674"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # LP-596 — the 1003's real-estate-owned schedule, which MISMO has always carried and the parser
    # has always swept into `catch_all`. `catch_all` never reaches the snapshot, so the rule engine
    # could not see it and AS-4 / DT-6 / DT-8 were reporting they could not determine facts the
    # application states outright.
    #
    # EVERY COLUMN IS NULLABLE, deliberately: MISMO makes each element optional and the tri-state
    # matters. A NULL `is_subject` means "the export did not say", which is NOT "false" — and even a
    # stored false is weak, since the real export marks false on every block (the subject property is
    # described in its own section, not repeated here). Only a true identifies the subject.
    op.create_table(
        "stated_owned_properties",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("loan_file_id", sa.UUID(), nullable=False),
        sa.Column("is_subject", sa.Boolean(), nullable=True),
        sa.Column("disposition_status", sa.String(length=64), nullable=True),
        sa.Column("lien_upb", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("unit_count", sa.Integer(), nullable=True),
        sa.Column("rental_income_gross", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("rental_income_net", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("current_usage_type", sa.String(length=64), nullable=True),
        sa.Column("usage_type", sa.String(length=64), nullable=True),
        sa.Column("estimated_value", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["loan_file_id"], ["loan_files.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_stated_owned_properties_loan_file_id",
        "stated_owned_properties",
        ["loan_file_id"],
    )

    # The readonly query view. NO ADDRESS COLUMN — the parser deliberately does not read the nested
    # PROPERTY/ADDRESS (it is the borrower's other home, and no rule asks for it), so there is nothing
    # here to scrub. Every column below is a status, a count or an amount.
    op.execute(
        """
        CREATE VIEW readonly.stated_owned_properties AS
        SELECT id, loan_file_id, is_subject, disposition_status, lien_upb, unit_count,
               rental_income_gross, rental_income_net, current_usage_type, usage_type,
               estimated_value, created_at, updated_at, deleted_at
        FROM public.stated_owned_properties
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
                GRANT SELECT ON readonly.stated_owned_properties TO mbai_readonly;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS readonly.stated_owned_properties")
    op.drop_index("ix_stated_owned_properties_loan_file_id", table_name="stated_owned_properties")
    op.drop_table("stated_owned_properties")

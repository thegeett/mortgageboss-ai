"""LP-624 — the stated EMPLOYMENT record, not just the employer's name.

The MISMO states a whole employment per employer — status, self-employment, classification, position,
start and end dates, monthly income, and whether the employer is a relative or interested party. The
parser read `FullName` and left the rest unconsumed, so it fell to `catch_all`, which the snapshot does
not read. On LF-ABRS that meant a complete, dated, gapless two-year history imported as three bare
strings while IN-4 abstained for want of the dates.

ADDITIVE AND NULLABLE. Every column is new and nullable, so existing rows stay valid and no backfill is
required for the migration to apply; `scripts/backfill_stated_employment.py` re-parses stored MISMO to
fill them where a file already exists.

Revision ID: 4a1298968c99
Revises: d2e5b83c61af
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4a1298968c99"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "d2e5b83c61af"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = (
    sa.Column("self_employed", sa.Boolean(), nullable=True),
    sa.Column("classification", sa.String(length=32), nullable=True),
    sa.Column("position", sa.String(length=256), nullable=True),
    sa.Column("start_date", sa.Date(), nullable=True),
    sa.Column("end_date", sa.Date(), nullable=True),
    sa.Column("monthly_income", sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column("special_relationship", sa.Boolean(), nullable=True),
)


def upgrade() -> None:
    for column in _COLUMNS:
        op.add_column("stated_employers", column.copy())

    # The read-only query view must carry the new columns or staging cannot see what was just imported
    # — the whole point of the ticket is that a fact in the file was unreachable. Every column here is a
    # status, a date, an amount or a classification: no identifier, nothing to scrub.
    op.execute("DROP VIEW IF EXISTS readonly.stated_employers")
    op.execute(
        """
        CREATE VIEW readonly.stated_employers AS
        SELECT id, borrower_id,
               readonly.scrub(employer_name) AS employer_name,
               is_current, self_employed, classification,
               readonly.scrub(position) AS position,
               start_date, end_date, monthly_income, special_relationship,
               created_at, updated_at, deleted_at
        FROM public.stated_employers
        """
    )
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
                EXECUTE 'GRANT SELECT ON readonly.stated_employers TO mbai_readonly';
            END IF;
        END
        $$;
    """)


def downgrade() -> None:
    # The view SELECTs the columns, so it goes first: CREATE OR REPLACE cannot drop a column.
    op.execute("DROP VIEW IF EXISTS readonly.stated_employers")
    for column in _COLUMNS:
        op.drop_column("stated_employers", column.name)
    op.execute(
        """
        CREATE VIEW readonly.stated_employers AS
        SELECT id, borrower_id,
               readonly.scrub(employer_name) AS employer_name,
               is_current, created_at, updated_at, deleted_at
        FROM public.stated_employers
        """
    )
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
                EXECUTE 'GRANT SELECT ON readonly.stated_employers TO mbai_readonly';
            END IF;
        END
        $$;
    """)

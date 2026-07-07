"""LP-118.7 store-everything — borrower current address + property county columns

Revision ID: e2d5b8c1f4a9
Revises: c8e1a4f9d2b7
Create Date: 2026-07-07 17:00:00.000000

Adds the columns for the MISMO fields the parser reads but previously dropped (LP-118.7): the
borrower's current residential address (structured, mirroring ``properties`` address columns) and
the property ``county``. All nullable; existing rows keep NULL (no backfill — the values were not
retained, so there is nothing to backfill). The import now persists these; a re-import populates
them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2d5b8c1f4a9"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "c8e1a4f9d2b7"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add borrower current-address columns + property.county."""
    op.add_column(
        "borrowers", sa.Column("current_address_line", sa.String(length=256), nullable=True)
    )
    op.add_column("borrowers", sa.Column("current_city", sa.String(length=256), nullable=True))
    op.add_column("borrowers", sa.Column("current_state", sa.String(length=2), nullable=True))
    op.add_column(
        "borrowers", sa.Column("current_postal_code", sa.String(length=16), nullable=True)
    )
    op.add_column(
        "borrowers", sa.Column("current_address_type", sa.String(length=64), nullable=True)
    )
    op.add_column("properties", sa.Column("county", sa.String(length=64), nullable=True))


def downgrade() -> None:
    """Drop the LP-118.7 columns."""
    op.drop_column("properties", "county")
    op.drop_column("borrowers", "current_address_type")
    op.drop_column("borrowers", "current_postal_code")
    op.drop_column("borrowers", "current_state")
    op.drop_column("borrowers", "current_city")
    op.drop_column("borrowers", "current_address_line")

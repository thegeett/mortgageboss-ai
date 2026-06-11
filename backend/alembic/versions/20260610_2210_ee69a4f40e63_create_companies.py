"""create_companies

Revision ID: ee69a4f40e63
Revises: f0934055772d
Create Date: 2026-06-10 22:10:38.143654

Creates the ``companies`` table — the tenant root of the multi-tenant schema
(LP-11). Slug is globally unique (enforced by a unique index) and indexed for
lookups. ``settings`` is a JSON object for per-company configuration.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ee69a4f40e63"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "f0934055772d"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the companies table and its unique slug index."""
    op.create_table(
        "companies",
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_companies")),
    )
    op.create_index(op.f("ix_companies_slug"), "companies", ["slug"], unique=True)


def downgrade() -> None:
    """Drop the companies table and its index."""
    op.drop_index(op.f("ix_companies_slug"), table_name="companies")
    op.drop_table("companies")

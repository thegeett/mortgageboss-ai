"""create_lenders

Revision ID: f9ed4a63a97e
Revises: e5d215445535
Create Date: 2026-06-10 22:36:26.976220

Creates the ``lenders`` table (LP-12) — institutions that loan files are
submitted to (UWM, Sun-West). Each lender belongs to a company via a RESTRICT
foreign key (ADR-044). The slug is unique **per company** (composite unique on
``company_id`` + ``slug``), not globally (ADR-045) — the multi-tenant default,
contrasting with the globally-unique user email. ``lender_overlays`` and
``supported_programs`` are JSON (ADR-046); overlays are structured in Phase 3.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f9ed4a63a97e"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "e5d215445535"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the lenders table, its FK, composite unique slug, and index."""
    op.create_table(
        "lenders",
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("contact_email", sa.String(length=256), nullable=True),
        sa.Column("portal_url", sa.String(length=1024), nullable=True),
        sa.Column("contact_phone", sa.String(length=64), nullable=True),
        sa.Column("notes", sa.String(length=1024), nullable=True),
        sa.Column("lender_overlays", sa.JSON(), nullable=False),
        sa.Column("supported_programs", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_lenders_company_id_companies"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lenders")),
        sa.UniqueConstraint("company_id", "slug", name="uq_lenders_company_id_slug"),
    )
    op.create_index(op.f("ix_lenders_company_id"), "lenders", ["company_id"], unique=False)


def downgrade() -> None:
    """Drop the lenders table and its index."""
    op.drop_index(op.f("ix_lenders_company_id"), table_name="lenders")
    op.drop_table("lenders")

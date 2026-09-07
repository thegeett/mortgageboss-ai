"""LP-UI-015 - saved views

Creates `saved_views`: a named, reusable filter over the pipeline, owned by a
user and scoped to a company, with an optional shared flag.

HAND-WRITTEN. `alembic revision --autogenerate` on this repo proposes eighteen
unrelated destructive operations alongside whatever you asked for, because the
models and the local development database have drifted (see the LP-UI-010
migration's docstring). Autogenerate was not used.

Revision ID: c1e5a97b3d42
Revises: b7f4a2d19c63
Create Date: 2026-08-30 01:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1e5a97b3d42"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "b7f4a2d19c63"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SORT = sa.Enum(
    "attention",
    "updated_desc",
    "updated_asc",
    "amount_desc",
    name="savedviewsort",
    native_enum=False,
    create_constraint=True,
    length=32,
)


def upgrade() -> None:
    """Create the saved_views table."""
    op.create_table(
        "saved_views",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=False),
        sa.Column("sort", _SORT, server_default="attention", nullable=False),
        sa.Column("is_shared", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_saved_views_company_id_companies"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_saved_views_owner_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_saved_views")),
        # A person should not end up with two views of the same name; two people
        # in the same company may. `deleted_at` is in the key so a deleted name
        # can be reused.
        sa.UniqueConstraint(
            "owner_user_id", "name", "deleted_at", name="uq_saved_views_owner_name"
        ),
    )
    op.create_index(op.f("ix_saved_views_company_id"), "saved_views", ["company_id"])
    op.create_index(op.f("ix_saved_views_owner_user_id"), "saved_views", ["owner_user_id"])


def downgrade() -> None:
    """Drop the saved_views table and everything in it."""
    op.drop_index(op.f("ix_saved_views_owner_user_id"), table_name="saved_views")
    op.drop_index(op.f("ix_saved_views_company_id"), table_name="saved_views")
    op.drop_table("saved_views")

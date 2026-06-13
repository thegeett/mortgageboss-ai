"""create_users

Revision ID: e5d215445535
Revises: ee69a4f40e63
Create Date: 2026-06-10 22:18:45.686297

Creates the ``users`` table (LP-11). Each user belongs to one company via a
RESTRICT foreign key (companies are soft-deleted, never hard-deleted — ADR-044).
Email is globally unique (ADR-042, enforced by a unique index). ``role`` is a
VARCHAR with a CHECK constraint (``ck_users_userrole``) rather than a native PG
enum — see ADR-037 (and its amendment recording the ``create_constraint`` fix).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5d215445535"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "ee69a4f40e63"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the users table, its FK to companies, indexes, and role CHECK."""
    op.create_table(
        "users",
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=256), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("first_name", sa.String(length=64), nullable=False),
        sa.Column("last_name", sa.String(length=64), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "processor",
                "admin",
                name="userrole",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_users_company_id_companies"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(op.f("ix_users_company_id"), "users", ["company_id"], unique=False)
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)


def downgrade() -> None:
    """Drop the users table and its indexes."""
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_index(op.f("ix_users_company_id"), table_name="users")
    op.drop_table("users")

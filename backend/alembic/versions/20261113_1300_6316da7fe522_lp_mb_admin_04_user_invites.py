"""LP-MB-Admin-04 — staff invites.

`user_invites`: one row per invitation. `token_hash` is the SHA-256 of the emailed token; the token
itself is never stored. A partial unique index allows one open invite per address per company
(`accepted_at IS NULL AND revoked_at IS NULL`); expired rows keep theirs and are reused.

No readonly view: `email` identifies a person, and the rest (roles, dates, counts) answers no question
anyone has asked of staging yet. Listed as excluded in `tests/test_readonly_query.py`.

Hand-written, like every migration against this schema.

Revision ID: 6316da7fe522
Revises: c5874fbee899
Create Date: 2026-11-13 13:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "6316da7fe522"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "c5874fbee899"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_invites",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("roles", sa.JSON(), nullable=False),
        sa.Column("token_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("invited_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("send_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_user_invites_company_id_companies",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["invited_by_user_id"],
            ["users.id"],
            name="fk_user_invites_invited_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["accepted_user_id"],
            ["users.id"],
            name="fk_user_invites_accepted_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_invites"),
        sa.UniqueConstraint("token_hash", name="uq_user_invites_token_hash"),
    )
    op.create_index("ix_user_invites_company_id", "user_invites", ["company_id"])
    op.execute(
        "CREATE UNIQUE INDEX uq_user_invites_company_id_email_open ON user_invites "
        "(company_id, email) WHERE accepted_at IS NULL AND revoked_at IS NULL"
    )


def downgrade() -> None:
    op.drop_table("user_invites")

"""LP-MB-Admin-03 — a person's profile, licensing and last sign-in.

On `users`:

- `phone` VARCHAR(32), `title` VARCHAR(100), both nullable: what an admin edits on People.
- `nmls_id` VARCHAR(16) nullable and `licensed_states` JSON (a list of two-letter codes, validated in
  the request schema) default `[]`: a loan officer's licensing. One NMLS ID per person and a list of
  states, so no table until a state licence needs its own number or expiry.
- `sees_all_loans` default false: read by LP-MB-Admin-05 when files are restricted to their team.
- `last_login_at` nullable: set on a successful login, not on refresh.

Every existing row takes the defaults, which is what it is: nothing recorded any of this before.

`readonly.users` gains `title`, `licensed_states`, `sees_all_loans` and `last_login_at`. NOT `phone` or
`nmls_id`: each identifies a person (an NMLS ID is public, but it names exactly one individual), so
they are excluded like `email` and the names.

Hand-written, like every migration against this schema.

Revision ID: c5874fbee899
Revises: 0a7332974687
Create Date: 2026-11-13 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5874fbee899"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "0a7332974687"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GRANT = """
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
            EXECUTE 'GRANT SELECT ON readonly.users TO mbai_readonly';
        END IF;
    END
    $$;
    """


def upgrade() -> None:
    op.add_column("users", sa.Column("phone", sa.String(length=32), nullable=True))
    op.add_column("users", sa.Column("title", sa.String(length=100), nullable=True))
    op.add_column("users", sa.Column("nmls_id", sa.String(length=16), nullable=True))
    op.add_column(
        "users",
        sa.Column("licensed_states", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("sees_all_loans", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("DROP VIEW IF EXISTS readonly.users")
    op.execute(
        """
        CREATE VIEW readonly.users AS
        SELECT id, company_id, is_active, default_aggression_level, density,
               title, licensed_states, sees_all_loans, last_login_at,
               created_at, updated_at, deleted_at
        FROM public.users
        """
    )
    op.execute(_GRANT)


def downgrade() -> None:
    # The previous definition is inside this function on purpose: the readonly drift guard reads
    # everything above `def downgrade(` as the live view.
    op.execute("DROP VIEW IF EXISTS readonly.users")
    op.execute(
        """
        CREATE VIEW readonly.users AS
        SELECT id, company_id, is_active, default_aggression_level, density,
               created_at, updated_at, deleted_at
        FROM public.users
        """
    )
    op.execute(_GRANT)
    op.execute(
        "ALTER TABLE users DROP COLUMN last_login_at, DROP COLUMN sees_all_loans, "
        "DROP COLUMN licensed_states, DROP COLUMN nmls_id, DROP COLUMN title, DROP COLUMN phone"
    )

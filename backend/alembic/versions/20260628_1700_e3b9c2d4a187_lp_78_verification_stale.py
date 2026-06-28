"""LP-78 loan_file.verification_stale (cross-source staleness flag)

Revision ID: e3b9c2d4a187
Revises: d2a8b6f10e93
Create Date: 2026-06-28 17:00:00.000000

Adds a non-null ``verification_stale`` boolean to ``loan_files`` (LP-78): whether
the cross-source verification is out of date (set on document change / when a
finding is applied; cleared when the pass re-runs). Server default ``false`` so
existing rows read as current.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e3b9c2d4a187"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "d2a8b6f10e93"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the non-null verification_stale column (server-default false)."""
    op.add_column(
        "loan_files",
        sa.Column(
            "verification_stale",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    """Drop the verification_stale column."""
    op.drop_column("loan_files", "verification_stale")

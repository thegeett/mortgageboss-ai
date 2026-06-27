"""LP-71.5 loan_file ai_needs_status

Revision ID: c3e8a1f49b27
Revises: a7f4c2e1b9d0
Create Date: 2026-06-24 10:15:00.000000

Adds a nullable ``ai_needs_status`` column to ``loan_files`` (LP-71.5): the visible
state of LP-69's async AI needs reasoning (``pending`` / ``completed`` / ``failed``;
NULL = not triggered). A bounded VARCHAR + CHECK (ADR-037). No data backfill — existing
files default to NULL (no AI reasoning state recorded yet).

The CHECK is added with raw SQL and the literal name the model's ``str_enum`` produces
(``ck_loan_files_aineedsstatus``) so a fresh ``create_all`` and this migration converge.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3e8a1f49b27"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "a7f4c2e1b9d0"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_loan_files_aineedsstatus"
_VALUES = ("pending", "completed", "failed")


def upgrade() -> None:
    """Add the nullable ai_needs_status column with its bounded CHECK."""
    op.add_column(
        "loan_files",
        sa.Column("ai_needs_status", sa.String(length=32), nullable=True),
    )
    joined = ", ".join(f"'{value}'" for value in _VALUES)
    op.execute(
        f"ALTER TABLE loan_files ADD CONSTRAINT {_CONSTRAINT} CHECK (ai_needs_status IN ({joined}))"
    )


def downgrade() -> None:
    """Drop the column (the CHECK goes with it)."""
    op.execute(f"ALTER TABLE loan_files DROP CONSTRAINT {_CONSTRAINT}")
    op.drop_column("loan_files", "ai_needs_status")

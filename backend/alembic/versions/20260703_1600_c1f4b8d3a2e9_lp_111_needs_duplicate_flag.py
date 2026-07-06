"""add needs_items duplicate-flag columns (LP-111)

Revision ID: c1f4b8d3a2e9
Revises: b7e3a9c2f1d8
Create Date: 2026-07-03 16:00:00.000000

LP-111 — needs consolidation. The deterministic layers (collapse-by-source, substance-identity)
merge certain duplicates outright; the AI layer only FLAGS the semantic residue for the processor to
confirm — never a silent delete. That flag needs two columns on ``needs_items``:

  * ``duplicate_of_id`` — self-referential FK: this proposed need looks like a duplicate of that one
    (SET NULL so removing the survivor doesn't strand the flag).
  * ``duplicate_reviewed`` — the processor has disposed of a flag (confirmed merge / kept both), so
    the AI pass never re-flags a pair the human already judged.

Both are additive; existing rows default to (null, false). No backfill.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1f4b8d3a2e9"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "b7e3a9c2f1d8"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the duplicate-flag columns + the self-FK + its index."""
    op.add_column(
        "needs_items",
        sa.Column("duplicate_reviewed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("needs_items", sa.Column("duplicate_of_id", sa.Uuid(), nullable=True))
    op.create_index(
        op.f("ix_needs_items_duplicate_of_id"), "needs_items", ["duplicate_of_id"], unique=False
    )
    op.create_foreign_key(
        op.f("fk_needs_items_duplicate_of_id_needs_items"),
        "needs_items",
        "needs_items",
        ["duplicate_of_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Drop the server_default now that existing rows are populated — the model default drives inserts.
    op.alter_column("needs_items", "duplicate_reviewed", server_default=None)


def downgrade() -> None:
    """Drop the duplicate-flag columns (+ FK + index)."""
    op.drop_constraint(
        op.f("fk_needs_items_duplicate_of_id_needs_items"), "needs_items", type_="foreignkey"
    )
    op.drop_index(op.f("ix_needs_items_duplicate_of_id"), table_name="needs_items")
    op.drop_column("needs_items", "duplicate_of_id")
    op.drop_column("needs_items", "duplicate_reviewed")

"""add needs_items.source_facts (LP-110)

Revision ID: b7e3a9c2f1d8
Revises: a2f5c8d1e4b6
Create Date: 2026-07-03 14:00:00.000000

LP-110 — every need shows its SOURCE (the specific data that triggered it), so the AI's reasoning
is FALSIFIABLE (the processor can verify a misread). Adds one nullable JSON column,
``needs_items.source_facts``, holding the per-origin structured triggering facts
(``[{"kind", "label", "ref"?}]``): a FLOOR need's deterministically-derived rule+data, or an
AI_REASONING need's cited FileContext facts. SUGGESTION needs continue to use the existing
``source_finding_id`` FK (unchanged). Nullable — existing rows have no captured source. No backfill.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7e3a9c2f1d8"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "a2f5c8d1e4b6"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable ``source_facts`` JSON column."""
    op.add_column("needs_items", sa.Column("source_facts", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Drop the ``source_facts`` column."""
    op.drop_column("needs_items", "source_facts")

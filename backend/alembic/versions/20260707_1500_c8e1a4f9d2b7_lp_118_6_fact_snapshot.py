"""LP-118.6 add verifications.fact_snapshot (the per-run fact namespace)

Revision ID: c8e1a4f9d2b7
Revises: d4b8f1a63c27
Create Date: 2026-07-07 15:00:00.000000

Adds one nullable JSON column, ``verifications.fact_snapshot`` (LP-118.6) — the assembled,
immutable, entity-addressable per-run fact namespace ("what the engine saw"): typed facts +
compute-once calculators + canonicalized categories, serialized as JSON. NOT a live key-value/EAV
table — one frozen record per run. Nullable — existing runs have none; the current LP-86 path does
not set it (the registry runner, LP-121, will). No backfill.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8e1a4f9d2b7"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "d4b8f1a63c27"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable ``fact_snapshot`` JSON column."""
    op.add_column("verifications", sa.Column("fact_snapshot", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Drop the ``fact_snapshot`` column."""
    op.drop_column("verifications", "fact_snapshot")

"""LP-65: add the document ``summary`` column (Tier 2 recognized-doc gist)

Revision ID: b344317498a5
Revises: f1ed01fc2713
Create Date: 2026-06-19 10:00:00.000000

Adds the nullable ``summary`` TEXT column to ``documents`` (LP-65): a short 1-2
sentence human-readable gist set by the Tier 2 shared summary path for *recognized*
documents (what the document is, for quick processor reference). It is NOT
structured data (that is the Tier 1 extraction). Nullable: Tier 1 docs and any doc
processed before this column existed keep ``NULL``, as do Tier 2 docs whose
summarization failed (forgiving — low stakes).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b344317498a5"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "f1ed01fc2713"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable ``summary`` TEXT column."""
    op.add_column("documents", sa.Column("summary", sa.Text(), nullable=True))


def downgrade() -> None:
    """Drop the ``summary`` column."""
    op.drop_column("documents", "summary")

"""add findings.source_document_ids (LP-114.1)

Revision ID: e5a9c3f7b2d1
Revises: c1f4b8d3a2e9
Create Date: 2026-07-04 12:00:00.000000

LP-114.1 — a cross-source finding is derived from MULTIPLE documents (an employer appears on a pay
stub AND a W-2; a discrepancy compares stated data against one-or-more documents), so its provenance
is a SET, not the single ``source_document_id`` LP-114 added. Adds one nullable JSON column,
``findings.source_document_ids`` (a JSON array of document-id strings), derived by value-matching the
finding's cited value(s) to every document that contains them. ``source_document_id`` stays as the
primary/trigger. Nullable; existing rows are backfilled by the run/backfill, not this migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5a9c3f7b2d1"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "c1f4b8d3a2e9"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable ``source_document_ids`` JSON column."""
    op.add_column("findings", sa.Column("source_document_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Drop the ``source_document_ids`` column."""
    op.drop_column("findings", "source_document_ids")

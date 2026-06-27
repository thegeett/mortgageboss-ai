"""LP-71 document versioning + staleness

Revision ID: d4b18c7af3e2
Revises: c3e8a1f49b27
Create Date: 2026-06-25 09:00:00.000000

Adds document-level versioning (Model C) + the staleness-resolution field to
``documents`` (LP-71):

  * ``version`` (int, default 1), ``is_current`` (bool, default true, indexed),
    ``version_group_id`` (uuid, nullable, indexed), ``supersedes_document_id``
    (uuid FK documents SET NULL) — the explicit-replace version chain.
  * ``staleness_resolution`` (VARCHAR + CHECK: waived / accepted; nullable) — the
    processor's resolution of a flagged-stale document.
  * ``possible_duplicate`` (bool, default false) — the email-ingest "possible
    duplicate" flag.

Existing rows backfill via server defaults (every existing document is a current,
standalone v1, not a possible duplicate). The server defaults are then dropped so the
ORM owns the defaults going forward (the booleans/int are model defaults).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4b18c7af3e2"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "c3e8a1f49b27"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STALENESS_CHECK = "ck_documents_stalenessresolution"


def upgrade() -> None:
    """Add the versioning + staleness columns (server defaults backfill existing rows)."""
    op.add_column(
        "documents",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "documents",
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("documents", sa.Column("version_group_id", sa.Uuid(), nullable=True))
    op.add_column("documents", sa.Column("supersedes_document_id", sa.Uuid(), nullable=True))
    op.add_column(
        "documents", sa.Column("staleness_resolution", sa.String(length=32), nullable=True)
    )
    op.add_column(
        "documents",
        sa.Column("possible_duplicate", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_index("ix_documents_is_current", "documents", ["is_current"])
    op.create_index("ix_documents_version_group_id", "documents", ["version_group_id"])
    op.create_foreign_key(
        "fk_documents_supersedes_document_id_documents",
        "documents",
        "documents",
        ["supersedes_document_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        f"ALTER TABLE documents ADD CONSTRAINT {_STALENESS_CHECK} "
        f"CHECK (staleness_resolution IN ('waived', 'accepted'))"
    )

    # Drop the server defaults — the ORM owns the defaults from here (existing rows
    # are already backfilled).
    op.alter_column("documents", "version", server_default=None)
    op.alter_column("documents", "is_current", server_default=None)
    op.alter_column("documents", "possible_duplicate", server_default=None)


def downgrade() -> None:
    """Drop the versioning + staleness columns (and their constraints/indexes)."""
    op.execute(f"ALTER TABLE documents DROP CONSTRAINT {_STALENESS_CHECK}")
    op.drop_constraint(
        "fk_documents_supersedes_document_id_documents", "documents", type_="foreignkey"
    )
    op.drop_index("ix_documents_version_group_id", table_name="documents")
    op.drop_index("ix_documents_is_current", table_name="documents")
    op.drop_column("documents", "possible_duplicate")
    op.drop_column("documents", "staleness_resolution")
    op.drop_column("documents", "supersedes_document_id")
    op.drop_column("documents", "version_group_id")
    op.drop_column("documents", "is_current")
    op.drop_column("documents", "version")

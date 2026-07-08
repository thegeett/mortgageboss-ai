"""LP-118.8 borrower<->document links + documents.borrower_match_note

Revision ID: f3a9c2d5e8b1
Revises: e2d5b8c1f4a9
Create Date: 2026-07-07 19:00:00.000000

Adds the borrower↔document association (LP-118.8): a ``document_borrower_links`` table (one row per
confident (document, borrower) match — a link table so a JOINT document can belong to multiple
borrowers, with ``confidence`` + ``method`` provenance), and a nullable
``documents.borrower_match_note`` recording WHY a document was left unassigned (no_name / no_match /
ambiguous). Nullable + additive; no backfill (the matcher populates on its next run).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3a9c2d5e8b1"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "e2d5b8c1f4a9"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create document_borrower_links + add documents.borrower_match_note."""
    op.add_column(
        "documents", sa.Column("borrower_match_note", sa.String(length=64), nullable=True)
    )
    op.create_table(
        "document_borrower_links",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("borrower_id", sa.Uuid(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("method", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_borrower_links_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["borrower_id"],
            ["borrowers.id"],
            name=op.f("fk_document_borrower_links_borrower_id_borrowers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_borrower_links")),
        sa.UniqueConstraint(
            "document_id", "borrower_id", name="uq_document_borrower_links_document_borrower"
        ),
    )
    op.create_index(
        op.f("ix_document_borrower_links_document_id"),
        "document_borrower_links",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_document_borrower_links_borrower_id"),
        "document_borrower_links",
        ["borrower_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop the link table + the note column."""
    op.drop_index(
        op.f("ix_document_borrower_links_borrower_id"), table_name="document_borrower_links"
    )
    op.drop_index(
        op.f("ix_document_borrower_links_document_id"), table_name="document_borrower_links"
    )
    op.drop_table("document_borrower_links")
    op.drop_column("documents", "borrower_match_note")

"""create document_borrower_links (LP-202)

Revision ID: b3f8d2c6a941
Revises: a7c2e5f9d1b4
Create Date: 2026-07-09 17:00:00.000000

LP-202 — a deterministic document→borrower link table (ADR-239). One row per
(document, borrower) pair a name-matcher resolved; supports many borrowers per
document (joint statements). No-match documents produce zero rows. Owned child of
the document (CASCADE); UNIQUE (document_id, borrower_id).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3f8d2c6a941"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "a7c2e5f9d1b4"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the document_borrower_links table."""
    op.create_table(
        "document_borrower_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("borrower_id", sa.Uuid(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("method", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["borrower_id"], ["borrowers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id", "borrower_id", name="uq_document_borrower_links_document_borrower"
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_document_borrower_links_confidence_range",
        ),
    )
    op.create_index(
        "ix_document_borrower_links_document_id", "document_borrower_links", ["document_id"]
    )
    op.create_index(
        "ix_document_borrower_links_borrower_id", "document_borrower_links", ["borrower_id"]
    )


def downgrade() -> None:
    """Drop the document_borrower_links table."""
    op.drop_index("ix_document_borrower_links_borrower_id", table_name="document_borrower_links")
    op.drop_index("ix_document_borrower_links_document_id", table_name="document_borrower_links")
    op.drop_table("document_borrower_links")

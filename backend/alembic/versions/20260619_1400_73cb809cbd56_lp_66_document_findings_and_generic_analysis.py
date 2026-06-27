"""LP-66: document_findings table + Tier 3 generic-analysis / full-text columns

Revision ID: 73cb809cbd56
Revises: b344317498a5
Create Date: 2026-06-19 14:00:00.000000

Two changes for LP-66 (Tier 3 generic analyzer + the findings infrastructure):

  1. Create ``document_findings`` — single-document observations (obligation /
     property_interest / income_related / discrepancy_candidate / other) recorded
     uniformly by the Tier 3 analyzer AND the Tier 1 divorce-decree wiring.
     Tenant-scoped via ``document_id -> documents -> loan_files -> companies``
     (no own ``company_id``). Distinct from the Phase 3 verification ``findings``
     table (a different model).
  2. Add ``generic_analysis`` (JSON) + ``full_text`` (Text) to ``documents`` for
     the Tier 3 analyzer output + the searchable text, plus a **GIN full-text
     index** on ``to_tsvector('english', full_text)`` (the data + index; the
     search UI is future).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "73cb809cbd56"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "b344317498a5"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FTS_INDEX = "ix_documents_full_text_fts"


def upgrade() -> None:
    """Create document_findings + add the Tier 3 columns + the full-text index."""
    op.create_table(
        "document_findings",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column(
            "finding_type",
            sa.Enum(
                "obligation",
                "property_interest",
                "income_related",
                "discrepancy_candidate",
                "other",
                name="documentfindingtype",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("frequency", sa.String(length=64), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "open",
                "reviewed",
                "dismissed",
                name="documentfindingstatus",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_findings_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_findings")),
    )
    op.create_index(
        op.f("ix_document_findings_document_id"), "document_findings", ["document_id"], unique=False
    )
    op.create_index(
        op.f("ix_document_findings_finding_type"),
        "document_findings",
        ["finding_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_document_findings_status"), "document_findings", ["status"], unique=False
    )

    # --- Tier 3 analyzer output + searchable text on documents -------------- #
    op.add_column("documents", sa.Column("generic_analysis", sa.JSON(), nullable=True))
    op.add_column("documents", sa.Column("full_text", sa.Text(), nullable=True))
    # A GIN full-text index over the document's text (Tier 3 docs can't be found by
    # type, so full-text search matters most for them). Data + index now; UI later.
    op.create_index(
        _FTS_INDEX,
        "documents",
        [sa.text("to_tsvector('english', coalesce(full_text, ''))")],
        postgresql_using="gin",
    )


def downgrade() -> None:
    """Drop the full-text index + the Tier 3 columns + the document_findings table."""
    op.drop_index(_FTS_INDEX, table_name="documents")
    op.drop_column("documents", "full_text")
    op.drop_column("documents", "generic_analysis")
    op.drop_index(op.f("ix_document_findings_status"), table_name="document_findings")
    op.drop_index(op.f("ix_document_findings_finding_type"), table_name="document_findings")
    op.drop_index(op.f("ix_document_findings_document_id"), table_name="document_findings")
    op.drop_table("document_findings")

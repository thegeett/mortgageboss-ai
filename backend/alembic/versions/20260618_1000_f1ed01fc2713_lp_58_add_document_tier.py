"""LP-58: add the document ``tier`` column (three-tier model)

Revision ID: f1ed01fc2713
Revises: 2680568f49c9
Create Date: 2026-06-18 10:00:00.000000

Adds the nullable ``tier`` column to ``documents`` (LP-58): the level-of-investment
tier a document was handled as (``tier_1`` / ``tier_2`` / ``tier_3``), set from the
document-type catalog during classification. Stored as a VARCHAR + CHECK
(``ck_documents_tier``) like every other enum here (native_enum=False, ADR-037) so
the small stable tier set is DB-enforced. The document_type → tier MAPPING is not
in the DB — it lives in ``app/documents/catalog.py`` (the single source of truth).

Nullable: existing rows (classified before this column existed) keep ``NULL``
until reprocessed; the pipeline sets it on every future classification.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1ed01fc2713"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "2680568f49c9"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the ``tier`` VARCHAR + CHECK column (nullable)."""
    op.add_column(
        "documents",
        sa.Column(
            "tier",
            sa.Enum(
                "tier_1",
                "tier_2",
                "tier_3",
                name="tier",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Drop the ``tier`` column (its CHECK constraint goes with it)."""
    op.drop_column("documents", "tier")

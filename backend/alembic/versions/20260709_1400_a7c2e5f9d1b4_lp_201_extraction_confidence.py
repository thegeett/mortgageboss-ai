"""add extractions.confidence + confidence_source (LP-201)

Revision ID: a7c2e5f9d1b4
Revises: e5a9c3f7b2d1
Create Date: 2026-07-09 14:00:00.000000

LP-201 — per-field extraction confidence. Per-field confidence rides inside the
existing ``extracted_data`` JSON (additive keys, no column). This migration adds
the two nullable columns that persist the model's DOCUMENT-level self-reported
confidence — which was computed today but dropped at storage: ``confidence``
(float, 0..1) and ``confidence_source`` (a CHECK-constrained enum —
``model_self_reported`` / ``not_provided`` — so a defaulted 0.0 can never be
mislabelled as a genuine model rating). Both nullable, no backfill — existing rows
stay NULL (an honest "not recorded"), never a fabricated default.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c2e5f9d1b4"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "e5a9c3f7b2d1"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable document-level ``confidence`` + ``confidence_source`` columns."""
    op.add_column("extractions", sa.Column("confidence", sa.Float(), nullable=True))
    op.add_column(
        "extractions",
        sa.Column(
            # CHECK-constrained VARCHAR (native_enum=False, ADR-037) matching the
            # ``ConfidenceSource`` StrEnum — a defaulted 0.0 can never be persisted
            # under a bogus source, and the vocabulary can't silently drift.
            "confidence_source",
            sa.Enum(
                "model_self_reported",
                "not_provided",
                name="confidencesource",
                native_enum=False,
                create_constraint=True,
                length=64,
            ),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Drop the confidence columns."""
    op.drop_column("extractions", "confidence_source")
    op.drop_column("extractions", "confidence")

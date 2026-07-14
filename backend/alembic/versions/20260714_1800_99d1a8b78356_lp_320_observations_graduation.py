"""LP-320 observation channel + graduation log

Revision ID: 99d1a8b78356
Revises: a3d7f1e9c2b5
Create Date: 2026-07-14 18:00:00.000000

Two tables for the unbounded-real-world safety channel (§3D / §7):

* ``observations`` — a structured, schemaless record of a document/fact OUTSIDE the tag vocabulary.
  File-owned (CASCADE on the loan file), append-only. ``relates_to_finding_id`` attaches it to a
  finding for human review (SET NULL on finding delete — the observation OUTLIVES the finding; it is
  discovery data, not the finding's child). The rule engine never reads this table, so an observation
  can never resolve a finding.
* ``graduation_candidates`` — a PII-safe tally of recurring observation TYPES (unique normalized
  ``signature``), ranked by ``occurrences`` to rank which unknowns to formalize next. Type + count +
  timestamps only — no raw values — so it is safe as a system-wide signal.

Names use the model naming convention so a fresh ``create_all`` and this migration converge.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "99d1a8b78356"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "a3d7f1e9c2b5"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create observations + graduation_candidates."""
    op.create_table(
        "observations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("loan_file_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("about", sa.String(length=256), nullable=False),
        sa.Column("observation_type", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("structured", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("relates_to_finding_id", sa.Uuid(), nullable=True),
        sa.Column("relates_to_subject", sa.String(length=256), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("produced_by", sa.String(length=64), nullable=False),
        sa.Column("needs_tag", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["loan_file_id"],
            ["loan_files.id"],
            name=op.f("fk_observations_loan_file_id_loan_files"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["relates_to_finding_id"],
            ["findings.id"],
            name=op.f("fk_observations_relates_to_finding_id_findings"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_observations")),
    )
    op.create_index("ix_observations_loan_file", "observations", ["loan_file_id"])
    op.create_index("ix_observations_relates_to_finding", "observations", ["relates_to_finding_id"])
    op.create_index("ix_observations_type", "observations", ["observation_type"])

    op.create_table(
        "graduation_candidates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("signature", sa.String(length=256), nullable=False),
        sa.Column("observation_type", sa.String(length=64), nullable=False),
        sa.Column("occurrences", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_graduation_candidates")),
        sa.UniqueConstraint("signature", name=op.f("uq_graduation_candidates_signature")),
    )


def downgrade() -> None:
    """Drop graduation_candidates + observations."""
    op.drop_table("graduation_candidates")
    op.drop_index("ix_observations_type", table_name="observations")
    op.drop_index("ix_observations_relates_to_finding", table_name="observations")
    op.drop_index("ix_observations_loan_file", table_name="observations")
    op.drop_table("observations")

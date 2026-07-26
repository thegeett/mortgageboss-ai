"""create snapshot_records (LP-209)

Revision ID: c4e9a7f2b8d3
Revises: b3f8d2c6a941
Create Date: 2026-07-10 12:00:00.000000

LP-209 — the immutable per-run snapshot at rest (ADR-246). One row per run holds the
full LP-204 Snapshot as a single JSONB blob (``snapshot_json``), not shredded. The
row is append-only: no ``updated_at``, no soft-delete; ``run_id`` is UNIQUE (one
snapshot per run) and a bare UUID (not a FK to ``verifications`` — the builder
receives run_id and never mints it from a verification row). ``loan_file_id`` is an
indexed FK to the owning loan file (CASCADE, ADR-052). Immutability is enforced in
code (insert-only write path; no update method) — there is no DB-level append-only
trigger/REVOKE pattern in this repo to reuse.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c4e9a7f2b8d3"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "b3f8d2c6a941"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the immutable snapshot_records table."""
    op.create_table(
        "snapshot_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("loan_file_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot_version", sa.Integer(), nullable=False),
        sa.Column("snapshot_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["loan_file_id"], ["loan_files.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uq_snapshot_records_run_id"),
    )
    op.create_index("ix_snapshot_records_loan_file_id", "snapshot_records", ["loan_file_id"])


def downgrade() -> None:
    """Drop the snapshot_records table."""
    op.drop_index("ix_snapshot_records_loan_file_id", table_name="snapshot_records")
    op.drop_table("snapshot_records")

"""LP-644 §3 — persist the per-file AI tag caches across runs.

Adds ``tag_cache_entries``. Additive only: one new table, nothing existing is touched.

⚠️ HAND-TRIMMED, AND THAT MATTERED. `alembic revision --autogenerate` also produced
``op.drop_table('finding_prose')``, a drop of the documents FTS index, and a dozen `alter_column`
type changes across `validation_verdicts`, `needs_items` and `verifications` — pre-existing drift
between the models and this database, none of it related to this ticket. Shipping the generated file
would have DROPPED A TABLE as a side effect of adding a cache. Everything but the `create_table` and
its indexes was removed by hand; the drift is real and belongs in its own ticket, where it can be
reviewed as the schema change it is rather than smuggled in as a footnote.

Revision ID: a1c8734a7978
Revises: c8b1e47da920
Create Date: 2026-09-05 09:27:52.119916
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1c8734a7978"
down_revision: str | Sequence[str] | None = "c8b1e47da920"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tag_cache_entries",
        sa.Column("loan_file_id", sa.Uuid(), nullable=False),
        sa.Column("cache_kind", sa.String(length=32), nullable=False),
        sa.Column("cache_key", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("hit_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # CASCADE: a cache entry is meaningless without its loan file, and leaving orphans behind
        # would be a slow leak in a table whose whole purpose is to stay bounded.
        sa.ForeignKeyConstraint(
            ["loan_file_id"],
            ["loan_files.id"],
            name=op.f("fk_tag_cache_entries_loan_file_id_loan_files"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tag_cache_entries")),
    )
    op.create_index(
        op.f("ix_tag_cache_entries_loan_file_id"),
        "tag_cache_entries",
        ["loan_file_id"],
        unique=False,
    )
    # Eviction reads this: oldest-first within a (file, kind).
    op.create_index(
        "ix_tag_cache_file_kind_created",
        "tag_cache_entries",
        ["loan_file_id", "cache_kind", "created_at"],
        unique=False,
    )
    # The lookup AND the identity — the save path's upsert conflict target.
    op.create_index(
        "uq_tag_cache_file_kind_key",
        "tag_cache_entries",
        ["loan_file_id", "cache_kind", "cache_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_tag_cache_file_kind_key", table_name="tag_cache_entries")
    op.drop_index("ix_tag_cache_file_kind_created", table_name="tag_cache_entries")
    op.drop_index(op.f("ix_tag_cache_entries_loan_file_id"), table_name="tag_cache_entries")
    op.drop_table("tag_cache_entries")

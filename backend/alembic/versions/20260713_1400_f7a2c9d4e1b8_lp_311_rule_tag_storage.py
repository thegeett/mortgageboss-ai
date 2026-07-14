"""LP-311 rule + tag storage — projection tables; retire phase3_5_1 orphans

Revision ID: f7a2c9d4e1b8
Revises: c4e9a7f2b8d3
Create Date: 2026-07-13 14:00:00.000000

Creates the four GLOBAL (un-scoped) projection tables for the fact-tag architecture
(LP-311, ADR-249): ``rules`` (from rule_kinds.csv + specs/*.yaml), ``tags`` (the fact-
tag vocabulary), ``rule_tags`` (rule -> required-tag edges) and ``tag_dependencies``
(the tag DAG). These are a QUERYABLE PROJECTION of the version-controlled files; the
LP-311 loader populates and reconciles them (this migration only builds the schema).

Also RETIRES the abandoned phase3_5_1 rule registry (LP-118 / ADR-238): ``verification_rules``
and ``rule_change_audits``. Those tables are not part of this branch's Alembic history
(their creating migration lives only on the abandoned branch), but a dev DB that was
migrated on phase3_5_1 and then switched here still carries them as ORPHANS. Dropping
them here makes a migrated dev DB converge with a fresh one. The drop is ``IF EXISTS``
so it is a no-op on a fresh database. ``downgrade`` deliberately does NOT recreate them
(they were never part of this branch's schema).

Constraint/index names match the models so a fresh ``create_all`` and this migration
converge. No fork/merge migration is needed: on this branch ``alembic heads`` is the
single head ``c4e9a7f2b8d3`` (the LP-118 revision is absent here).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f7a2c9d4e1b8"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "c4e9a7f2b8d3"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Retire the phase3_5_1 orphans, then build the four projection tables."""
    # --- Retire the abandoned phase3_5_1 rule registry (orphans on a dirty dev DB) --- #
    # rule_change_audits FKs verification_rules; CASCADE + IF EXISTS covers both orders
    # and is a no-op on a fresh database.
    op.execute("DROP TABLE IF EXISTS rule_change_audits CASCADE")
    op.execute("DROP TABLE IF EXISTS verification_rules CASCADE")

    # --- rules ---------------------------------------------------------------- #
    op.create_table(
        "rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("evaluation_path", sa.String(length=64), nullable=True),
        sa.Column("numeric_check", sa.Boolean(), nullable=False),
        sa.Column("exact_match", sa.Boolean(), nullable=True),
        sa.Column("priya_validated", sa.Boolean(), nullable=False),
        sa.Column("threshold_needs_signoff", sa.Boolean(), nullable=False),
        sa.Column("rationale", sa.String(length=1024), nullable=True),
        sa.Column("spec", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rules")),
        sa.UniqueConstraint("rule_id", name="uq_rules_rule_id"),
    )

    # --- tags ----------------------------------------------------------------- #
    op.create_table(
        "tags",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tag_id", sa.String(length=64), nullable=False),
        sa.Column("entity", sa.String(length=64), nullable=False),
        sa.Column("value_type", sa.String(length=64), nullable=False),
        sa.Column("allowed_values", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("produced_by", sa.String(length=64), nullable=False),
        sa.Column("tag_role", sa.String(length=64), nullable=True),
        sa.Column("tag_version", sa.Integer(), nullable=False),
        sa.Column("extras", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tags")),
        sa.UniqueConstraint("tag_id", name="uq_tags_tag_id"),
    )

    # --- rule_tags (rule -> required tag) ------------------------------------- #
    op.create_table(
        "rule_tags",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.String(length=64), nullable=False),
        sa.Column("tag_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["rules.rule_id"],
            name=op.f("fk_rule_tags_rule_id_rules"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["tags.tag_id"],
            name=op.f("fk_rule_tags_tag_id_tags"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rule_tags")),
        sa.UniqueConstraint("rule_id", "tag_id", name="uq_rule_tags_rule_id_tag_id"),
    )
    op.create_index(op.f("ix_rule_tags_rule_id"), "rule_tags", ["rule_id"], unique=False)
    op.create_index(op.f("ix_rule_tags_tag_id"), "rule_tags", ["tag_id"], unique=False)

    # --- tag_dependencies (tag -> depends-on tag, the DAG) -------------------- #
    op.create_table(
        "tag_dependencies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tag_id", sa.String(length=64), nullable=False),
        sa.Column("depends_on_tag_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["tags.tag_id"],
            name=op.f("fk_tag_dependencies_tag_id_tags"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["depends_on_tag_id"],
            ["tags.tag_id"],
            name=op.f("fk_tag_dependencies_depends_on_tag_id_tags"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tag_dependencies")),
        sa.UniqueConstraint(
            "tag_id",
            "depends_on_tag_id",
            name="uq_tag_dependencies_tag_id_depends_on_tag_id",
        ),
    )
    op.create_index(
        op.f("ix_tag_dependencies_tag_id"), "tag_dependencies", ["tag_id"], unique=False
    )
    op.create_index(
        op.f("ix_tag_dependencies_depends_on_tag_id"),
        "tag_dependencies",
        ["depends_on_tag_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop the four projection tables (FK-safe order).

    Does NOT recreate ``verification_rules`` / ``rule_change_audits`` — they were
    never part of this branch's schema (see the module docstring).
    """
    op.drop_index(op.f("ix_tag_dependencies_depends_on_tag_id"), table_name="tag_dependencies")
    op.drop_index(op.f("ix_tag_dependencies_tag_id"), table_name="tag_dependencies")
    op.drop_table("tag_dependencies")
    op.drop_index(op.f("ix_rule_tags_tag_id"), table_name="rule_tags")
    op.drop_index(op.f("ix_rule_tags_rule_id"), table_name="rule_tags")
    op.drop_table("rule_tags")
    op.drop_table("tags")
    op.drop_table("rules")

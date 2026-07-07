"""LP-118 rule registry — verification_rules + rule_change_audits (hybrid storage)

Revision ID: d4b8f1a63c27
Revises: e5a9c3f7b2d1
Create Date: 2026-07-07 12:00:00.000000

Creates the data-driven rule storage foundation (LP-118): the ``verification_rules``
table (rule_id PK, playbook_id, structural + tunable fields) and the ``rule_change_audits``
table (the compliance change history). Then POPULATES ``verification_rules`` from the
version-controlled seed (``docs/rules/rule_seed.json`` — the authoring source of truth),
recording each insert in ``rule_change_audits`` with ``change_source="seed_migration"``.

Nothing executes a rule here — the applicability filter (LP-119), evaluators (LP-120),
runner wiring (LP-121), and admin UI (LP-122) are later tickets. The live verification
path is unchanged. Constraint/index names match the models so a fresh ``create_all`` and
this migration converge.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.services.rule_registry import seed_verification_rules

# revision identifiers, used by Alembic.
revision: str = "d4b8f1a63c27"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "e5a9c3f7b2d1"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create both tables, then seed verification_rules (auditing each insert)."""
    op.create_table(
        "verification_rules",
        sa.Column("rule_id", sa.Text(), nullable=False),
        sa.Column("playbook_id", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("layer", sa.String(length=64), nullable=True),
        sa.Column("evaluator", sa.String(length=64), nullable=True),
        sa.Column("applicability", sa.JSON(), nullable=True),
        sa.Column("canonical_type", sa.String(length=64), nullable=True),
        sa.Column("message_template", sa.Text(), nullable=True),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("severity", sa.String(length=64), nullable=True),
        sa.Column("confidence_mode", sa.String(length=64), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=True),
        sa.Column("scope", sa.String(length=64), nullable=True),
        sa.Column("validated", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("rule_id", name=op.f("pk_verification_rules")),
    )
    op.create_index(
        op.f("ix_verification_rules_playbook_id"),
        "verification_rules",
        ["playbook_id"],
        unique=False,
    )
    op.create_table(
        "rule_change_audits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Text(), nullable=False),
        sa.Column("changed_field", sa.String(length=64), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("change_source", sa.String(length=64), nullable=False),
        sa.Column("changed_by", sa.Uuid(), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["verification_rules.rule_id"],
            name=op.f("fk_rule_change_audits_rule_id_verification_rules"),
        ),
        sa.ForeignKeyConstraint(
            ["changed_by"],
            ["users.id"],
            name=op.f("fk_rule_change_audits_changed_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rule_change_audits")),
    )
    op.create_index(
        op.f("ix_rule_change_audits_rule_id"),
        "rule_change_audits",
        ["rule_id"],
        unique=False,
    )

    # Populate verification_rules from the version-controlled seed, auditing each insert.
    seed_verification_rules(op.get_bind())


def downgrade() -> None:
    """Drop both tables (the audit rows go with them)."""
    op.drop_index(op.f("ix_rule_change_audits_rule_id"), table_name="rule_change_audits")
    op.drop_table("rule_change_audits")
    op.drop_index(op.f("ix_verification_rules_playbook_id"), table_name="verification_rules")
    op.drop_table("verification_rules")

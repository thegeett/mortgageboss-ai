"""LP-87 calculator_overrides table + calculator_overridden / lender_overlay_updated types

Revision ID: e3c9a1f5b2d7
Revises: b7f2c1d4e890
Create Date: 2026-06-29 16:00:00.000000

Creates the ``calculator_overrides`` table (LP-87): one shared, calculator-discriminated
override table for the four new calculators (mortgage insurance, self-employed income,
reserves, max loan) — one active row per ``(loan_file_id, calculator, field_key)``; clearing
soft-deletes (the LP-76/77 semantics). Also widens the ``activity_logs`` type CHECK to add
``calculator_overridden`` (the audited calculator override) and ``lender_overlay_updated``
(the admin overlay edit). Constraint/index names match the models so a fresh ``create_all``
and this migration converge.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e3c9a1f5b2d7"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "b7f2c1d4e890"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACTIVITY_CONSTRAINT = "ck_activity_logs_activitytype"
_ACTIVITY_BASE = (
    "file_created",
    "file_updated",
    "file_deleted",
    "status_changed",
    "document_uploaded",
    "document_processed",
    "document_type_overridden",
    "document_replaced",
    "document_staleness_resolved",
    "finding_resolved",
    "verification_run",
    "dti_overridden",
    "ltv_overridden",
    "needs_item_created",
    "needs_item_satisfied",
    "needs_item_confirmed",
    "needs_item_adjusted",
    "needs_item_dismissed",
    "needs_item_waived",
    "communication_sent",
    "communication_received",
    "note_added",
)
_ACTIVITY_NEW = (*_ACTIVITY_BASE, "calculator_overridden", "lender_overlay_updated")


def _swap_activity_check(values: tuple[str, ...]) -> None:
    joined = ", ".join(f"'{value}'" for value in values)
    op.execute(f"ALTER TABLE activity_logs DROP CONSTRAINT {_ACTIVITY_CONSTRAINT}")
    op.execute(
        f"ALTER TABLE activity_logs ADD CONSTRAINT {_ACTIVITY_CONSTRAINT} "
        f"CHECK (activity_type IN ({joined}))"
    )


def upgrade() -> None:
    """Create calculator_overrides and add the two new activity types."""
    op.create_table(
        "calculator_overrides",
        sa.Column("loan_file_id", sa.Uuid(), nullable=False),
        sa.Column("calculator", sa.String(length=64), nullable=False),
        sa.Column("field_key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["loan_file_id"],
            ["loan_files.id"],
            name=op.f("fk_calculator_overrides_loan_file_id_loan_files"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_calculator_overrides_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calculator_overrides")),
        sa.UniqueConstraint(
            "loan_file_id",
            "calculator",
            "field_key",
            name="uq_calculator_overrides_file_calc_field",
        ),
    )
    op.create_index(
        op.f("ix_calculator_overrides_loan_file_id"),
        "calculator_overrides",
        ["loan_file_id"],
        unique=False,
    )
    _swap_activity_check(_ACTIVITY_NEW)


def downgrade() -> None:
    """Drop the two activity types and the calculator_overrides table."""
    _swap_activity_check(_ACTIVITY_BASE)
    op.drop_index(op.f("ix_calculator_overrides_loan_file_id"), table_name="calculator_overrides")
    op.drop_table("calculator_overrides")

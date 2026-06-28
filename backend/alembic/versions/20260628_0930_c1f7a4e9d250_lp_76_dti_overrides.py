"""LP-76 DTI overrides table + dti_overridden activity type

Revision ID: c1f7a4e9d250
Revises: b8d3f06a1c54
Create Date: 2026-06-28 09:30:00.000000

Creates the ``dti_overrides`` table (LP-76): a processor's per-field override of a
DTI calculator input (one active row per ``(loan_file_id, field_key)``; clearing
soft-deletes). Also widens the ``activity_logs`` type CHECK (constraint-swap) to
add ``dti_overridden`` — the audited override event. Constraint/index names match
what the models produce so a fresh ``create_all`` and this migration converge.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1f7a4e9d250"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "b8d3f06a1c54"  # pragma: allowlist secret
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
_ACTIVITY_NEW = (*_ACTIVITY_BASE, "dti_overridden")


def _swap_activity_check(values: tuple[str, ...]) -> None:
    joined = ", ".join(f"'{value}'" for value in values)
    op.execute(f"ALTER TABLE activity_logs DROP CONSTRAINT {_ACTIVITY_CONSTRAINT}")
    op.execute(
        f"ALTER TABLE activity_logs ADD CONSTRAINT {_ACTIVITY_CONSTRAINT} "
        f"CHECK (activity_type IN ({joined}))"
    )


def upgrade() -> None:
    """Create dti_overrides and add the dti_overridden activity type."""
    op.create_table(
        "dti_overrides",
        sa.Column("loan_file_id", sa.Uuid(), nullable=False),
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
            name=op.f("fk_dti_overrides_loan_file_id_loan_files"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_dti_overrides_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dti_overrides")),
        sa.UniqueConstraint(
            "loan_file_id", "field_key", name="uq_dti_overrides_loan_file_id_field_key"
        ),
    )
    op.create_index(
        op.f("ix_dti_overrides_loan_file_id"), "dti_overrides", ["loan_file_id"], unique=False
    )
    _swap_activity_check(_ACTIVITY_NEW)


def downgrade() -> None:
    """Drop the dti_overridden activity type and the dti_overrides table."""
    _swap_activity_check(_ACTIVITY_BASE)
    op.drop_index(op.f("ix_dti_overrides_loan_file_id"), table_name="dti_overrides")
    op.drop_table("dti_overrides")

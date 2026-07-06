"""LP-77 LTV calculator — ltv_overrides, refinance_type, ltv_overridden activity

Revision ID: d2a8b6f10e93
Revises: c1f7a4e9d250
Create Date: 2026-06-28 15:00:00.000000

Adds the LTV calculator's persistence (LP-77):

* ``ltv_overrides`` — a processor's per-field override of an LTV input (mirrors
  ``dti_overrides``; one active row per ``(loan_file_id, field_key)``).
* ``loan_files.refinance_type`` — the refinance kind (``rate_term`` / ``cash_out``;
  null for a purchase), a bounded VARCHAR + CHECK, which drives the LTV denominator
  + limit.
* widens the ``activity_logs`` type CHECK to add ``ltv_overridden`` (the audited
  override event).

Constraint/index names match what the models produce so a fresh ``create_all`` and
this migration converge.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d2a8b6f10e93"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "c1f7a4e9d250"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REFI_CONSTRAINT = "ck_loan_files_refinancetype"
_REFI_VALUES = ("rate_term", "cash_out")

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
_ACTIVITY_NEW = (*_ACTIVITY_BASE, "ltv_overridden")


def _swap_activity_check(values: tuple[str, ...]) -> None:
    joined = ", ".join(f"'{value}'" for value in values)
    op.execute(f"ALTER TABLE activity_logs DROP CONSTRAINT {_ACTIVITY_CONSTRAINT}")
    op.execute(
        f"ALTER TABLE activity_logs ADD CONSTRAINT {_ACTIVITY_CONSTRAINT} "
        f"CHECK (activity_type IN ({joined}))"
    )


def upgrade() -> None:
    """Create ltv_overrides, add refinance_type + the ltv_overridden activity type."""
    op.create_table(
        "ltv_overrides",
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
            name=op.f("fk_ltv_overrides_loan_file_id_loan_files"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_ltv_overrides_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ltv_overrides")),
        sa.UniqueConstraint(
            "loan_file_id", "field_key", name="uq_ltv_overrides_loan_file_id_field_key"
        ),
    )
    op.create_index(
        op.f("ix_ltv_overrides_loan_file_id"), "ltv_overrides", ["loan_file_id"], unique=False
    )

    op.add_column("loan_files", sa.Column("refinance_type", sa.String(length=32), nullable=True))
    joined = ", ".join(f"'{value}'" for value in _REFI_VALUES)
    op.execute(
        f"ALTER TABLE loan_files ADD CONSTRAINT {_REFI_CONSTRAINT} "
        f"CHECK (refinance_type IN ({joined}))"
    )

    _swap_activity_check(_ACTIVITY_NEW)


def downgrade() -> None:
    """Revert the activity type, drop refinance_type and ltv_overrides."""
    _swap_activity_check(_ACTIVITY_BASE)
    op.execute(f"ALTER TABLE loan_files DROP CONSTRAINT {_REFI_CONSTRAINT}")
    op.drop_column("loan_files", "refinance_type")
    op.drop_index(op.f("ix_ltv_overrides_loan_file_id"), table_name="ltv_overrides")
    op.drop_table("ltv_overrides")

"""add finding_undone activity type (LP-98)

Revision ID: a2f5c8d1e4b6
Revises: f4d1a7c0e2b9
Create Date: 2026-07-01 12:00:00.000000

Adds one value to the ``activity_type`` enum (LP-98): ``finding_undone``, so an Undo of a
resolved finding (reverse Apply/Accept/Override) is audited with a semantically-correct type.
The enum is a VARCHAR + CHECK (ADR-037), so this is a constraint swap — drop the
``ck_activity_logs_activitytype`` CHECK and recreate it with the expanded value set. No data
changes.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a2f5c8d1e4b6"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "f4d1a7c0e2b9"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_activity_logs_activitytype"

# The full enum value set, in model-definition order, with the new value (finding_undone) right
# after finding_resolved.
_NEW_VALUES = (
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
    "finding_undone",
    "verification_run",
    "dti_overridden",
    "ltv_overridden",
    "calculator_overridden",
    "lender_overlay_updated",
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

# The original set (without the new value) for downgrade.
_OLD_VALUES = tuple(v for v in _NEW_VALUES if v != "finding_undone")


def _swap_check(values: tuple[str, ...]) -> None:
    """Drop and recreate the activity_type CHECK with ``values`` (literal constraint name)."""
    joined = ", ".join(f"'{value}'" for value in values)
    op.execute(f"ALTER TABLE activity_logs DROP CONSTRAINT {_CONSTRAINT}")
    op.execute(
        f"ALTER TABLE activity_logs ADD CONSTRAINT {_CONSTRAINT} "
        f"CHECK (activity_type IN ({joined}))"
    )


def upgrade() -> None:
    """Replace the activity_type CHECK with the expanded value set."""
    _swap_check(_NEW_VALUES)


def downgrade() -> None:
    """Restore the activity_type CHECK to the original value set."""
    _swap_check(_OLD_VALUES)

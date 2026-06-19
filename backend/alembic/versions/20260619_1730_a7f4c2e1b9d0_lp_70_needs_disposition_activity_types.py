"""LP-70 needs disposition activity types

Revision ID: a7f4c2e1b9d0
Revises: 93a861456e2f
Create Date: 2026-06-19 17:30:00.000000

Adds four values to the ``activity_type`` enum (LP-70) so the needs-list
disposition actions are audited with semantically-correct types:
``needs_item_confirmed`` / ``needs_item_adjusted`` / ``needs_item_dismissed`` /
``needs_item_waived``. (Adding a need reuses the existing ``needs_item_created``.)
The enum is a VARCHAR + CHECK (ADR-037), so this is a constraint swap — drop the
``ck_activity_logs_activitytype`` CHECK and recreate it with the expanded value
set. No data changes.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7f4c2e1b9d0"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "93a861456e2f"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_activity_logs_activitytype"

# The full enum value set, in model-definition order, with the four new values
# right after needs_item_satisfied.
_NEW_VALUES = (
    "file_created",
    "file_updated",
    "file_deleted",
    "status_changed",
    "document_uploaded",
    "document_processed",
    "document_type_overridden",
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

_ADDED = {
    "needs_item_confirmed",
    "needs_item_adjusted",
    "needs_item_dismissed",
    "needs_item_waived",
}

# The original set (without the new values) for downgrade.
_OLD_VALUES = tuple(v for v in _NEW_VALUES if v not in _ADDED)


def _swap_check(values: tuple[str, ...]) -> None:
    """Drop and recreate the activity_type CHECK with ``values``.

    Uses raw SQL with the literal constraint name so Alembic's naming convention
    does not re-prefix it.
    """
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

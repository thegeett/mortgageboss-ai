"""add document_type_overridden activity type

Revision ID: 8a153b35129b
Revises: 4a94a45455de
Create Date: 2026-06-12 12:31:08.810417

Adds one value to the ``activity_type`` enum (LP-44): ``document_type_overridden``,
so a manual document type override is audited with a semantically-correct type
(ADR-101/151). The enum is a VARCHAR + CHECK (ADR-037), so this is a constraint
swap — drop the ``ck_activity_logs_activitytype`` CHECK and recreate it with the
expanded value set. No data changes.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8a153b35129b"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "4a94a45455de"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_activity_logs_activitytype"

# The full enum value set, in model-definition order, with the new value
# (document_type_overridden) right after document_processed.
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
    "communication_sent",
    "communication_received",
    "note_added",
)

# The original set (without the new value) for downgrade.
_OLD_VALUES = tuple(v for v in _NEW_VALUES if v != "document_type_overridden")


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

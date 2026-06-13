"""add file_updated and file_deleted activity types

Revision ID: 4a94a45455de
Revises: bf89fba42bdc
Create Date: 2026-06-11 17:43:07.424607

Adds two values to the ``activity_type`` enum (LP-30): ``file_updated`` and
``file_deleted``, so the loan-file activity-logging adoption can record updates
and (soft) deletes with semantically-correct types rather than reusing an
ill-fitting one (ADR-101). The enum is a VARCHAR + CHECK (ADR-037), so this is a
constraint swap — drop the ``ck_activity_logs_activitytype`` CHECK and recreate
it with the expanded value set. No data changes.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4a94a45455de"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "bf89fba42bdc"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_activity_logs_activitytype"

# The full enum value set, in model-definition order, after adding the two new
# values (file_updated, file_deleted) right after file_created.
_NEW_VALUES = (
    "file_created",
    "file_updated",
    "file_deleted",
    "status_changed",
    "document_uploaded",
    "document_processed",
    "finding_resolved",
    "verification_run",
    "needs_item_created",
    "needs_item_satisfied",
    "communication_sent",
    "communication_received",
    "note_added",
)

# The original set (without the two new values) for downgrade.
_OLD_VALUES = tuple(v for v in _NEW_VALUES if v not in ("file_updated", "file_deleted"))


def _swap_check(values: tuple[str, ...]) -> None:
    """Drop and recreate the activity_type CHECK with ``values``.

    Uses raw SQL with the literal constraint name so Alembic's naming convention
    does not re-prefix it (``op.drop_constraint`` would otherwise build
    ``ck_activity_logs_<name>`` from the passed name).
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
    """Restore the activity_type CHECK to the original value set.

    Any rows using the new values would violate the restored CHECK; in V1 dev
    there are none at downgrade time.
    """
    _swap_check(_OLD_VALUES)

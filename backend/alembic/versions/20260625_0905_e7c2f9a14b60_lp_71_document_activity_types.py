"""LP-71 document versioning/staleness activity types

Revision ID: e7c2f9a14b60
Revises: d4b18c7af3e2
Create Date: 2026-06-25 09:05:00.000000

Adds two values to the ``activity_type`` enum (LP-71): ``document_replaced`` (an
explicit replace — old historical, new current) and ``document_staleness_resolved``
(the processor waived/accepted a flagged-stale document). VARCHAR + CHECK (ADR-037),
so this is a constraint swap.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7c2f9a14b60"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "d4b18c7af3e2"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_activity_logs_activitytype"

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

_ADDED = {"document_replaced", "document_staleness_resolved"}
_OLD_VALUES = tuple(v for v in _NEW_VALUES if v not in _ADDED)


def _swap_check(values: tuple[str, ...]) -> None:
    joined = ", ".join(f"'{value}'" for value in values)
    op.execute(f"ALTER TABLE activity_logs DROP CONSTRAINT {_CONSTRAINT}")
    op.execute(
        f"ALTER TABLE activity_logs ADD CONSTRAINT {_CONSTRAINT} "
        f"CHECK (activity_type IN ({joined}))"
    )


def upgrade() -> None:
    _swap_check(_NEW_VALUES)


def downgrade() -> None:
    _swap_check(_OLD_VALUES)

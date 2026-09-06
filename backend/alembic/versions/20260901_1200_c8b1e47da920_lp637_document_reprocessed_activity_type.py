"""add document_reprocessed activity type (LP-637)

Adds one value to the ``activity_type`` enum (LP-637): ``document_reprocessed``, so a processor
asking for a document to be read again from scratch is audited with its own type — distinct from
``document_type_overridden`` (a human supplying the type) and ``document_replaced`` (a new file).

The enum is a VARCHAR + CHECK (ADR-037), so this is a constraint swap, exactly as LP-98 did for
``finding_undone``.

WITHOUT THIS THE ENDPOINT 500s ON ITS FIRST CALL against any migrated database. `log_activity` is
the first write `POST /documents/{id}/reprocess` makes, and the CHECK would reject the new value:
`IntegrityError` on commit, so the activity, the stale marker and the enqueue all fail together.

The test suite cannot see that. ``tests/conftest.py`` builds the schema with
``Base.metadata.create_all``, which regenerates the CHECK from the *current* enum — so a missing
migration is invisible there by construction, and the suite passes at full green either way. The
guard that does see it is a text check over these files:
``tests/test_activity_type_migrations.py``.

Revision ID: c8b1e47da920
Revises: f4a2c8e91b73
Create Date: 2026-09-01 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8b1e47da920"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "f4a2c8e91b73"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_activity_logs_activitytype"

# The full enum value set, in model-definition order, with the new value (document_reprocessed)
# right after document_staleness_resolved.
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
    "document_reprocessed",
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
_OLD_VALUES = tuple(v for v in _NEW_VALUES if v != "document_reprocessed")


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

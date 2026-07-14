"""LP-322 finding_events: add carried_forward + revived event types

Revision ID: 9f0a5f88b6f8
Revises: 99d1a8b78356
Create Date: 2026-07-14 20:00:00.000000

Cross-run reconciliation (LP-322) records two transitions the single-run log (LP-316) did not have:
``carried_forward`` (a re-run re-detected a finding unchanged) and ``revived`` (a retired finding's
subject reappeared). Both are appended to the existing ``finding_events`` log; this only widens the
``event_type`` CHECK constraint to admit them. ``str_enum`` is VARCHAR+CHECK (no native enum), so
this is a DROP + re-ADD of the CHECK — no ``ALTER TYPE``.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9f0a5f88b6f8"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "99d1a8b78356"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The CHECK name ``create_all`` produces (the migration converges on this). Some early-created DBs
# carry a stale double-prefixed name (a str_enum + naming-convention artifact); both are dropped
# IF EXISTS so the migration applies cleanly regardless and everyone ends on the single name.
_CONSTRAINT = "ck_finding_events_findingeventtype"
_STALE_DOUBLE = "ck_finding_events_ck_finding_events_findingeventtype"
_OLD = ("created", "outcome_changed", "resolved", "retired")
_NEW = ("created", "carried_forward", "outcome_changed", "resolved", "retired", "revived")


def _check(values: tuple[str, ...]) -> str:
    return f"event_type IN ({', '.join(repr(v) for v in values)})"


def _replace_check(values: tuple[str, ...]) -> None:
    op.execute(f"ALTER TABLE finding_events DROP CONSTRAINT IF EXISTS {_CONSTRAINT}")
    op.execute(f"ALTER TABLE finding_events DROP CONSTRAINT IF EXISTS {_STALE_DOUBLE}")
    op.execute(f"ALTER TABLE finding_events ADD CONSTRAINT {_CONSTRAINT} CHECK ({_check(values)})")


def upgrade() -> None:
    """Widen the finding_events event_type CHECK to admit carried_forward + revived."""
    _replace_check(_NEW)


def downgrade() -> None:
    """Restore the single-run CHECK (LP-316's four values)."""
    _replace_check(_OLD)

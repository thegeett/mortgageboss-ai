"""LP-905 — one new activity type, and the whole constraint rewritten to keep it.

`CONDITION_SHEET_RECEIVED` is the timeline entry a processor sees when a condition sheet arrives,
by upload or forwarded from the inbox. Adding it means rewriting the `activity_type` CHECK, because
`str_enum` (ADR-037) stores these as VARCHAR + CHECK rather than as a native enum.

⚠️ THE SWAP LISTS ALL 33 VALUES, NOT JUST THE NEW ONE, AND THAT IS THE WHOLE DANGER OF THIS FILE.
Each swap DROPS the constraint and recreates it from its own tuple, so whatever this tuple omits is
revoked from the database even though an earlier migration added it. `tests/test_activity_type_
migrations.py` exists because LP-UI-033 shipped a swap that silently revoked four live values.

⚠️ AND THE LIST WAS TAKEN FROM THE ENUM AT RUNTIME, NOT FROM A GREP. Grepping
`^\\s+[A-Z_]+ = "` over `activity_log.py` returns 31 of the 32 members — it misses
`document_replaced` — and grepping the constraint name with an underscore
(`ck_activity_logs_activity_type`) matches none of the thirteen swap migrations, because the real
name has none (`ck_activity_logs_activitytype`). Both mistakes were made while writing this file and
both would have produced a plausible, wrong tuple. The values below came from
`[m.value for m in ActivityType]`, and the newest complete swap was identified with the guard's own
parser rather than by filename date: `a7f42c8e91b6` (LP-819), the only one of thirteen listing all 32.

Revision ID: e5a2c7f31b84
Revises: d1f4b8c25e93
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e5a2c7f31b84"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | None = "d1f4b8c25e93"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_activity_logs_activitytype"

#: Every value the enum declared before this migration — 32, in enum order, taken from the enum
#: itself. The guard folds this tuple out of the `upgrade()` call below with `ast`, so it must stay
#: a literal it can resolve.
_EXISTING = (
    "file_created",
    "file_updated",
    "file_deleted",
    "status_changed",
    "document_uploaded",
    "document_processed",
    "document_type_overridden",
    "document_replaced",
    "document_staleness_resolved",
    "field_reviewed",
    "field_review_reverted",
    "document_reprocessed",
    "finding_resolved",
    "finding_undone",
    "verification_run",
    "dti_overridden",
    "dti_line_added",
    "dti_line_removed",
    "dti_ungated",
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
    "communication_failed",
    "note_added",
)

#: 33 — the 32 above plus the one LP-905 adds.
_NEW_VALUES = (*_EXISTING, "condition_sheet_received")


def _swap_check(values: tuple[str, ...]) -> None:
    joined = ", ".join(f"'{value}'" for value in values)
    op.execute(f"ALTER TABLE activity_logs DROP CONSTRAINT IF EXISTS {_CONSTRAINT}")
    op.execute(
        f"ALTER TABLE activity_logs ADD CONSTRAINT {_CONSTRAINT} "
        f"CHECK (activity_type IN ({joined}))"
    )


def upgrade() -> None:
    """Permit `condition_sheet_received` alongside everything already permitted."""
    _swap_check(_NEW_VALUES)


def downgrade() -> None:
    """Back to the 32.

    ⚠️ ROWS CARRYING THE REVOKED VALUE ARE DELETED FIRST, or the ADD CONSTRAINT fails against them
    and the downgrade cannot complete. An activity-log row is an audit entry, so this is a real loss
    — which is the honest consequence of removing a value the application has already written, and
    the reason a downgrade past this point is not a routine operation.
    """
    op.execute("DELETE FROM activity_logs WHERE activity_type = 'condition_sheet_received'")
    _swap_check(_EXISTING)

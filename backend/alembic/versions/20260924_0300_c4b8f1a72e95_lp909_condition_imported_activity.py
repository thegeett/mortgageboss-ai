"""LP-909 — one new activity type for the import, and the whole constraint rewritten to keep it.

`CONDITION_IMPORTED` is the timeline entry spec §LP-909 step 5 requires: "Conditions imported: N new,
M seen again". Adding it means rewriting the `activity_type` CHECK, because `str_enum` (ADR-037)
stores these as VARCHAR + CHECK rather than as a native enum — so the enum member alone changes what
the CODE writes and nothing about what the database accepts.

⚠️ THE SWAP LISTS ALL 34 VALUES, NOT JUST THE NEW ONE, AND THAT IS THE WHOLE DANGER OF THIS FILE.
Each swap DROPS the constraint and recreates it from its own tuple, so whatever this tuple omits is
revoked even though an earlier migration added it. `tests/test_activity_type_migrations.py` exists
because LP-UI-033 shipped a swap that silently revoked four live values.

⚠️ AND THE LIST CAME FROM THE ENUM AT RUNTIME, NOT FROM A GREP — LP-905's swap records that grepping
`^\\s+[A-Z_]+ = "` over `activity_log.py` returns 31 of 32 members (it misses `document_replaced`),
and that grepping the constraint name with an underscore matches none of the swaps because the real
name has none. Both mistakes were made while writing that file. These 33 came from
`[m.value for m in ActivityType]` before `condition_imported` was added to the enum.

`_EXISTING` is a module constant unpacked with `*`, which is a form the guard's `ast` folder resolves
deliberately — it must stay a literal tuple it can fold, never a comprehension or a call.

Revision ID: c4b8f1a72e95
Revises: e5a2c7f31b84
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c4b8f1a72e95"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | None = "e5a2c7f31b84"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_activity_logs_activitytype"

#: Every value the enum declared before this migration — 33, in enum order, taken from the enum
#: itself rather than from a grep.
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
    "condition_sheet_received",
)

#: 34 — the 33 above plus the one LP-909 adds.
_NEW_VALUES = (*_EXISTING, "condition_imported")


def _swap_check(values: tuple[str, ...]) -> None:
    joined = ", ".join(f"'{value}'" for value in values)
    op.execute(f"ALTER TABLE activity_logs DROP CONSTRAINT IF EXISTS {_CONSTRAINT}")
    op.execute(
        f"ALTER TABLE activity_logs ADD CONSTRAINT {_CONSTRAINT} "
        f"CHECK (activity_type IN ({joined}))"
    )


def upgrade() -> None:
    """Permit `condition_imported` alongside everything already permitted."""
    _swap_check(_NEW_VALUES)


def downgrade() -> None:
    """Back to the 33.

    ⚠️ ROWS CARRYING THE REVOKED VALUE ARE DELETED FIRST, or the ADD CONSTRAINT fails against them
    and the downgrade cannot complete. An activity-log row is an audit entry, so this is a real loss
    — the honest consequence of removing a value the application has already written, and the reason
    a downgrade past this point is not a routine operation.
    """
    op.execute("DELETE FROM activity_logs WHERE activity_type = 'condition_imported'")
    _swap_check(_EXISTING)

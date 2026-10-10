"""LP-972 — the call log and "Wait for something".

- `condition_items.waiting`: a step that waits on someone by its `due_date`, with a reminder on that
  date. Not null, default false, so every existing task is not a wait.
- `condition_events.kind` gains `condition_call_logged`: she called or talked to someone, recorded on the
  condition as history (a record, not a task).
- `reminder_snoozes.kind` gains `condition_wait_due`: the reminder a wait's date raises.

RAW SQL for the CHECK swaps (ADR-037, LP-932). The downgrade removes the rows that use the new values
before narrowing each CHECK back.

NOT IN THE READONLY VIEW. `readonly.condition_items` lists its columns explicitly (LP-956), so `waiting`
stays out until a ticket adds it; `condition_events.detail`, where a call's words are kept, is already out.

Revision ID: 169e48fff378
Revises: 253c4c8df883
Create Date: 2026-10-09 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "169e48fff378"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "253c4c8df883"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENT_KIND_CK = "ck_condition_events_conditioneventkind"
_EVENT_KINDS_BEFORE = (
    "round_received",
    "round_parsed",
    "round_parse_failed",
    "round_reparse_requested",
    "round_imported",
    "round_discarded",
    "round_enriched",
    "condition_created",
    "condition_seen_again",
    "condition_note_added",
    "condition_edited",
    "condition_prep_moved",
    "condition_verdict_recorded",
    "condition_reopened",
    "condition_came_back",
    "condition_owner_changed",
    "condition_superseded",
    "round_compared",
    "condition_read",
    "condition_reading_confirmed",
    "condition_planned",
    "condition_plan_changed",
    "round_plan_confirmed",
    "condition_drafted",
    "condition_draft_polished",
    "condition_evidence_checked",
    "condition_evidence_accepted",
    "condition_finding_answered",
    "round_completeness_changed",
    "condition_withdrawn",
    "condition_restored",
    "condition_typed",
    "round_lender_declined",
    "round_wrong_file_confirmed",
    "condition_evidence_linked",
    "condition_evidence_unlinked",
)
_EVENT_KINDS_AFTER = (*_EVENT_KINDS_BEFORE, "condition_call_logged")

_REMINDER_KIND_CK = "ck_reminder_snoozes_reminderkind"
_REMINDER_KINDS_BEFORE = ("needs_item_pending", "no_reply", "file_untouched")
_REMINDER_KINDS_AFTER = (*_REMINDER_KINDS_BEFORE, "condition_wait_due")


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _swap(table: str, constraint: str, values: Sequence[str]) -> None:
    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}")
    op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {constraint} CHECK ({_in('kind', values)})")


def upgrade() -> None:
    op.add_column(
        "condition_items",
        sa.Column("waiting", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    _swap("condition_events", _EVENT_KIND_CK, _EVENT_KINDS_AFTER)
    _swap("reminder_snoozes", _REMINDER_KIND_CK, _REMINDER_KINDS_AFTER)


def downgrade() -> None:
    op.execute("DELETE FROM reminder_snoozes WHERE kind = 'condition_wait_due'")
    _swap("reminder_snoozes", _REMINDER_KIND_CK, _REMINDER_KINDS_BEFORE)
    op.execute("DELETE FROM condition_events WHERE kind = 'condition_call_logged'")
    _swap("condition_events", _EVENT_KIND_CK, _EVENT_KINDS_BEFORE)
    op.drop_column("condition_items", "waiting")

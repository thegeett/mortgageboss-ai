"""LP-972 — the call log and "Wait for something".

- `condition_items.waiting`: a step that waits on someone by its `due_date`, with a reminder on that
  date. Not null, default false, so every existing task is not a wait.
- `condition_events.kind` gains `condition_call_logged`: she called or talked to someone, recorded on the
  condition as history (a record, not a task).
- `reminder_snoozes.kind` gains `condition_wait_due`: the reminder a wait's date raises.

RAW SQL for the CHECK swaps (ADR-037, LP-932). The downgrade removes the SNOOZES that use the new
value and refuses outright if any call has been logged (LP-972 review): a call is a record of a
conversation in her words, and a schema rollback must not delete one as a side effect.

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


#: The one SQL both the count and the sentence below name, so they cannot drift apart.
_CALLS = "FROM condition_events WHERE kind = 'condition_call_logged'"


def downgrade() -> None:
    """LP-972 REVIEW — A ROLLBACK DOES NOT DELETE HER CALLS WITHOUT BEING TOLD TO.

    Narrowing `condition_events.kind` means no row may hold the new value, so the rows have to go
    before the CHECK does. But a `condition_call_logged` event IS the record of a conversation — who
    she spoke to, on what day, and up to 300 characters of her own words about what was agreed — and
    it is the only trace of it anywhere. Deleting that as a side effect of a schema rollback is not a
    decision a migration should make quietly, so this refuses and names the SQL that accepts the loss.

    The snoozes are different and still go: a snooze is derived state about a date, and the reminder
    it suppresses comes back on its own.
    """
    logged = int(op.get_bind().execute(sa.text(f"SELECT count(*) {_CALLS}")).scalar() or 0)
    if logged:
        raise RuntimeError(
            f"{logged} logged call(s) are recorded as `condition_call_logged` events, each carrying "
            "the words she typed about what was agreed, and narrowing the CHECK means deleting them. "
            "This migration will not do that as a side effect. To accept the loss, run "
            f"`DELETE {_CALLS};` and downgrade again."
        )
    op.execute("DELETE FROM reminder_snoozes WHERE kind = 'condition_wait_due'")
    _swap("reminder_snoozes", _REMINDER_KIND_CK, _REMINDER_KINDS_BEFORE)
    _swap("condition_events", _EVENT_KIND_CK, _EVENT_KINDS_BEFORE)
    op.drop_column("condition_items", "waiting")

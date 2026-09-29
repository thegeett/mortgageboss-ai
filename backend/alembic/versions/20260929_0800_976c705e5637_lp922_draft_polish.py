"""LP-922 follow-up — AI polish of a condition draft (STOP AND ASK 1, answered 2026-09-29).

- `condition_drafts.polished_at`: when she used the AI's polish; cleared when the plan re-renders.
- Event kind `condition_draft_polished`.

RAW SQL (ADR-037). THE CHECK SWAP LISTS EVERY VALUE: 26 event kinds.

Revision ID: 976c705e5637
Revises: fccf8534a7cd
Create Date: 2026-09-29 08:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "976c705e5637"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "fccf8534a7cd"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENT_KIND_CK = "ck_condition_events_conditioneventkind"

_EVENT_KIND_BEFORE = (
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
    "round_completeness_changed",
    "condition_read",
    "condition_reading_confirmed",
    "condition_planned",
    "condition_plan_changed",
    "round_plan_confirmed",
    "condition_drafted",
)
_EVENT_KIND_AFTER = (*_EVENT_KIND_BEFORE, "condition_draft_polished")


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _swap_event_kind_check(values: Sequence[str]) -> None:
    """Rewrite `ck_condition_events_conditioneventkind` from `values`."""
    op.execute(f"ALTER TABLE condition_events DROP CONSTRAINT IF EXISTS {_EVENT_KIND_CK}")
    op.execute(
        f"ALTER TABLE condition_events ADD CONSTRAINT {_EVENT_KIND_CK} CHECK ({_in('kind', values)})"
    )


def upgrade() -> None:
    op.execute("ALTER TABLE condition_drafts ADD COLUMN polished_at TIMESTAMP WITH TIME ZONE")
    _swap_event_kind_check(_EVENT_KIND_AFTER)


def downgrade() -> None:
    op.execute("DELETE FROM condition_events WHERE kind = 'condition_draft_polished'")
    _swap_event_kind_check(_EVENT_KIND_BEFORE)
    op.execute("ALTER TABLE condition_drafts DROP COLUMN IF EXISTS polished_at")

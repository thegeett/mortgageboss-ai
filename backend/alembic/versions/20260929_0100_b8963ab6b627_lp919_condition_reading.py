"""LP-919 — reading each condition: where the reading is kept, and two event kinds.

- `conditions.reading` (JSONB, NPI: it restates amounts, banks and last fours from the lender's text),
  `reading_status` (NOT NULL, default `unread`), `reading_source`, `reading_confidence`.
- `condition_rounds.reading_run` (JSONB): the one AI call per round, its tokens and cost estimate.
- `lender_condition_codes.confirmed_reading` (JSONB): her S3-03 answer for a code, names and performers
  only.
- `condition_events.kind` gains `condition_read` and `condition_reading_confirmed`.

RAW SQL, AS LP-912 AND LP-931 DO. `op.create_check_constraint` re-prefixes names through the naming
convention; a literal `ADD CONSTRAINT` is named what it says, which is what `create_all` names it.

THE EVENT-KIND SWAP LISTS ALL 21 VALUES, taken from the enum at runtime when this was written, not
from a grep. A swap recreates the CHECK from its own tuple, so the tuple IS what the database accepts.
Since LP-932 the constraint has one name on every database, `ck_condition_events_conditioneventkind`.

No readonly view changes: none of the four new `conditions` columns is exposed (the reading is NPI; the
status columns are listed as excluded in the readonly guard rather than half-exposing a feature).

Revision ID: b8963ab6b627
Revises: bac8810abe90
Create Date: 2026-09-29 01:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b8963ab6b627"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "bac8810abe90"  # pragma: allowlist secret
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
)

_EVENT_KIND_AFTER = (
    *_EVENT_KIND_BEFORE,
    "condition_read",
    "condition_reading_confirmed",
)

_READING_STATUS = ("unread", "ready", "needs_confirmation", "confirmed")
_READING_SOURCE = ("ai", "library", "confirmed")


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _swap_event_kind_check(values: Sequence[str]) -> None:
    """Rewrite `ck_condition_events_conditioneventkind` from `values`."""
    op.execute(f"ALTER TABLE condition_events DROP CONSTRAINT IF EXISTS {_EVENT_KIND_CK}")
    op.execute(
        f"ALTER TABLE condition_events ADD CONSTRAINT {_EVENT_KIND_CK} CHECK ({_in('kind', values)})"
    )


def upgrade() -> None:
    op.execute("ALTER TABLE conditions ADD COLUMN reading JSONB")
    op.execute(
        "ALTER TABLE conditions ADD COLUMN reading_status VARCHAR(32) NOT NULL DEFAULT 'unread'"
    )
    op.execute("ALTER TABLE conditions ADD COLUMN reading_source VARCHAR(32)")
    op.execute("ALTER TABLE conditions ADD COLUMN reading_confidence NUMERIC(3, 2)")
    op.execute(
        "ALTER TABLE conditions ADD CONSTRAINT ck_conditions_conditionreadingstatus "
        f"CHECK ({_in('reading_status', _READING_STATUS)})"
    )
    op.execute(
        "ALTER TABLE conditions ADD CONSTRAINT ck_conditions_conditionreadingsource "
        f"CHECK ({_in('reading_source', _READING_SOURCE)})"
    )
    op.execute("ALTER TABLE condition_rounds ADD COLUMN reading_run JSONB")
    op.execute("ALTER TABLE lender_condition_codes ADD COLUMN confirmed_reading JSONB")
    _swap_event_kind_check(_EVENT_KIND_AFTER)


def downgrade() -> None:
    # Rows carrying a revoked kind would make the narrower CHECK fail; they go first.
    op.execute(
        "DELETE FROM condition_events WHERE kind IN ('condition_read', 'condition_reading_confirmed')"
    )
    op.execute(f"ALTER TABLE condition_events DROP CONSTRAINT IF EXISTS {_EVENT_KIND_CK}")
    op.execute(
        f"ALTER TABLE condition_events ADD CONSTRAINT {_EVENT_KIND_CK} "
        f"CHECK ({_in('kind', _EVENT_KIND_BEFORE)})"
    )
    op.execute("ALTER TABLE lender_condition_codes DROP COLUMN IF EXISTS confirmed_reading")
    op.execute("ALTER TABLE condition_rounds DROP COLUMN IF EXISTS reading_run")
    op.execute(
        "ALTER TABLE conditions DROP CONSTRAINT IF EXISTS ck_conditions_conditionreadingsource"
    )
    op.execute(
        "ALTER TABLE conditions DROP CONSTRAINT IF EXISTS ck_conditions_conditionreadingstatus"
    )
    for column in ("reading_confidence", "reading_source", "reading_status", "reading"):
        op.execute(f"ALTER TABLE conditions DROP COLUMN IF EXISTS {column}")

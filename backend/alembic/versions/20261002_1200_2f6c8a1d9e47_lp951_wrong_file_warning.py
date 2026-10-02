"""LP-951 — wrong-file warning: event kind `round_wrong_file_confirmed`.

She imported a sheet whose borrower or loan number did not match the file, after the warning. No table
changes; the detail carries which facts differed, never the values.

RAW SQL for the CHECK swap (ADR-037, LP-932): it lists every value, 34 kinds. The downgrade refuses while
any such event exists: it is the only record that she was warned.

Revision ID: 2f6c8a1d9e47
Revises: 7b2d9e4c1a58
Create Date: 2026-10-02 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2f6c8a1d9e47"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "7b2d9e4c1a58"  # pragma: allowlist secret
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
    "condition_draft_polished",
    "condition_evidence_checked",
    "condition_evidence_accepted",
    "condition_finding_answered",
    "condition_withdrawn",
    "condition_restored",
    "condition_typed",
    "round_lender_declined",
)
_NEW = ("round_wrong_file_confirmed",)
_EVENT_KIND_AFTER = (*_EVENT_KIND_BEFORE, *_NEW)


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _swap_event_kind_check(values: Sequence[str]) -> None:
    """Rewrite `ck_condition_events_conditioneventkind` from `values`."""
    op.execute(f"ALTER TABLE condition_events DROP CONSTRAINT IF EXISTS {_EVENT_KIND_CK}")
    op.execute(
        f"ALTER TABLE condition_events ADD CONSTRAINT {_EVENT_KIND_CK} CHECK ({_in('kind', values)})"
    )


def upgrade() -> None:
    _swap_event_kind_check(_EVENT_KIND_AFTER)


def downgrade() -> None:
    present = (
        op.get_bind()
        .execute(sa.text(f"SELECT count(*) FROM condition_events WHERE {_in('kind', _NEW)}"))
        .scalar()
    )
    if present:
        raise RuntimeError(
            f"{present} wrong-file confirmation(s) exist; they record that she was warned. "
            "Downgrading would have to delete them, so it stops here."
        )
    _swap_event_kind_check(_EVENT_KIND_BEFORE)

"""LP-940 — withdraw a hand-added condition: event kinds `condition_withdrawn`, `condition_restored`.

No table changes: withdrawal is the existing soft delete (`conditions.deleted_at`), and the reason
travels in the event's detail.

RAW SQL (ADR-037, LP-932). THE CHECK SWAP LISTS EVERY VALUE: 31 kinds.

THE DOWNGRADE REFUSES RATHER THAN DELETES. Earlier swaps deleted the new kinds' events on the way down;
these are the only record of why a condition left the file, so a downgrade with any of them present
stops and says so instead.

Revision ID: 3c1e7a90d4b2
Revises: 08828fa86ffc
Create Date: 2026-09-29 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3c1e7a90d4b2"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "08828fa86ffc"  # pragma: allowlist secret
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
)
_NEW = ("condition_withdrawn", "condition_restored")
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
            f"{present} withdrawal event(s) exist; they are the only record of why a condition left "
            "the file. Downgrading would have to delete them, so it stops here."
        )
    _swap_event_kind_check(_EVENT_KIND_BEFORE)

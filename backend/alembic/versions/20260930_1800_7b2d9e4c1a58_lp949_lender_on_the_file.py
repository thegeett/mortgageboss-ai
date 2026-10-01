"""LP-949 — lender on the file: the AI's proposed type on a code, and two event kinds.

- `lender_condition_codes.proposed_type_id`: a library type the reading PROPOSED for an unmapped code.
  It is shown in the lender's "Codes to review" table and used only after a person confirms it there
  (ADR-417). Never read by import, the reading or the plan.
- Event kinds `condition_typed` (an untyped condition got its type from the lender's code map, after
  the file's lender was set or a code was confirmed) and `round_lender_declined` (she said the lender
  the app detected on a sheet is not this file's lender).

RAW SQL for the CHECK swap (ADR-037, LP-932): it lists every value, 33 kinds.

THE DOWNGRADE REFUSES RATHER THAN DELETES, as LP-940's does: the events are history.

Revision ID: 7b2d9e4c1a58
Revises: c4a8e2f1b637
Create Date: 2026-09-30 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7b2d9e4c1a58"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "c4a8e2f1b637"  # pragma: allowlist secret
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
)
_NEW = ("condition_typed", "round_lender_declined")
_EVENT_KIND_AFTER = (*_EVENT_KIND_BEFORE, *_NEW)


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _swap_event_kind_check(values: Sequence[str]) -> None:
    """Rewrite `ck_condition_events_conditioneventkind` from `values`."""
    op.execute(f"ALTER TABLE condition_events DROP CONSTRAINT IF EXISTS {_EVENT_KIND_CK}")
    op.execute(
        f"ALTER TABLE condition_events ADD CONSTRAINT {_EVENT_KIND_CK} CHECK ({_in('kind', values)})"
    )


def _grant_codes_view() -> None:
    """A dropped view drops its grants (LP-842): re-grant in the same step as the rebuild."""
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
                GRANT SELECT ON readonly.lender_condition_codes TO mbai_readonly;
            END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    op.add_column(
        "lender_condition_codes",
        sa.Column("proposed_type_id", sa.String(length=64), nullable=True),
    )
    # LP-904's definition plus `proposed_type_id`: a library type id, not borrower data, exposed like
    # `canonical_type_id` beside it. Re-granted below in the same step (LP-842).
    op.execute("DROP VIEW IF EXISTS readonly.lender_condition_codes")
    op.execute(
        """
        CREATE VIEW readonly.lender_condition_codes AS
        SELECT id, lender_id, code, label, canonical_type_id,
               default_bucket_kind, default_owner_hint, info_only,
               status, times_seen, first_seen_at, last_seen_at,
               created_at, updated_at, proposed_type_id
        FROM public.lender_condition_codes
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
                GRANT SELECT ON readonly.lender_condition_codes TO mbai_readonly;
            END IF;
        END
        $$;
        """
    )
    _swap_event_kind_check(_EVENT_KIND_AFTER)


def downgrade() -> None:
    present = (
        op.get_bind()
        .execute(sa.text(f"SELECT count(*) FROM condition_events WHERE {_in('kind', _NEW)}"))
        .scalar()
    )
    if present:
        raise RuntimeError(
            f"{present} typed/declined event(s) exist; they are history. Downgrading would have to "
            "delete them, so it stops here."
        )
    _swap_event_kind_check(_EVENT_KIND_BEFORE)
    op.execute("DROP VIEW IF EXISTS readonly.lender_condition_codes")
    op.execute(
        """
        CREATE VIEW readonly.lender_condition_codes AS
        SELECT id, lender_id, code, label, canonical_type_id,
               default_bucket_kind, default_owner_hint, info_only,
               status, times_seen, first_seen_at, last_seen_at,
               created_at, updated_at
        FROM public.lender_condition_codes
        """
    )
    _grant_codes_view()
    op.drop_column("lender_condition_codes", "proposed_type_id")

"""LP-920 — the action plan: items per condition, the round's plan state, and two switches.

- `condition_items`: one row per thing a condition asks for, with its action, who acts, status, due
  date, the need it asks through and the document already in the file. `specifics` is NPI, so the table
  has no readonly view (listed as excluded in the readonly guard).
- `conditions.next_step` (+ CHECK `ck_conditions_planoption`) and `conditions.plan_reason`.
- `condition_rounds.plan_ready_at`, `plan_confirmed_at`, `plan_confirmed_by_user_id`.
- `loan_files.lender_processing` ("Lender is processing this file", §4a change 8).
- `lenders.condition_settings` (who orders what; LP-925 edits it).
- Event kinds `condition_planned`, `condition_plan_changed`, `round_plan_confirmed`; activity types
  `condition_plan_ready`, `condition_plan_confirmed`.

RAW SQL THROUGHOUT (ADR-037, LP-912, LP-931): the DDL is `create_all`'s own, printed from the models,
so every constraint carries the name the models give it (LP-932's guard checks names now).

BOTH CHECK SWAPS LIST EVERY VALUE: 24 event kinds, 36 activity types, taken from the enums at runtime
when this was written. Each swap helper names its own constraint.

Revision ID: 6d517ee261d7
Revises: b8963ab6b627
Create Date: 2026-09-29 04:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "6d517ee261d7"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "b8963ab6b627"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENT_KIND_CK = "ck_condition_events_conditioneventkind"
_ACTIVITY_CK = "ck_activity_logs_activitytype"

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
)
_EVENT_KIND_AFTER = (
    *_EVENT_KIND_BEFORE,
    "condition_planned",
    "condition_plan_changed",
    "round_plan_confirmed",
)

_ACTIVITY_BEFORE = (
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
    "condition_imported",
)
_ACTIVITY_AFTER = (*_ACTIVITY_BEFORE, "condition_plan_ready", "condition_plan_confirmed")

_PERFORMER = (
    "borrower",
    "lo",
    "processor",
    "lender",
    "title",
    "attorney",
    "insurance",
    "hoa",
    "employer",
    "appraiser",
    "other_party",
)
_PLAN_OPTION = (
    "ask_borrower",
    "ask_third_party",
    "i_will_do_it",
    "already_in_file",
    "ask_underwriter",
    "push_back",
    "lender_doing_it",
    "information_only",
)
_ITEM_STATUS = ("open", "requested", "received", "done", "not_needed")
_ITEM_ORIGIN = ("reading", "manual", "carried")


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _swap_event_kind_check(values: Sequence[str]) -> None:
    """Rewrite `ck_condition_events_conditioneventkind` from `values`."""
    op.execute(f"ALTER TABLE condition_events DROP CONSTRAINT IF EXISTS {_EVENT_KIND_CK}")
    op.execute(
        f"ALTER TABLE condition_events ADD CONSTRAINT {_EVENT_KIND_CK} CHECK ({_in('kind', values)})"
    )


def _swap_activity_check(values: Sequence[str]) -> None:
    """Rewrite `ck_activity_logs_activitytype` from `values`."""
    op.execute(f"ALTER TABLE activity_logs DROP CONSTRAINT IF EXISTS {_ACTIVITY_CK}")
    op.execute(
        f"ALTER TABLE activity_logs ADD CONSTRAINT {_ACTIVITY_CK} "
        f"CHECK ({_in('activity_type', values)})"
    )


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE condition_items (
            company_id UUID NOT NULL,
            loan_file_id UUID NOT NULL,
            condition_id UUID NOT NULL,
            round_id UUID,
            key VARCHAR(40) NOT NULL,
            name VARCHAR(200) NOT NULL,
            acceptable TEXT NOT NULL,
            performer VARCHAR(32) NOT NULL,
            performers JSONB NOT NULL,
            option VARCHAR(32) NOT NULL,
            status VARCHAR(32) DEFAULT 'open' NOT NULL,
            origin VARCHAR(32) NOT NULL,
            documents JSONB NOT NULL,
            checks JSONB NOT NULL,
            specifics JSONB NOT NULL,
            need_id UUID,
            document_id UUID,
            document_page INTEGER,
            waits_on_condition_id UUID,
            due_date DATE,
            sequence INTEGER NOT NULL,
            id UUID NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            deleted_at TIMESTAMP WITH TIME ZONE,
            CONSTRAINT pk_condition_items PRIMARY KEY (id),
            CONSTRAINT fk_condition_items_company_id_companies FOREIGN KEY (company_id)
                REFERENCES companies (id) ON DELETE CASCADE,
            CONSTRAINT fk_condition_items_loan_file_id_loan_files FOREIGN KEY (loan_file_id)
                REFERENCES loan_files (id) ON DELETE CASCADE,
            CONSTRAINT fk_condition_items_condition_id_conditions FOREIGN KEY (condition_id)
                REFERENCES conditions (id) ON DELETE CASCADE,
            CONSTRAINT fk_condition_items_round_id_condition_rounds FOREIGN KEY (round_id)
                REFERENCES condition_rounds (id) ON DELETE SET NULL,
            CONSTRAINT ck_condition_items_performer CHECK ({_in("performer", _PERFORMER)}),
            CONSTRAINT ck_condition_items_planoption CHECK ({_in("option", _PLAN_OPTION)}),
            CONSTRAINT ck_condition_items_conditionitemstatus CHECK ({_in("status", _ITEM_STATUS)}),
            CONSTRAINT ck_condition_items_conditionitemorigin CHECK ({_in("origin", _ITEM_ORIGIN)}),
            CONSTRAINT fk_condition_items_need_id_needs_items FOREIGN KEY (need_id)
                REFERENCES needs_items (id) ON DELETE SET NULL,
            CONSTRAINT fk_condition_items_document_id_documents FOREIGN KEY (document_id)
                REFERENCES documents (id) ON DELETE SET NULL,
            CONSTRAINT fk_condition_items_waits_on_condition_id_conditions
                FOREIGN KEY (waits_on_condition_id) REFERENCES conditions (id) ON DELETE SET NULL
        )
        """
    )
    op.execute("CREATE INDEX ix_condition_items_condition_id ON condition_items (condition_id)")
    op.execute("CREATE INDEX ix_condition_items_loan_file_id ON condition_items (loan_file_id)")
    op.execute("CREATE INDEX ix_condition_items_need_id ON condition_items (need_id)")

    op.execute("ALTER TABLE conditions ADD COLUMN next_step VARCHAR(32)")
    op.execute("ALTER TABLE conditions ADD COLUMN plan_reason VARCHAR(256)")
    op.execute(
        "ALTER TABLE conditions ADD CONSTRAINT ck_conditions_planoption "
        f"CHECK ({_in('next_step', _PLAN_OPTION)})"
    )
    op.execute("ALTER TABLE condition_rounds ADD COLUMN plan_ready_at TIMESTAMP WITH TIME ZONE")
    op.execute("ALTER TABLE condition_rounds ADD COLUMN plan_confirmed_at TIMESTAMP WITH TIME ZONE")
    op.execute("ALTER TABLE condition_rounds ADD COLUMN plan_confirmed_by_user_id UUID")
    op.execute(
        "ALTER TABLE condition_rounds ADD CONSTRAINT "
        "fk_condition_rounds_plan_confirmed_by_user_id_users FOREIGN KEY (plan_confirmed_by_user_id) "
        "REFERENCES users (id) ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE loan_files ADD COLUMN lender_processing BOOLEAN DEFAULT 'false' NOT NULL"
    )
    op.execute("ALTER TABLE lenders ADD COLUMN condition_settings JSONB")

    _swap_event_kind_check(_EVENT_KIND_AFTER)
    _swap_activity_check(_ACTIVITY_AFTER)


def downgrade() -> None:
    op.execute(
        "DELETE FROM activity_logs "
        "WHERE activity_type IN ('condition_plan_ready', 'condition_plan_confirmed')"
    )
    op.execute(f"ALTER TABLE activity_logs DROP CONSTRAINT IF EXISTS {_ACTIVITY_CK}")
    op.execute(
        f"ALTER TABLE activity_logs ADD CONSTRAINT {_ACTIVITY_CK} "
        f"CHECK ({_in('activity_type', _ACTIVITY_BEFORE)})"
    )
    op.execute(
        "DELETE FROM condition_events "
        "WHERE kind IN ('condition_planned', 'condition_plan_changed', 'round_plan_confirmed')"
    )
    op.execute(f"ALTER TABLE condition_events DROP CONSTRAINT IF EXISTS {_EVENT_KIND_CK}")
    op.execute(
        f"ALTER TABLE condition_events ADD CONSTRAINT {_EVENT_KIND_CK} "
        f"CHECK ({_in('kind', _EVENT_KIND_BEFORE)})"
    )
    op.execute("ALTER TABLE lenders DROP COLUMN IF EXISTS condition_settings")
    op.execute("ALTER TABLE loan_files DROP COLUMN IF EXISTS lender_processing")
    op.execute(
        "ALTER TABLE condition_rounds DROP CONSTRAINT IF EXISTS "
        "fk_condition_rounds_plan_confirmed_by_user_id_users"
    )
    for column in ("plan_confirmed_by_user_id", "plan_confirmed_at", "plan_ready_at"):
        op.execute(f"ALTER TABLE condition_rounds DROP COLUMN IF EXISTS {column}")
    op.execute("ALTER TABLE conditions DROP CONSTRAINT IF EXISTS ck_conditions_planoption")
    op.execute("ALTER TABLE conditions DROP COLUMN IF EXISTS plan_reason")
    op.execute("ALTER TABLE conditions DROP COLUMN IF EXISTS next_step")
    op.execute("DROP TABLE IF EXISTS condition_items")

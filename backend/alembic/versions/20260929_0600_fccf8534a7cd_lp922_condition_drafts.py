"""LP-922 — condition drafts: the link from a round's conditions to Phase 4's draft emails.

- `condition_drafts`: one row per draft the plan made (recipient, round, and the condition for a
  question), linked to its `communications` row. Excluded whole from the readonly layer.
- `condition_items.draft_id`: the draft that asks for the item.
- Event kind `condition_drafted`.

RAW SQL, the DDL `create_all` prints (ADR-037, LP-932). THE CHECK SWAP LISTS EVERY VALUE: 25 event
kinds, taken from the enum when this was written.

Revision ID: fccf8534a7cd
Revises: 6d517ee261d7
Create Date: 2026-09-29 06:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fccf8534a7cd"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "6d517ee261d7"  # pragma: allowlist secret
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
)
_EVENT_KIND_AFTER = (*_EVENT_KIND_BEFORE, "condition_drafted")

_RECIPIENT = (
    "borrower",
    "title_attorney",
    "lo",
    "insurance",
    "hoa",
    "employer",
    "other_party",
    "underwriter",
)


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _swap_event_kind_check(values: Sequence[str]) -> None:
    """Rewrite `ck_condition_events_conditioneventkind` from `values`."""
    op.execute(f"ALTER TABLE condition_events DROP CONSTRAINT IF EXISTS {_EVENT_KIND_CK}")
    op.execute(
        f"ALTER TABLE condition_events ADD CONSTRAINT {_EVENT_KIND_CK} CHECK ({_in('kind', values)})"
    )


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE condition_drafts (
            company_id UUID NOT NULL,
            loan_file_id UUID NOT NULL,
            communication_id UUID NOT NULL,
            round_id UUID,
            recipient VARCHAR(32) NOT NULL,
            condition_id UUID,
            id UUID NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            CONSTRAINT pk_condition_drafts PRIMARY KEY (id),
            CONSTRAINT uq_condition_drafts_communication_id UNIQUE (communication_id),
            CONSTRAINT fk_condition_drafts_company_id_companies FOREIGN KEY (company_id)
                REFERENCES companies (id) ON DELETE CASCADE,
            CONSTRAINT fk_condition_drafts_loan_file_id_loan_files FOREIGN KEY (loan_file_id)
                REFERENCES loan_files (id) ON DELETE CASCADE,
            CONSTRAINT fk_condition_drafts_communication_id_communications
                FOREIGN KEY (communication_id) REFERENCES communications (id) ON DELETE CASCADE,
            CONSTRAINT fk_condition_drafts_round_id_condition_rounds FOREIGN KEY (round_id)
                REFERENCES condition_rounds (id) ON DELETE SET NULL,
            CONSTRAINT ck_condition_drafts_draftrecipient CHECK ({_in("recipient", _RECIPIENT)}),
            CONSTRAINT fk_condition_drafts_condition_id_conditions FOREIGN KEY (condition_id)
                REFERENCES conditions (id) ON DELETE CASCADE
        )
        """
    )
    op.execute("CREATE INDEX ix_condition_drafts_loan_file_id ON condition_drafts (loan_file_id)")
    op.execute("ALTER TABLE condition_items ADD COLUMN draft_id UUID")
    op.execute(
        "ALTER TABLE condition_items ADD CONSTRAINT fk_condition_items_draft_id_condition_drafts "
        "FOREIGN KEY (draft_id) REFERENCES condition_drafts (id) ON DELETE SET NULL"
    )
    _swap_event_kind_check(_EVENT_KIND_AFTER)


def downgrade() -> None:
    op.execute("DELETE FROM condition_events WHERE kind = 'condition_drafted'")
    op.execute(f"ALTER TABLE condition_events DROP CONSTRAINT IF EXISTS {_EVENT_KIND_CK}")
    op.execute(
        f"ALTER TABLE condition_events ADD CONSTRAINT {_EVENT_KIND_CK} "
        f"CHECK ({_in('kind', _EVENT_KIND_BEFORE)})"
    )
    op.execute(
        "ALTER TABLE condition_items DROP CONSTRAINT IF EXISTS "
        "fk_condition_items_draft_id_condition_drafts"
    )
    op.execute("ALTER TABLE condition_items DROP COLUMN IF EXISTS draft_id")
    op.execute("DROP TABLE IF EXISTS condition_drafts")

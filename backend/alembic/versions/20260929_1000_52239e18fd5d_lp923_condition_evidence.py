"""LP-923 — evidence arrives and is checked: one row per (condition item, document).

- `condition_evidence`: the document linked to an item, each check's result and reason, and what the
  document itself showed (a large deposit). NPI (amounts, dates, endings), so excluded from the
  readonly layer.
- Event kinds `condition_evidence_checked`, `condition_evidence_accepted`, `condition_finding_answered`.

RAW SQL, the DDL `create_all` prints (ADR-037, LP-932). THE CHECK SWAP LISTS EVERY VALUE: 29 kinds.

Revision ID: 52239e18fd5d
Revises: 976c705e5637
Create Date: 2026-09-29 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "52239e18fd5d"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "976c705e5637"  # pragma: allowlist secret
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
)
_EVENT_KIND_AFTER = (
    *_EVENT_KIND_BEFORE,
    "condition_evidence_checked",
    "condition_evidence_accepted",
    "condition_finding_answered",
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
        """
        CREATE TABLE condition_evidence (
            company_id UUID NOT NULL,
            loan_file_id UUID NOT NULL,
            condition_id UUID NOT NULL,
            item_id UUID NOT NULL,
            document_id UUID NOT NULL,
            status VARCHAR(32) DEFAULT 'checked' NOT NULL,
            checks JSONB NOT NULL,
            findings JSONB NOT NULL,
            accepted_reason TEXT,
            accepted_by_user_id UUID,
            id UUID NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            CONSTRAINT pk_condition_evidence PRIMARY KEY (id),
            CONSTRAINT uq_condition_evidence_item_id UNIQUE (item_id, document_id),
            CONSTRAINT fk_condition_evidence_company_id_companies FOREIGN KEY (company_id)
                REFERENCES companies (id) ON DELETE CASCADE,
            CONSTRAINT fk_condition_evidence_loan_file_id_loan_files FOREIGN KEY (loan_file_id)
                REFERENCES loan_files (id) ON DELETE CASCADE,
            CONSTRAINT fk_condition_evidence_condition_id_conditions FOREIGN KEY (condition_id)
                REFERENCES conditions (id) ON DELETE CASCADE,
            CONSTRAINT fk_condition_evidence_item_id_condition_items FOREIGN KEY (item_id)
                REFERENCES condition_items (id) ON DELETE CASCADE,
            CONSTRAINT fk_condition_evidence_document_id_documents FOREIGN KEY (document_id)
                REFERENCES documents (id) ON DELETE CASCADE,
            CONSTRAINT ck_condition_evidence_evidencestatus CHECK (status IN ('checked', 'accepted')),
            CONSTRAINT fk_condition_evidence_accepted_by_user_id_users
                FOREIGN KEY (accepted_by_user_id) REFERENCES users (id) ON DELETE SET NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_condition_evidence_condition_id ON condition_evidence (condition_id)"
    )
    op.execute(
        "CREATE INDEX ix_condition_evidence_loan_file_id ON condition_evidence (loan_file_id)"
    )
    _swap_event_kind_check(_EVENT_KIND_AFTER)


def downgrade() -> None:
    op.execute(
        "DELETE FROM condition_events WHERE kind IN "
        "('condition_evidence_checked', 'condition_evidence_accepted', 'condition_finding_answered')"
    )
    _swap_event_kind_check(_EVENT_KIND_BEFORE)
    op.execute("DROP TABLE IF EXISTS condition_evidence")

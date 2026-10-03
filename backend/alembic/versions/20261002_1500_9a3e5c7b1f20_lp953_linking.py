"""LP-953 — linking: manual evidence links, her unlinks as a stored fact, two event kinds.

- `condition_evidence.origin` (`auto` | `manual`), `linked_by_user_id`, `page`: a link she made is an
  evidence row like any other, so its checks run and show; the columns say who made it and where.
- `condition_item_unlinks`: HER DECISION that a document does not answer an item, as its own row. The
  evidence row is deleted on unlink (so no query over evidence has to remember to skip it), and this row
  is what stops arrival linking, or a plan-time match, from putting it back. Clearing it restores the
  automatic match with nothing to reconstruct (the `owner_override` pattern: her choice is a separate
  fact, never an overwrite of the inference).
- Event kinds `condition_evidence_linked`, `condition_evidence_unlinked` (36 kinds).

RAW SQL (ADR-037, LP-932). `condition_item_unlinks` holds ids only and gets a readonly view, re-granted.
The downgrade refuses while any manual link, unlink or new event exists.

Revision ID: 9a3e5c7b1f20
Revises: 2f6c8a1d9e47
Create Date: 2026-10-02 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9a3e5c7b1f20"  # pragma: allowlist secret  (Alembic revision id, not a secret)
down_revision: str | Sequence[str] | None = "2f6c8a1d9e47"  # pragma: allowlist secret
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
    "round_wrong_file_confirmed",
)
_NEW = ("condition_evidence_linked", "condition_evidence_unlinked")
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
    op.execute(
        "ALTER TABLE condition_evidence ADD COLUMN origin VARCHAR(32) DEFAULT 'auto' NOT NULL"
    )
    op.execute(
        "ALTER TABLE condition_evidence ADD CONSTRAINT ck_condition_evidence_evidenceorigin "
        "CHECK (origin IN ('auto', 'manual'))"
    )
    op.execute("ALTER TABLE condition_evidence ADD COLUMN linked_by_user_id UUID")
    op.execute(
        "ALTER TABLE condition_evidence ADD CONSTRAINT fk_condition_evidence_linked_by_user_id_users "
        "FOREIGN KEY (linked_by_user_id) REFERENCES users (id) ON DELETE SET NULL"
    )
    op.execute("ALTER TABLE condition_evidence ADD COLUMN page INTEGER")
    op.execute(
        """
        CREATE TABLE condition_item_unlinks (
            id UUID NOT NULL,
            company_id UUID NOT NULL,
            loan_file_id UUID NOT NULL,
            item_id UUID NOT NULL,
            document_id UUID NOT NULL,
            unlinked_by_user_id UUID,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            CONSTRAINT pk_condition_item_unlinks PRIMARY KEY (id),
            CONSTRAINT uq_condition_item_unlinks_item_id UNIQUE (item_id, document_id),
            CONSTRAINT fk_condition_item_unlinks_company_id_companies FOREIGN KEY (company_id)
                REFERENCES companies (id) ON DELETE CASCADE,
            CONSTRAINT fk_condition_item_unlinks_loan_file_id_loan_files FOREIGN KEY (loan_file_id)
                REFERENCES loan_files (id) ON DELETE CASCADE,
            CONSTRAINT fk_condition_item_unlinks_item_id_condition_items FOREIGN KEY (item_id)
                REFERENCES condition_items (id) ON DELETE CASCADE,
            CONSTRAINT fk_condition_item_unlinks_document_id_documents FOREIGN KEY (document_id)
                REFERENCES documents (id) ON DELETE CASCADE,
            CONSTRAINT fk_condition_item_unlinks_unlinked_by_user_id_users
                FOREIGN KEY (unlinked_by_user_id) REFERENCES users (id) ON DELETE SET NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_condition_item_unlinks_loan_file_id ON condition_item_unlinks (loan_file_id)"
    )
    op.execute(
        """
        CREATE VIEW readonly.condition_item_unlinks AS
        SELECT id, company_id, loan_file_id, item_id, document_id, unlinked_by_user_id,
               created_at, updated_at
        FROM public.condition_item_unlinks
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mbai_readonly') THEN
                GRANT SELECT ON readonly.condition_item_unlinks TO mbai_readonly;
            END IF;
        END
        $$;
        """
    )
    _swap_event_kind_check(_EVENT_KIND_AFTER)


def downgrade() -> None:
    bind = op.get_bind()
    present = bind.execute(
        sa.text(
            "SELECT (SELECT count(*) FROM condition_evidence WHERE origin = 'manual')"
            " + (SELECT count(*) FROM condition_item_unlinks)"
            f" + (SELECT count(*) FROM condition_events WHERE {_in('kind', _NEW)})"
        )
    ).scalar()
    if present:
        raise RuntimeError(
            f"{present} manual link(s), unlink(s) or link event(s) exist; they record her decisions. "
            "Downgrading would have to delete them, so it stops here."
        )
    _swap_event_kind_check(_EVENT_KIND_BEFORE)
    op.execute("DROP VIEW IF EXISTS readonly.condition_item_unlinks")
    op.execute("DROP TABLE condition_item_unlinks")
    op.execute(
        "ALTER TABLE condition_evidence DROP CONSTRAINT ck_condition_evidence_evidenceorigin"
    )
    op.execute(
        "ALTER TABLE condition_evidence DROP CONSTRAINT fk_condition_evidence_linked_by_user_id_users"
    )
    op.execute("ALTER TABLE condition_evidence DROP COLUMN page")
    op.execute("ALTER TABLE condition_evidence DROP COLUMN linked_by_user_id")
    op.execute("ALTER TABLE condition_evidence DROP COLUMN origin")
